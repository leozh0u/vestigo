"""The loop.

Five steps, and the order comes out of what Phase 0 measured rather than out of
what an agent usually looks like.

  1. observe    a cheap model lists what is in the photograph
  2. first pass the reasoning model makes its own guess, unaided
  3. tools      it calls tools, which add evidence and constraints
  4. claims     it proposes claims, each citing evidence already on the board
  5. resolve    the board answers at the finest level that clears its threshold

Step 2 is the one that looks out of place. A bare model call is already very
good on landmark photographs, 2.6 km median, and an agent that throws that away
and rebuilds from tool output starts behind its own baseline. So the first
guess is kept as a candidate with a prior, and the tools' job is to filter it
rather than to replace it. On the Thailand image the model derived a correct
longitude band and then picked a point inside it six times worse than the guess
it already had. This ordering is that mistake made structurally impossible.

The discipline the whole project rests on is enforced here rather than
requested. A claim must cite evidence that is already on the board. The model
cannot assert one, and a claim citing an id that does not exist is rejected and
recorded as rejected, not quietly dropped and not quietly accepted.
"""
from __future__ import annotations

import pathlib
from collections.abc import Iterable
from dataclasses import dataclass, field

from .board import Board, Level, Resolution, Support
from .geo import LatLon
from .llm import Budget, Image, Message, Request, Router, Text, Usage
from .observe import OBSERVATION_SCHEMA, attach_observations, parse_observations
from .tools.base import Registry

MAX_TOOL_TURNS = 6

# Roughly 25k tokens of conversation. The board holds the real state, so the
# transcript is allowed to be forgetful; it exists to tell the model what has
# already been tried.
MAX_CONTEXT_CHARS = 100_000

SYSTEM = """You work out where a photograph was taken.

Answer at the most specific level the evidence supports and then stop. A
country at high confidence is a better answer than a street address you cannot
defend. You are not scored on how close you land. You are scored on whether the
claim you actually made was true.

Every claim must cite evidence already on the board, by id. A claim citing
nothing does not count towards the answer. Neither does one citing an id that
does not exist, and inventing an id is worse than making no claim at all.

Two readings of the same object are one piece of evidence, not two. A sign, and
the language of the writing on that sign, is one signboard.
"""

GUESS_SCHEMA = {
    "type": "object",
    "properties": {
        "lat": {"type": "number"},
        "lon": {"type": "number"},
        "place": {"type": "string", "description": "What you think this is, in words."},
        "alternatives": {
            "type": "array",
            "description": (
                "Up to three other places this could plausibly be, each somewhere "
                "you would look next if the first answer were wrong. Name real "
                "alternatives rather than points near your first guess. This is "
                "what the tools test against, so a guess with no alternatives "
                "cannot be checked."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "place": {"type": "string"},
                    "why": {"type": "string",
                            "description": "What in the image points here."},
                },
                "required": ["lat", "lon", "place"],
            },
        },
        "granularity": {
            "type": "string",
            "enum": ["continent", "country", "region", "city", "district", "point"],
            "description": "The most specific level you would defend.",
        },
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reasoning": {"type": "string"},
    },
    "required": ["lat", "lon", "granularity", "confidence"],
}

CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "description": "Coarsest first, each one inside the last.",
            "items": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["continent", "country", "region", "city",
                                 "district", "point"],
                    },
                    "value": {"type": "string", "description": "The place named."},
                    "lat": {"type": "number"},
                    "lon": {"type": "number"},
                    "supports": {
                        "type": "array",
                        "description": (
                            "The evidence for this claim. Every id must already "
                            "be on the board."
                        ),
                        "items": {
                            "type": "object",
                            "properties": {
                                "evidence_id": {"type": "string"},
                                "strength": {
                                    "type": "number",
                                    "description": (
                                        "0 to 1. The chance this evidence alone "
                                        "would settle the claim."
                                    ),
                                },
                                "supports": {
                                    "type": "boolean",
                                    "description": "False if it argues against.",
                                },
                            },
                            "required": ["evidence_id", "strength"],
                        },
                    },
                    "confidence": {"type": "string",
                                   "enum": ["high", "medium", "low"]},
                },
                "required": ["level", "value", "supports"],
            },
        }
    },
    "required": ["claims"],
}


def _size(message: Message) -> int:
    return sum(len(p.text) for p in message.content if isinstance(p, Text))


@dataclass(slots=True)
class Trace:
    """What happened, in order, for the write-up and for debugging a run."""

    steps: list[tuple[str, str]] = field(default_factory=list)

    def add(self, step: str, detail: str) -> None:
        self.steps.append((step, detail))

    def __str__(self) -> str:
        return "\n".join(f"{step:<10} {detail}" for step, detail in self.steps)


@dataclass(slots=True)
class Run:
    """One photograph, start to finish."""

    subject: str
    board: Board
    resolution: Resolution
    usage: Usage
    cost_usd: float
    turns: int
    trace: Trace
    rejected: list[str] = field(default_factory=list)

    @property
    def answer(self):
        return self.resolution.answer

    @property
    def best_point(self) -> LatLon | None:
        """The top candidate after constraints, which is what a distance score
        needs. The claim is the real answer; this is the coordinate to plot."""
        ranked = self.board.rank_candidates()
        return ranked[0].point if ranked else None

    def describe(self) -> str:
        head = self.resolution.describe()
        return (f"{self.subject}: {head}\n"
                f"  {len(self.board.evidence)} evidence, "
                f"{len(self.board.constraints)} constraints, "
                f"{len(self.board.candidates)} candidates, "
                f"{self.turns} tool turns, ${self.cost_usd:.4f}")


class Agent:
    """Runs one photograph through the loop.

    Holds no state between runs. Every run gets a fresh board, so two runs of
    the same image are independent, which is what repeat sampling needs.
    """

    def __init__(self, router: Router, tools: Registry | None = None,
                 budget: Budget | None = None, max_turns: int = MAX_TOOL_TURNS):
        self.router = router
        self.tools = tools or Registry()
        self.budget = budget
        self.max_turns = max_turns

    # -- steps -------------------------------------------------------------

    def _observe(self, board: Board, image: Image, trace: Trace, sample: int) -> None:
        """Cheapest call in the run, and the highest volume. Belongs on a small
        model, which is why it is its own job rather than part of the loop."""
        reply = self.router.complete("extract", Request(
            messages=(Message.user(
                "List everything in this photograph that could bear on where it "
                "was taken. Report what is visible, not what it implies.", image),),
            system=SYSTEM,
            schema=OBSERVATION_SCHEMA,
            sample=sample,
        ))
        if not reply.structured:
            trace.add("observe", "extractor returned nothing usable")
            return
        try:
            observations = parse_observations(reply.structured)
        except ValueError as exc:
            trace.add("observe", f"unusable reply: {exc}")
            return
        attach_observations(board, observations)
        trace.add("observe", f"{len(observations)} observations, "
                             f"{len(observations.groups())} distinct objects")

    def _first_pass(self, board: Board, image: Image, context: str,
                    trace: Trace, sample: int) -> None:
        """The unaided guess, kept as a candidate.

        This is the arm A baseline preserved inside the agent. It is strong, and
        an agent that discards it starts behind its own floor.
        """
        summary = "\n".join(f"{e.id}: {e.summary}" for e in board.evidence.values())
        reply = self.router.complete("reason", Request(
            messages=(Message.user(
                f"Where was this taken?\n\nObserved:\n{summary or '(nothing yet)'}"
                + (f"\n\nContext supplied with the photograph:\n{context}" if context else ""),
                image),),
            system=SYSTEM,
            schema=GUESS_SCHEMA,
            sample=sample,
        ))
        guess = reply.structured
        if not guess:
            trace.add("guess", "no first pass returned")
            return
        evidence = board.add_evidence(
            source="first_pass",
            summary=guess.get("reasoning") or guess.get("place", "unaided guess"),
            kind="observation",
            result=guess,
        )
        board.add_candidate(
            LatLon(float(guess["lat"]), float(guess["lon"])),
            label=guess.get("place", ""),
            prior=1.0,
            origin="first_pass",
            evidence_ids=(evidence.id,),
        )

        # The alternatives are what makes a constraint able to do anything. A
        # constraint eliminates candidates, so with one candidate it has
        # nothing to eliminate in favour of and the ranking normalises straight
        # back to 1.0 however badly the answer fits.
        #
        # Phase 0 wrote this case down before the code existed. Arm A answered
        # Mexico and named Kenyan acacia scrub as a plausible alternative; the
        # rerun took the alternative and went 14,970 km wrong. Both on the
        # board, solar geometry settles it, because the sun was 47 degrees up
        # over one and 79 below the horizon over the other.
        alternatives = guess.get("alternatives") or []
        for alt in alternatives[:3]:
            try:
                point = LatLon(float(alt["lat"]), float(alt["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            board.add_candidate(
                point,
                label=alt.get("place", ""),
                # Lower than the first guess, since the model preferred that
                # one. Enough to win if a constraint rules the first one out.
                prior=0.4,
                origin="alternative",
                evidence_ids=(evidence.id,),
            )
        trace.add("guess", f"{guess.get('place', '?')} at "
                           f"{guess['lat']:.3f},{guess['lon']:.3f} "
                           f"({guess.get('granularity')}, {guess.get('confidence')})"
                           + (f", {len(alternatives)} alternatives" if alternatives else
                              ", no alternatives offered"))

    def _brief(self, board: Board, ids: Iterable[str]) -> str:
        return "\n".join(f"{board.evidence[e].id}: {board.evidence[e].summary}"
                         for e in ids)

    def _use_tools(self, board: Board, context: str, trace: Trace, sample: int) -> int:
        """Let the model call tools until it stops asking.

        Written as a conversation that grows rather than as one message rebuilt
        each turn. The first version rebuilt the whole evidence list and the
        whole tool history every turn, which sends the same text once per turn
        and grows with the square of the turn count. Six turns over twenty
        observations paid for those observations six times.

        Here the opening message is byte-identical on every turn, so a
        provider's prompt cache can hold it and bill it at about a tenth. Each
        turn appends only what is new. Growth is linear, and most of it is
        cached.

        Tools add evidence, constraints and candidates. None can write a claim,
        so nothing here reaches the answer except through the board.
        """
        if not len(self.tools):
            return 0

        opening = ("Evidence so far:\n" + self._brief(board, board.evidence)
                   + (f"\n\nContext supplied with the photograph:\n{context}" if context else "")
                   + "\n\nCall a tool if one would narrow this down. If none would, "
                     "say so and stop.")
        messages: list[Message] = [Message.user(opening)]
        seen = set(board.evidence)
        turns = 0

        while turns < self.max_turns:
            reply = self.router.complete("reason", Request(
                messages=tuple(self._trimmed(messages)),
                system=SYSTEM,
                tools=tuple(self.tools.specs()),
                sample=sample,
            ))
            if not reply.tool_calls:
                trace.add("tools", f"stopped after {turns} turns")
                break

            called, results = [], []
            for call in reply.tool_calls:
                name = call.get("name", "")
                called.append(name)
                if name not in self.tools:
                    trace.add("tools", f"asked for unknown tool {name!r}")
                    results.append(f"{name}: no such tool")
                    continue
                result = self.tools.call(board, name, **call.get("input", {}))
                results.append(f"{name}: {result.summary}")
                trace.add("tools", f"{name} -> {result.summary}")

            fresh = [eid for eid in board.evidence if eid not in seen]
            seen.update(board.evidence)
            messages.append(Message.assistant("Called: " + ", ".join(called)))
            messages.append(Message.user(
                "\n".join(results)
                + (f"\n\nNew evidence:\n{self._brief(board, fresh)}" if fresh else "")
                + "\n\nCall another tool, or stop."))
            turns += 1
        return turns

    @staticmethod
    def _trimmed(messages: list[Message]) -> list[Message]:
        """Keep the opening and the most recent exchanges, drop the middle.

        The opening carries the observations and the context, so it is the one
        message that must survive. The oldest tool results are the most
        expendable, because whatever they found is already on the board and the
        board is what the answer is built from. The conversation is a working
        note, not the record.
        """
        budget = MAX_CONTEXT_CHARS
        if sum(_size(m) for m in messages) <= budget:
            return messages
        head, tail = messages[:1], []
        budget -= _size(head[0])
        for message in reversed(messages[1:]):
            if budget - _size(message) < 0:
                break
            tail.insert(0, message)
            budget -= _size(message)
        dropped = len(messages) - len(head) - len(tail)
        if dropped:
            head = head + [Message.user(
                f"({dropped} earlier exchanges dropped to stay inside the context "
                "window. Everything they found is on the board.)")]
        return head + tail

    def _make_claims(self, board: Board, trace: Trace,
                     sample: int) -> list[str]:
        """Ask for claims, and reject any that cite evidence not on the board.

        Rejections are returned rather than swallowed. A model inventing an
        evidence id is the exact failure this project exists to catch, so it has
        to show up in the output of a run and not only in a log.
        """
        summary = "\n".join(f"{e.id}: {e.summary}" for e in board.evidence.values())
        if not summary:
            trace.add("claims", "no evidence on the board, so no claims")
            return []
        reply = self.router.complete("reason", Request(
            messages=(Message.user(
                f"Evidence on the board:\n{summary}\n\n"
                "State the claims this evidence supports, coarsest first. Cite "
                "evidence by id. Do not claim a level you cannot defend."),),
            system=SYSTEM,
            schema=CLAIM_SCHEMA,
            sample=sample,
        ))
        rejected: list[str] = []
        parent: str | None = None
        for row in (reply.structured or {}).get("claims", []):
            supports, bad = [], []
            for s in row.get("supports", []):
                eid = s.get("evidence_id", "")
                if eid in board.evidence:
                    supports.append(Support(eid, float(s.get("strength", 0.0)),
                                            bool(s.get("supports", True))))
                else:
                    bad.append(eid)
            if bad:
                rejected.append(f"{row.get('value', '?')} cited {bad}, not on the board")
            if not supports:
                rejected.append(f"{row.get('value', '?')} cited nothing that exists")
                continue
            try:
                level = Level[row["level"].upper()]
            except (KeyError, AttributeError):
                rejected.append(f"{row.get('value', '?')} used an unknown level")
                continue
            point = None
            if row.get("lat") is not None and row.get("lon") is not None:
                point = LatLon(float(row["lat"]), float(row["lon"]))
            claim = board.add_claim(level, row["value"], supports=supports,
                                    point=point, parent=parent,
                                    stated_confidence=row.get("confidence"))
            parent = claim.id
        trace.add("claims", f"{len(board.claims)} accepted, {len(rejected)} rejected")
        return rejected

    # -- the run -----------------------------------------------------------

    def run(self, image_path: pathlib.Path | str, *, subject: str = "",
            context: str = "", sample: int = 0) -> Run:
        """One photograph, one answer.

        `sample` runs through to every call's cache key, so three samples of one
        image are three distinct answers that cost nothing to reproduce.
        """
        path = pathlib.Path(image_path)
        subject = subject or path.stem
        image = Image.from_path(path)
        board = Board(subject)
        trace = Trace()
        before = self._spent()

        self._observe(board, image, trace, sample)
        self._first_pass(board, image, context, trace, sample)
        turns = self._use_tools(board, context, trace, sample)
        rejected = self._make_claims(board, trace, sample)

        resolution = board.resolve()
        trace.add("resolve", resolution.describe())
        return Run(
            subject=subject,
            board=board,
            resolution=resolution,
            usage=self._usage(),
            cost_usd=self._spent() - before,
            turns=turns,
            trace=trace,
            rejected=rejected,
        )

    def run_samples(self, image_path: pathlib.Path | str, n: int = 3, **kw) -> list[Run]:
        """The same photograph several times.

        Not optional. Run-to-run noise on this data is a 40 km median with a
        14,951 km tail, so one sample cannot tell an improvement from a reroll.
        """
        return [self.run(image_path, sample=i, **kw) for i in range(n)]

    def _spent(self) -> float:
        return self.budget.spent_usd if self.budget else 0.0

    def _usage(self) -> Usage:
        total = Usage()
        if self.budget:
            for _, usage in self.budget.entries:
                total = total + usage
        return total
