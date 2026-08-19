"""The tool contract.

One shape for every tool, from the trigonometry in the solar solver to an
Overpass query to a web search. Getting this right early is cheaper than
retrofitting it around six tools that each grew their own signature.

What a tool may return: evidence, constraints, and candidate locations.

What a tool may not return: a claim. Tools report what they found. Deciding
what that means for the answer is the board's job, and keeping the two apart is
what stops a tool from asserting a conclusion nobody can audit. A tool that
could write claims would be a tool that could talk the answer up on its own
say-so.

Three other things the contract buys:

`spec()` emits a tool definition in the shape the model API wants, so the same
object serves the agent loop and the API call and the two cannot drift apart.

`deterministic` marks the tools whose results can be cached on disk forever.
Solar geometry for a fixed timestamp is the same answer next week. That matters
for cost: the eval harness is the largest line item in the project and it gets
rerun a dozen times over the same images, so the second run onwards should not
re-hit anything.

Every call is timed and every failure is caught and recorded. A tool that
throws returns a result with `ok=False` rather than ending the run, because a
failed lookup is a normal outcome and the board should record it as one.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from ..board import Board, Constraint, Evidence, EvidenceKind, LatLon

CACHE_DIR = pathlib.Path(".cache/tools")


class ToolInputError(ValueError):
    """The inputs did not match the tool's declared schema."""


@dataclass(frozen=True, slots=True)
class CandidateProposal:
    """A place a tool wants considered. Ids get assigned when it hits the board."""

    point: LatLon
    label: str = ""
    prior: float = 1.0

    def to_dict(self) -> dict:
        return {"point": self.point.to_dict(), "label": self.label, "prior": self.prior}

    @classmethod
    def from_dict(cls, d: dict) -> "CandidateProposal":
        return cls(LatLon.from_dict(d["point"]), d.get("label", ""),
                   float(d.get("prior", 1.0)))


@dataclass(frozen=True, slots=True)
class ToolResult:
    """One tool call, start to finish.

    `value` is whatever the tool computed, kept verbatim so the evidence record
    holds the actual return rather than a summary of it. If a number in the
    write-up cannot be traced back to a `value` on this board, it did not come
    from a tool.
    """

    tool: str
    version: str
    inputs: dict[str, Any]
    ok: bool = True
    value: Any = None
    summary: str = ""
    constraints: tuple[Constraint, ...] = ()
    candidates: tuple[CandidateProposal, ...] = ()
    derived_from: tuple[str, ...] = ()
    error: str | None = None
    cached: bool = False
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "version": self.version,
            "inputs": self.inputs,
            "ok": self.ok,
            "value": self.value,
            "summary": self.summary,
            "constraints": [c.to_dict() for c in self.constraints],
            "candidates": [c.to_dict() for c in self.candidates],
            "derived_from": list(self.derived_from),
            "error": self.error,
            "elapsed_s": self.elapsed_s,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolResult":
        return cls(
            tool=d["tool"],
            version=d["version"],
            inputs=d.get("inputs", {}),
            ok=d.get("ok", True),
            value=d.get("value"),
            summary=d.get("summary", ""),
            constraints=tuple(Constraint.from_dict(c) for c in d.get("constraints", ())),
            candidates=tuple(CandidateProposal.from_dict(c) for c in d.get("candidates", ())),
            derived_from=tuple(d.get("derived_from", ())),
            error=d.get("error"),
            elapsed_s=d.get("elapsed_s", 0.0),
        )


def attach(board: Board, result: ToolResult) -> Evidence:
    """Put a tool result on the board and wire everything it produced to it.

    One tool call becomes exactly one evidence record. Constraints and
    candidates from that call all cite it, so tracing any of them back gives
    the call that produced it, with its inputs and its raw return.

    The dependency runs one way. The board knows nothing about tools; tools
    know about the board. That is why this is a function here and not a method
    on `Board`.
    """
    ev = board.add_evidence(
        source=result.tool,
        summary=result.summary or f"{result.tool} returned",
        kind=EvidenceKind.TOOL,
        inputs=result.inputs,
        result=result.value,
        derived_from=result.derived_from,
    )
    for constraint in result.constraints:
        board.add_constraint(
            replace(constraint, id="",
                    evidence_ids=tuple(constraint.evidence_ids) + (ev.id,))
        )
    for proposal in result.candidates:
        board.add_candidate(
            proposal.point,
            label=proposal.label,
            prior=proposal.prior,
            origin=result.tool,
            evidence_ids=(ev.id,),
        )
    return ev


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------

_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def validate_inputs(schema: dict, inputs: dict) -> None:
    """Check inputs against the subset of JSON Schema the tools actually use.

    Deliberately small. The point is to catch a wrong key or a string where a
    number belongs before a network call goes out, not to implement the spec.
    The same schema is what the model sees, so anything it cannot express is
    something the model cannot be told either.
    """
    props = schema.get("properties", {})
    required = schema.get("required", [])
    for key in required:
        if key not in inputs:
            raise ToolInputError(f"missing required input {key!r}")
    if not schema.get("additionalProperties", False):
        for key in inputs:
            if key not in props:
                raise ToolInputError(f"unexpected input {key!r}")
    for key, value in inputs.items():
        spec = props.get(key, {})
        expected = spec.get("type")
        if expected:
            wanted = _JSON_TYPES.get(expected)
            # bool is an int in Python, and a boolean is never a valid number.
            if wanted and (not isinstance(value, wanted)
                           or (expected in ("number", "integer") and isinstance(value, bool))):
                raise ToolInputError(
                    f"input {key!r} should be {expected}, got {type(value).__name__}"
                )
        if "enum" in spec and value not in spec["enum"]:
            raise ToolInputError(f"input {key!r} must be one of {spec['enum']}, got {value!r}")


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

class DiskCache:
    """Tool results on disk, keyed by tool name, version and inputs.

    Bumping a tool's `version` invalidates its cache without anyone having to
    remember to clear anything, which is the only version scheme that survives
    contact with a rushed evening.
    """

    def __init__(self, root: pathlib.Path | str = CACHE_DIR):
        self.root = pathlib.Path(root)

    @staticmethod
    def key(tool: str, version: str, inputs: dict) -> str:
        payload = json.dumps({"tool": tool, "version": version, "inputs": inputs},
                             sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def path(self, tool: str, key: str) -> pathlib.Path:
        return self.root / tool / f"{key}.json"

    def get(self, tool: str, version: str, inputs: dict) -> ToolResult | None:
        p = self.path(tool, self.key(tool, version, inputs))
        if not p.exists():
            return None
        try:
            result = ToolResult.from_dict(json.loads(p.read_text()))
        except (json.JSONDecodeError, KeyError, ValueError):
            return None            # a corrupt cache entry is a miss, not a crash
        return replace(result, cached=True)

    def put(self, result: ToolResult) -> None:
        p = self.path(result.tool, self.key(result.tool, result.version, result.inputs))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(result.to_dict(), indent=2, default=str) + "\n")


# --------------------------------------------------------------------------
# The tool itself
# --------------------------------------------------------------------------

class Tool(ABC):
    """Base class for every tool.

    Subclasses set the four class attributes and implement `_run`. Calling the
    tool goes through `__call__`, which validates, checks the cache, times the
    call, and turns an exception into a failed result.
    """

    name: ClassVar[str] = ""
    version: ClassVar[str] = "1"
    description: ClassVar[str] = ""
    input_schema: ClassVar[dict] = {"type": "object", "properties": {}}

    # True when the same inputs always give the same answer, which is what
    # makes a result safe to keep on disk indefinitely. Anything hitting a live
    # service that can change under you sets this False.
    deterministic: ClassVar[bool] = True

    def __init__(self, cache: DiskCache | None = None):
        if not self.name:
            raise ValueError(f"{type(self).__name__} has no name")
        self.cache = cache

    def spec(self) -> dict:
        """The tool definition in the shape the model API takes."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def result(
        self,
        *,
        value: Any = None,
        summary: str = "",
        constraints: tuple[Constraint, ...] = (),
        candidates: tuple[CandidateProposal, ...] = (),
        derived_from: tuple[str, ...] = (),
        ok: bool = True,
    ) -> ToolResult:
        """Helper for `_run` so subclasses do not restate the boilerplate."""
        return ToolResult(
            tool=self.name,
            version=self.version,
            inputs={},
            ok=ok,
            value=value,
            summary=summary,
            constraints=tuple(constraints),
            candidates=tuple(candidates),
            derived_from=tuple(derived_from),
        )

    @abstractmethod
    def _run(self, **inputs: Any) -> ToolResult:
        """Do the work. Raise on failure, `__call__` catches it."""

    def __call__(self, **inputs: Any) -> ToolResult:
        validate_inputs(self.input_schema, inputs)

        if self.cache and self.deterministic:
            hit = self.cache.get(self.name, self.version, inputs)
            if hit is not None:
                return hit

        started = time.perf_counter()
        try:
            result = self._run(**inputs)
        except Exception as exc:                       # a failed tool is a normal outcome
            return ToolResult(
                tool=self.name,
                version=self.version,
                inputs=inputs,
                ok=False,
                summary=f"{self.name} failed: {exc}",
                error=f"{type(exc).__name__}: {exc}",
                elapsed_s=time.perf_counter() - started,
            )
        result = replace(
            result,
            tool=self.name,
            version=self.version,
            inputs=inputs,
            elapsed_s=time.perf_counter() - started,
        )
        if self.cache and self.deterministic and result.ok:
            self.cache.put(result)
        return result


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

class Registry:
    """The set of tools an agent run is allowed to use.

    An instance rather than a module global, so an eval can hold a run to a
    named subset of tools and measure what each one is worth.
    """

    def __init__(self, tools: list[Tool] | None = None):
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.add(tool)

    def add(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool
        return tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"no tool named {name!r}")
        return self._tools[name]

    def specs(self) -> list[dict]:
        return [t.spec() for t in self._tools.values()]

    def call(self, board: Board, name: str, **inputs: Any) -> ToolResult:
        """Run a tool and put what it produced on the board."""
        result = self.get(name)(**inputs)
        if result.ok:
            attach(board, result)
        else:
            board.add_evidence(
                source=name,
                summary=result.summary,
                kind=EvidenceKind.TOOL,
                inputs=result.inputs,
                result={"error": result.error},
            )
        return result

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __iter__(self):
        return iter(self._tools.values())
