"""One interface over every model provider, and the machinery that stops it
costing more than it should.

Nothing above this layer names a vendor. The agent asks for a job to be done,
a router decides which model does it, and a provider carries it out. Swapping
Sonnet for Kimi or for something running on the laptop is a line in a config,
not an edit to the agent.

That matters for two reasons beyond tidiness.

The eval is the largest expense in the project and its whole point is running
the same images repeatedly. Every response is therefore cached on disk, keyed
partly on a sample index, so asking for three samples of an image gives three
different answers the first time and costs nothing every time after. A rerun of
a hundred-image eval should be free unless something actually changed.

And the project's thesis is calibration, which is a property of a model rather
than of this code. Being able to run the same eval against two vendors turns
"which model do we use" from a cost decision into a result.

Money is tracked rather than estimated. Every call records what it used and
what it cost, a budget can refuse to spend past a ceiling, and a model with no
price on file reports its cost as unknown rather than as zero. Silently costing
nothing is the one failure mode a budget must never have.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import StrEnum

CACHE_DIR = pathlib.Path(".cache/llm")


class LLMError(RuntimeError):
    """The provider could not answer."""


class BudgetExceeded(LLMError):
    """The call was refused because it would spend past the ceiling."""


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------

class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class Text:
    text: str

    def to_dict(self) -> dict:
        return {"type": "text", "text": self.text}


@dataclass(frozen=True, slots=True)
class Image:
    """An image, carried as raw bytes so the provider decides the encoding."""

    data: bytes
    media_type: str = "image/jpeg"

    @classmethod
    def from_path(cls, path: pathlib.Path | str) -> "Image":
        p = pathlib.Path(path)
        kinds = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
        return cls(p.read_bytes(), kinds.get(p.suffix.lower(), "image/jpeg"))

    @property
    def b64(self) -> str:
        return base64.b64encode(self.data).decode()

    def to_dict(self) -> dict:
        # The digest rather than the bytes, so cache keys stay small and a
        # logged request does not carry a megabyte of photograph.
        return {"type": "image", "media_type": self.media_type,
                "sha256": hashlib.sha256(self.data).hexdigest()}


Part = Text | Image


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: tuple[Part, ...]

    @classmethod
    def user(cls, *parts: Part | str) -> "Message":
        return cls(Role.USER, tuple(Text(p) if isinstance(p, str) else p for p in parts))

    @classmethod
    def assistant(cls, *parts: Part | str) -> "Message":
        return cls(Role.ASSISTANT,
                   tuple(Text(p) if isinstance(p, str) else p for p in parts))

    def to_dict(self) -> dict:
        return {"role": str(self.role), "content": [p.to_dict() for p in self.content]}


# --------------------------------------------------------------------------
# Cost
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Price:
    """Dollars per million tokens.

    `cache_read` is what a cached prompt prefix costs, usually about a tenth of
    the input rate. `batch` is the multiplier for asynchronous work, usually a
    half, and it applies to evals because nothing is waiting on them.
    """

    input: float
    output: float
    cache_read: float | None = None
    batch: float = 0.5

    @property
    def cached_rate(self) -> float:
        return self.cache_read if self.cache_read is not None else self.input * 0.1


# Verify against the provider's own page before trusting any of these. Prices
# move faster than a file in a repository does. A model absent from this table
# is not free, it is unpriced, and the code says so rather than reporting zero.
PRICING: dict[str, Price] = {
    "claude-opus-5": Price(5.0, 25.0),
    "claude-sonnet-5": Price(3.0, 15.0),
    "claude-haiku-4-5-20251001": Price(1.0, 5.0),
}


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0          # part of input_tokens that was a cache hit
    model: str = ""
    batched: bool = False

    @property
    def cost_usd(self) -> float | None:
        """None when the model has no price on file. Never zero by default."""
        price = PRICING.get(self.model)
        if price is None:
            return None
        fresh = max(0, self.input_tokens - self.cached_tokens)
        total = (fresh * price.input
                 + self.cached_tokens * price.cached_rate
                 + self.output_tokens * price.output) / 1_000_000
        return total * (price.batch if self.batched else 1.0)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            model=self.model if self.model == other.model else "mixed",
            batched=self.batched and other.batched,
        )


@dataclass(frozen=True, slots=True)
class Completion:
    """What came back."""

    text: str
    model: str
    usage: Usage
    structured: dict | None = None      # parsed, when a schema was asked for
    tool_calls: tuple[dict, ...] = ()
    stop_reason: str = ""
    cached: bool = False                # served from this project's disk cache
    elapsed_s: float = 0.0

    @property
    def cost_usd(self) -> float:
        """What this call actually cost. A cache hit costs nothing."""
        if self.cached:
            return 0.0
        return self.usage.cost_usd or 0.0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "model": self.model,
            "usage": {"input_tokens": self.usage.input_tokens,
                      "output_tokens": self.usage.output_tokens,
                      "cached_tokens": self.usage.cached_tokens,
                      "model": self.usage.model,
                      "batched": self.usage.batched},
            "structured": self.structured,
            "tool_calls": list(self.tool_calls),
            "stop_reason": self.stop_reason,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Completion":
        return cls(
            text=d["text"],
            model=d["model"],
            usage=Usage(**d["usage"]),
            structured=d.get("structured"),
            tool_calls=tuple(d.get("tool_calls", ())),
            stop_reason=d.get("stop_reason", ""),
        )


class Budget:
    """A ceiling that refuses rather than warns.

    An advisory budget is a budget that gets exceeded. This one raises before
    the call goes out, using an estimate, and records the real figure after.

    A model with no price on file counts as unpriced. By default that is
    refused, because a budget that treats unknown as zero is worse than no
    budget: it reports everything is fine right up until the invoice.
    """

    def __init__(self, limit_usd: float | None = None, *, allow_unpriced: bool = False):
        self.limit_usd = limit_usd
        self.allow_unpriced = allow_unpriced
        self.entries: list[tuple[str, Usage]] = []
        # Images run in parallel, so check-then-record is a read-modify-write
        # across threads. Without the lock several calls can each see room that
        # only one of them has, and the ceiling leaks by roughly the number of
        # workers times the cost of one call.
        self._lock = threading.Lock()

    @property
    def spent_usd(self) -> float:
        return sum(u.cost_usd or 0.0 for _, u in self.entries)

    @property
    def remaining_usd(self) -> float:
        return float("inf") if self.limit_usd is None else self.limit_usd - self.spent_usd

    @property
    def unpriced_calls(self) -> int:
        return sum(1 for _, u in self.entries if u.cost_usd is None)

    def check(self, model: str, estimated_usd: float = 0.0) -> None:
        with self._lock:
            self._check(model, estimated_usd)

    def _check(self, model: str, estimated_usd: float) -> None:
        if model not in PRICING and not self.allow_unpriced:
            raise BudgetExceeded(
                f"no price on file for {model!r}. Add it to PRICING, or build the "
                "budget with allow_unpriced=True and accept that spend is untracked."
            )
        if self.limit_usd is not None and self.spent_usd + estimated_usd > self.limit_usd:
            raise BudgetExceeded(
                f"would spend ${self.spent_usd + estimated_usd:.4f} against a "
                f"${self.limit_usd:.2f} ceiling"
            )

    def record(self, label: str, usage: Usage) -> None:
        with self._lock:
            self.entries.append((label, usage))

    def by_label(self) -> dict[str, float]:
        """Where the money went, which is the number worth looking at."""
        out: dict[str, float] = {}
        for label, usage in self.entries:
            out[label] = out.get(label, 0.0) + (usage.cost_usd or 0.0)
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def summary(self) -> str:
        parts = [f"${self.spent_usd:.4f} over {len(self.entries)} calls"]
        if self.limit_usd is not None:
            parts.append(f"of a ${self.limit_usd:.2f} ceiling")
        if self.unpriced_calls:
            parts.append(f"({self.unpriced_calls} unpriced)")
        return " ".join(parts)


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Request:
    """One thing to ask a model.

    `sample` is what makes repeat sampling and caching coexist. Every eval has
    to sample each image more than once, since a single sample reports a median
    that moves 40 km on rerun. Sample 0, 1 and 2 are three different cache
    entries, so the first run costs three calls and every rerun costs nothing
    while still carrying three distinct answers.
    """

    messages: tuple[Message, ...]
    system: str = ""
    tools: tuple[dict, ...] = ()
    schema: dict | None = None          # ask for structured output
    max_tokens: int = 2048
    temperature: float = 1.0
    sample: int = 0
    label: str = "call"                 # what this is for, used in the ledger

    def fingerprint(self, provider: str, model: str) -> str:
        payload = json.dumps({
            "provider": provider,
            "model": model,
            "system": self.system,
            "messages": [m.to_dict() for m in self.messages],
            "tools": list(self.tools),
            "schema": self.schema,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "sample": self.sample,
        }, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def estimate_tokens(self) -> int:
        """Rough input size, for the budget check that happens before the call.

        Four characters to a token for text, and a flat 1,600 for an image,
        which is mid-range for a photograph. Deliberately crude: it exists to
        stop a runaway loop, not to predict an invoice.
        """
        chars = len(self.system) + sum(
            len(p.text) for m in self.messages for p in m.content if isinstance(p, Text)
        )
        images = sum(1 for m in self.messages for p in m.content if isinstance(p, Image))
        return chars // 4 + images * 1600 + len(json.dumps(self.tools)) // 4


class CompletionCache:
    """Responses on disk, so a rerun of an eval costs nothing.

    The single largest saving available. A hundred-image eval gets rerun a
    dozen times while iterating, and only the run where something changed
    should cost anything.
    """

    def __init__(self, root: pathlib.Path | str = CACHE_DIR):
        self.root = pathlib.Path(root)
        self.hits = 0
        self.misses = 0

    def path(self, provider: str, key: str) -> pathlib.Path:
        return self.root / provider / f"{key}.json"

    def get(self, provider: str, key: str) -> Completion | None:
        p = self.path(provider, key)
        if not p.exists():
            self.misses += 1
            return None
        try:
            hit = Completion.from_dict(json.loads(p.read_text()))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            self.misses += 1
            return None            # a corrupt entry is a miss, not a crash
        self.hits += 1
        return replace(hit, cached=True)

    def put(self, provider: str, key: str, completion: Completion) -> None:
        p = self.path(provider, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(completion.to_dict(), indent=2) + "\n")

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

class Provider(ABC):
    """One vendor. Subclasses implement `_send` and nothing else.

    `complete` handles the caching, the budget check and the accounting, so
    those cannot be forgotten by a provider added later.
    """

    name: str = ""
    default_model: str = ""

    def __init__(self, model: str = "", *, cache: CompletionCache | None = None,
                 budget: Budget | None = None, batched: bool = False):
        self.model = model or self.default_model
        self.cache = cache
        self.budget = budget
        self.batched = batched
        if not self.name or not self.model:
            raise ValueError(f"{type(self).__name__} needs a name and a model")

    @abstractmethod
    def _send(self, request: Request, model: str) -> Completion:
        """Do the call. Raise on failure."""

    def complete(self, request: Request, model: str | None = None) -> Completion:
        model = model or self.model
        key = request.fingerprint(self.name, model)

        if self.cache:
            hit = self.cache.get(self.name, key)
            if hit is not None:
                return hit

        if self.budget:
            price = PRICING.get(model)
            estimate = 0.0
            if price:
                estimate = (request.estimate_tokens() * price.input
                            + request.max_tokens * price.output) / 1_000_000
                if self.batched:
                    estimate *= price.batch
            self.budget.check(model, estimate)

        started = time.perf_counter()
        completion = self._send(request, model)
        completion = replace(completion, elapsed_s=time.perf_counter() - started)

        if self.budget:
            self.budget.record(request.label, completion.usage)
        if self.cache:
            self.cache.put(self.name, key, completion)
        return completion

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.model!r})"


class Router:
    """Which model does which job.

    The whole point of splitting the work by job. Reading a photograph and
    listing what is in it is high volume and barely reasons, so it belongs on
    the cheapest model that can see. Deciding which of five clues to chase next
    is where a better model actually shows, and it runs a handful of times per
    image rather than constantly.

    Routing those two to the same model is the most expensive mistake available
    here, and it is the default everywhere unless something like this exists.
    """

    def __init__(self, default: Provider, jobs: dict[str, Provider] | None = None):
        self.default = default
        self.jobs = dict(jobs or {})

    def for_job(self, job: str) -> Provider:
        return self.jobs.get(job, self.default)

    def complete(self, job: str, request: Request) -> Completion:
        return self.for_job(job).complete(replace(request, label=job))

    def providers(self) -> list[Provider]:
        seen, out = set(), []
        for provider in [self.default, *self.jobs.values()]:
            if id(provider) not in seen:
                seen.add(id(provider))
                out.append(provider)
        return out

    def __repr__(self) -> str:
        jobs = ", ".join(f"{k}={v.model}" for k, v in self.jobs.items())
        return f"Router(default={self.default.model!r}{', ' + jobs if jobs else ''})"


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a reply.

    Models wrap JSON in prose or in a fenced block often enough that a bare
    `json.loads` fails on answers that are otherwise fine. This tries the whole
    string first and falls back to the outermost braces.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in reply: {text[:120]!r}")
    return json.loads(text[start:end + 1])
