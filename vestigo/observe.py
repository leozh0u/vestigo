"""Structured readings of a photograph.

Observations are the roots of the evidence graph. Every piece of evidence
eventually rests on something somebody saw in the image, and `derived_from`
walks back to here. Until now those roots were bare strings, which meant the
board's independence rule had nothing underneath it: two readings of the same
signboard only count once if something knows they are the same signboard.

That is what this module is for. It is not a richer description format. It is
the part that decides which readings are the same reading.

Two observations are treated as one when they look at the same object. The test
is that their image regions overlap and their modalities match, which is cheap,
local to the image, and needs no world knowledge. When they do, the second
declares the first as its parent, so the board's existing grouping sees them as
one root and counts them once. No synthetic nodes and no change to the board.

Certainty here is whether the thing is there at all, which is a different
question from what it implies about a location. A blurred sign can be read with
low certainty and still settle a country once read. That second question is
`Support.strength` on the board, and keeping the two apart is the same split as
Evidence against Support, one level down.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from .board import Board, Evidence, EvidenceKind, Level

# How far each kind of observation can locate a photograph on its own.
#
# This is the ceiling the first agent run needed and did not have. It
# overclaimed on 28% of answers against the bare model's 11%, and six of those
# were point-level claims backed by scenery. Vegetation narrows a climate band
# and a continent. It cannot find a street, whatever strength a model writes
# next to it.
#
# Text is the exception, and Phase 0 measured why: nearly every street-level
# answer in the baseline came from reading something. A legible sign can name
# the place outright, so text is allowed to reach a district and everything
# else stops at country or region.
MODALITY_REACH: dict["Modality", Level] = {
    "text": Level.DISTRICT,
    "infrastructure": Level.REGION,   # utility markings and cabinets carry codes
    "road": Level.REGION,             # route markers and paint schemes are regional
    "architecture": Level.REGION,
    "vehicle": Level.COUNTRY,         # plates and models are national at best
    "vegetation": Level.COUNTRY,
    "terrain": Level.COUNTRY,
    "sky": Level.COUNTRY,             # the solar tool constrains; the sight of it does not
    "other": Level.COUNTRY,
}

# Two readings of the same modality count as one object when their image
# regions overlap by at least this much. Chosen loose rather than tight: the
# cost of merging two genuinely separate objects is a little confidence given
# up, and the cost of missing a merge is a claim that looks corroborated when
# one observation is doing all the work.
SAME_OBJECT_IOU = 0.4


class Modality(StrEnum):
    """What kind of thing was seen.

    The split is by what a reading can be checked against, not by what it looks
    like. TEXT goes to search, VEGETATION goes to a species range, ROAD goes to
    a rule base, SKY goes to the solar tool. A modality with nowhere to send it
    is not worth extracting.
    """

    TEXT = "text"                       # signage, plates, painted markings
    VEGETATION = "vegetation"
    ARCHITECTURE = "architecture"
    ROAD = "road"                       # surface, markings, barriers, furniture
    VEHICLE = "vehicle"
    TERRAIN = "terrain"
    SKY = "sky"                         # sun, shadow, cloud, stars
    INFRASTRUCTURE = "infrastructure"   # poles, wires, cabinets, hydrants
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Region:
    """Where in the frame something is, in fractions of width and height.

    Normalised so it survives resizing, since the extractor and anything
    checking its work will not agree on pixel dimensions.
    """

    x0: float
    y0: float
    x1: float
    y1: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.x0 < self.x1 <= 1.0 and 0.0 <= self.y0 < self.y1 <= 1.0):
            raise ValueError(f"region out of range or inverted: {self}")

    @property
    def area(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def iou(self, other: "Region") -> float:
        """Intersection over union. Zero when they do not touch."""
        w = min(self.x1, other.x1) - max(self.x0, other.x0)
        h = min(self.y1, other.y1) - max(self.y0, other.y0)
        if w <= 0.0 or h <= 0.0:
            return 0.0
        overlap = w * h
        return overlap / (self.area + other.area - overlap)

    def to_dict(self) -> dict:
        return {"x0": self.x0, "y0": self.y0, "x1": self.x1, "y1": self.y1}

    @classmethod
    def from_dict(cls, d: dict) -> "Region":
        return cls(float(d["x0"]), float(d["y0"]), float(d["x1"]), float(d["y1"]))


@dataclass(frozen=True, slots=True)
class Observation:
    """One thing seen in the photograph.

    `what` is the description. `text` holds the characters verbatim when the
    modality is TEXT, separately from the description, because a search tool
    needs the string and not a sentence about the string.
    """

    id: str
    modality: Modality
    what: str
    region: Region | None = None
    text: str | None = None
    certainty: float = 1.0
    parent: str | None = None       # set when this reads the same object as another
    note: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.certainty <= 1.0:
            raise ValueError(f"certainty must be in [0, 1], got {self.certainty}")
        if not self.what.strip():
            raise ValueError("an observation with no description is not an observation")

    def same_object_as(self, other: "Observation") -> bool:
        """Are these two readings of one thing.

        Needs both a shared modality and overlapping regions. Modality alone
        would merge every tree in a forest; region alone would merge a shop sign
        with the building behind it, which are separate pieces of evidence that
        happen to sit in the same place.
        """
        if self.modality is not other.modality:
            return False
        if self.region is None or other.region is None:
            return False
        return self.region.iou(other.region) >= SAME_OBJECT_IOU

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "modality": str(self.modality),
            "what": self.what,
            "region": self.region.to_dict() if self.region else None,
            "text": self.text,
            "certainty": self.certainty,
            "parent": self.parent,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Observation":
        return cls(
            id=d["id"],
            modality=Modality(d["modality"]),
            what=d["what"],
            region=Region.from_dict(d["region"]) if d.get("region") else None,
            text=d.get("text"),
            certainty=float(d.get("certainty", 1.0)),
            parent=d.get("parent"),
            note=d.get("note", ""),
        )


class ObservationSet:
    """The observations from one photograph, with the duplicates linked up.

    Linking happens once, on construction. Grouping is union-find over the
    same-object test, which is quadratic in the number of observations and
    trivial at the twenty or so a photograph produces. Doing it lazily would
    buy nothing and would let a caller read an unlinked set by accident.
    """

    def __init__(self, observations: Iterable[Observation] = ()):
        self._by_id: dict[str, Observation] = {}
        self._counter = 0
        for obs in observations:
            self.add(obs)

    def add(self, obs: Observation) -> Observation:
        """Add an observation, linking it to any existing reading of the same
        object so the board counts them once."""
        if obs.id in self._by_id:
            raise ValueError(f"observation {obs.id!r} is already in the set")
        if obs.parent is not None and obs.parent not in self._by_id:
            raise KeyError(f"observation cites unknown parent {obs.parent!r}")
        if obs.parent is None:
            for existing in self._by_id.values():
                if obs.same_object_as(existing):
                    obs = replace(obs, parent=self.root_of(existing.id))
                    break
        self._by_id[obs.id] = obs
        return obs

    def observe(self, modality: Modality | str, what: str, **kw: Any) -> Observation:
        """Add an observation and let the set name it."""
        self._counter += 1
        return self.add(Observation(id=f"o{self._counter}",
                                    modality=Modality(modality), what=what, **kw))

    def root_of(self, obs_id: str) -> str:
        """Walk up to the observation that first saw this object."""
        seen: set[str] = set()
        current = obs_id
        while True:
            obs = self._by_id.get(current)
            if obs is None or obs.parent is None or obs.parent in seen:
                return current
            seen.add(current)
            current = obs.parent

    def groups(self) -> list[list[Observation]]:
        """Observations clustered by the object they read, largest first."""
        buckets: dict[str, list[Observation]] = {}
        for obs in self._by_id.values():
            buckets.setdefault(self.root_of(obs.id), []).append(obs)
        return sorted(buckets.values(), key=len, reverse=True)

    def by_modality(self, modality: Modality | str) -> list[Observation]:
        return [o for o in self._by_id.values() if o.modality is Modality(modality)]

    def texts(self) -> list[str]:
        """Every verbatim string, for the search tool. Deduplicated, in order."""
        out: list[str] = []
        for obs in self._by_id.values():
            value = (obs.text or "").strip()
            if value and value not in out:
                out.append(value)
        return out

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self):
        return iter(self._by_id.values())

    def __getitem__(self, obs_id: str) -> Observation:
        return self._by_id[obs_id]

    def __contains__(self, obs_id: str) -> bool:
        return obs_id in self._by_id

    def to_list(self) -> list[dict]:
        return [o.to_dict() for o in self._by_id.values()]

    @classmethod
    def from_list(cls, rows: Sequence[dict]) -> "ObservationSet":
        """Rebuild without relinking, since the parents are already recorded."""
        out = cls()
        for row in rows:
            obs = Observation.from_dict(row)
            out._by_id[obs.id] = obs
            out._counter = max(out._counter, _numeric_suffix(obs.id))
        return out

    def __repr__(self) -> str:
        return f"ObservationSet({len(self)} observations, {len(self.groups())} objects)"


def _numeric_suffix(obs_id: str) -> int:
    digits = "".join(c for c in obs_id if c.isdigit())
    return int(digits) if digits else 0


def attach_observations(board: Board, observations: ObservationSet) -> list[Evidence]:
    """Put a set of observations on a board as evidence records.

    Parents are written through to `derived_from`, so two readings of one
    signboard land in the same independence group and compound to nothing.

    Insertion order is already dependency order, because `ObservationSet.add`
    can only ever link an observation to one already in the set. So this walks
    the set as it stands, which keeps the evidence ids running parallel to the
    observation ids and saves a sort that could only reorder them.
    """
    written: dict[str, Evidence] = {}
    for obs in observations:
        parent = written.get(obs.parent) if obs.parent else None
        reach = MODALITY_REACH.get(str(obs.modality), Level.COUNTRY)
        if obs.modality is Modality.TEXT and not (obs.text or "").strip():
            # Text that could not be read is a sign, not a place name, and a
            # sign nobody can read locates nothing finer than the rest of the
            # scene does.
            reach = Level.COUNTRY
        written[obs.id] = board.add_evidence(
            source="observe",
            summary=obs.what,
            kind=EvidenceKind.OBSERVATION,
            inputs={"modality": str(obs.modality),
                    "region": obs.region.to_dict() if obs.region else None},
            result={"what": obs.what, "text": obs.text, "certainty": obs.certainty},
            derived_from=(parent.id,) if parent else (),
            resolves_to=reach,
            # How sure the extractor is the thing is there caps how much any
            # claim may lean on it. Seeing something faintly cannot support a
            # claim more strongly than seeing it clearly.
            max_strength=obs.certainty,
        )
    return list(written.values())


# --------------------------------------------------------------------------
# The extractor's contract
# --------------------------------------------------------------------------

# What the observation extractor has to return. This is the schema handed to
# the model, so anything it cannot express is something the model cannot be
# asked for. Regions are required rather than optional because they are what
# makes two readings comparable, and an extractor that omits them silently
# turns every duplicate into fresh corroboration.
OBSERVATION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "observations": {
            "type": "array",
            "description": (
                "Everything in the photograph that could bear on where it was "
                "taken. Report what is visible, not what it implies. 'a red "
                "octagonal sign reading ALTO' and not 'this is Mexico'."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "modality": {
                        "type": "string",
                        "enum": [str(m) for m in Modality],
                        "description": "What kind of thing this is.",
                    },
                    "what": {
                        "type": "string",
                        "description": "What is visible, in one line.",
                    },
                    "text": {
                        "type": "string",
                        "description": (
                            "Characters exactly as they appear, when the "
                            "modality is text. Transcribe, do not translate."
                        ),
                    },
                    "region": {
                        "type": "object",
                        "description": (
                            "Where it sits in the frame, as fractions of width "
                            "and height from the top left."
                        ),
                        "properties": {
                            "x0": {"type": "number"},
                            "y0": {"type": "number"},
                            "x1": {"type": "number"},
                            "y1": {"type": "number"},
                        },
                        "required": ["x0", "y0", "x1", "y1"],
                    },
                    "certainty": {
                        "type": "number",
                        "description": (
                            "How sure you are the thing is there at all, from 0 "
                            "to 1. Not how much it narrows the location."
                        ),
                    },
                },
                "required": ["modality", "what", "region", "certainty"],
            },
        }
    },
    "required": ["observations"],
}


def parse_observations(payload: dict) -> ObservationSet:
    """Turn an extractor's reply into a linked set.

    Anything malformed raises rather than being dropped. A silently discarded
    observation is a claim quietly losing its support, which would show up as a
    slightly worse number nobody could account for.
    """
    rows = payload.get("observations")
    if not isinstance(rows, list):
        raise ValueError("payload has no 'observations' list")
    out = ObservationSet()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"observation {i} is not an object")
        missing = {"modality", "what"} - set(row)
        if missing:
            raise ValueError(f"observation {i} is missing {sorted(missing)}")
        try:
            modality = Modality(row["modality"])
        except ValueError:
            raise ValueError(
                f"observation {i} has unknown modality {row['modality']!r}"
            ) from None
        out.observe(
            modality,
            row["what"],
            region=Region.from_dict(row["region"]) if row.get("region") else None,
            text=row.get("text"),
            certainty=float(row.get("certainty", 1.0)),
        )
    return out
