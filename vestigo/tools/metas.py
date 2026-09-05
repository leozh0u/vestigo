"""The meta tool: what the photograph shows about the country it is in.

The other tools in this project answer questions the model could have answered
itself, which is why five eval runs measured them firing and changing nothing.
This one is different in a way worth being precise about, because "the model
already knows Japan drives on the left" is true and is not the objection it
sounds like.

The model knows the fact. What it does not do is **act** on it. It will read
left-hand traffic, say so in its reasoning, and then answer with a right-hand
country, because nothing in a chat response forces the two to agree. Reading a
fact and being bound by it are different, and only the second one is a system.

So this tool takes no judgement from the model beyond what it can see. It asks
which side traffic drives on, what script the signs use, what colour the centre
line is, and turns each answer into a constraint that multiplies wrong
countries toward zero. The model supplies the observation. The table supplies
the consequence, and the table is written down where anyone can check it.

## It proposes nothing

No candidates, ever. This is the same discipline as the solar tool: a
constraint eliminates, and a photograph showing left-hand traffic is not
evidence for any particular one of the seventy-four countries that qualify. A
tool that answered "so it is probably Japan" would be inventing a preference
the evidence does not contain.

## Cost

Nothing. No network, no model call. The polygons are on disk and the table is
in `vestigo/metas.py`. It is the only tool here that is free to run, which also
makes it the only one that can be used on every image without thinking about it.
"""
from __future__ import annotations

from ..board import Level
from ..metas import METAS, constraint_for, country_resolver
from .base import Tool, ToolResult

# Grouped for the schema, so the model picks one value per question rather than
# assembling a list of keys and inventing one. Mutually exclusive within a
# group: a road has one centre line and traffic goes one way.
QUESTIONS: dict[str, tuple[str, ...]] = {
    "traffic_side": ("left", "right"),
    "centre_line": ("yellow", "white"),
}

# Scripts are not exclusive. A sign in Hong Kong carries Han and Latin, and a
# photograph can legitimately show two.
SCRIPT_KEYS = tuple(sorted(k[len("script_"):] for k in METAS if k.startswith("script_")))

REACH = Level.COUNTRY


class MetaTool(Tool):
    """Turn visible country-level properties into constraints."""

    name = "country_metas"
    version = "1"
    description = (
        "Report what the photograph shows about which country it is in: which "
        "side of the road traffic keeps, what script any signage uses, and "
        "what colour the road centre line is. Each answer eliminates countries "
        "where that is not true, so answer only from what you can actually see "
        "in the image and leave a field out if you cannot see it. Do not infer "
        "a value from where you already think the photograph was taken; a "
        "guess entered here becomes a constraint on the answer and will "
        "eliminate the right country as readily as the wrong one. Traffic side "
        "is the most useful single observation available: it rules out roughly "
        "150 countries either way."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "traffic_side": {
                "type": "string", "enum": list(QUESTIONS["traffic_side"]),
                "description": "Which side vehicles drive on. Read it from "
                               "parked cars, the driver's seat, or road "
                               "markings, not from your guess about the place.",
            },
            "centre_line": {
                "type": "string", "enum": list(QUESTIONS["centre_line"]),
                "description": "Colour of the line dividing opposing traffic.",
            },
            "scripts": {
                "type": "array", "items": {"type": "string", "enum": list(SCRIPT_KEYS)},
                "description": "Scripts legible on any signage. More than one "
                               "is normal; many countries sign bilingually.",
            },
        },
    }
    deterministic = True

    def __init__(self, cache=None, resolver=None):
        super().__init__(cache)
        # Loaded here, not on first call. The eval harness builds the tool once
        # and then hands it to six worker threads, so a lazy load would have
        # several of them racing to read the same three megabytes. Constructing
        # eagerly also means a missing boundary file fails at startup, where
        # the harness can report it and carry on, rather than inside a run.
        #
        # A resolver may be injected instead, which is how the tests run with
        # no boundary file at all.
        self._resolver = resolver if resolver is not None else country_resolver()

    def resolver(self):
        return self._resolver

    def _run(self, **inputs) -> ToolResult:
        keys: list[str] = []
        if side := inputs.get("traffic_side"):
            keys.append(f"traffic_{side}")
        if line := inputs.get("centre_line"):
            keys.append(f"centre_line_{line}")
        for script in inputs.get("scripts", []) or []:
            keys.append(f"script_{script}")

        # Validation has already rejected anything outside the schema's enums,
        # so an unknown key here is a bug in this file rather than bad input,
        # and it should be loud. Silently dropping it would mean the model
        # reported something, nothing acted on it, and nothing said so.
        unknown = [k for k in keys if k not in METAS]
        if unknown:
            raise ValueError(f"no meta named {unknown!r}; the schema and the "
                             f"table have drifted apart")
        if not keys:
            return self.result(
                value={"observed": [], "countries_ruled_out": 0},
                summary="nothing in the image was reported that narrows the country",
                resolves_to=None, max_strength=0.0,
            )

        resolver = self.resolver()
        constraints = tuple(constraint_for(k, resolver=resolver) for k in keys)

        described = [METAS[k].description for k in keys]
        # How many countries survive everything reported. A count, not a
        # confidence: it says how much was eliminated, not how likely the
        # remainder is.
        surviving: set[str] | None = None
        for k in keys:
            meta = METAS[k]
            allowed = meta.codes if meta.inside else None
            if allowed is None:
                continue
            surviving = set(allowed) if surviving is None else surviving & set(allowed)

        return self.result(
            value={
                "observed": keys,
                "descriptions": described,
                "narrowed_to": sorted(surviving) if surviving is not None else None,
            },
            summary=(f"{'; '.join(described)}"
                     + (f", leaving {len(surviving)} countries"
                        if surviving is not None else "")),
            constraints=constraints,
            # A country-level fact, and never finer. Left-hand traffic narrows
            # the world and says nothing about which street.
            resolves_to=REACH,
            # These constrain; they do not support a claim about anywhere in
            # particular. Nothing should cite this as evidence *for* a place.
            max_strength=0.0,
        )
