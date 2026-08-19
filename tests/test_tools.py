"""Tests for the tool contract.

The behaviour worth pinning down is what happens around the tool rather than
inside it: that a failure is recorded instead of thrown, that the cache is keyed
on the version so a bumped tool does not serve stale answers, and that one tool
call produces exactly one evidence record with everything it found hanging off
that record.
"""
import json

import pytest

from vestigo.board import Board, Level, LongitudeBand
from vestigo.geo import LatLon
from vestigo.tools.base import (
    CandidateProposal,
    DiskCache,
    Registry,
    Tool,
    ToolInputError,
    ToolResult,
    attach,
    validate_inputs,
)

MEXICO = LatLon(20.450895, -100.467564)


class FakeSolar(Tool):
    """Stands in for the real solar tool until Phase 1 builds it."""

    name = "solar_band"
    version = "1"
    description = "Longitude band from a UTC capture time and local solar noon"
    input_schema = {
        "type": "object",
        "properties": {
            "captured_utc": {"type": "string"},
            "light": {"type": "string", "enum": ["front", "back", "side"]},
            "slack_deg": {"type": "number"},
        },
        "required": ["captured_utc"],
    }

    def __init__(self, cache=None):
        super().__init__(cache)
        self.calls = 0

    def _run(self, captured_utc, light="front", slack_deg=10.0):
        self.calls += 1
        return self.result(
            value={"lon_lo": -115.0, "lon_hi": -85.0},
            summary=f"{captured_utc} puts local solar noon near -100",
            constraints=(
                LongitudeBand(id="", description="solar time", lo=-115.0, hi=-85.0,
                              soft_deg=slack_deg, weight=0.9),
            ),
            candidates=(CandidateProposal(MEXICO, label="Queretaro", prior=0.4),),
        )


class Broken(Tool):
    name = "broken"
    description = "Always fails"
    input_schema = {"type": "object", "properties": {}}

    def _run(self, **inputs):
        raise RuntimeError("overpass timed out")


class Live(Tool):
    name = "live"
    description = "Hits something that changes"
    deterministic = False
    input_schema = {"type": "object", "properties": {"q": {"type": "string"}}}

    def __init__(self, cache=None):
        super().__init__(cache)
        self.calls = 0

    def _run(self, q=""):
        self.calls += 1
        return self.result(value=self.calls, summary="searched")


# -- the spec --------------------------------------------------------------

def test_spec_is_the_shape_the_model_api_wants():
    spec = FakeSolar().spec()
    assert set(spec) == {"name", "description", "input_schema"}
    assert spec["input_schema"]["required"] == ["captured_utc"]


def test_a_tool_without_a_name_is_a_mistake_caught_at_construction():
    class Nameless(Tool):
        input_schema = {"type": "object", "properties": {}}

        def _run(self, **inputs):
            return self.result()

    with pytest.raises(ValueError):
        Nameless()


# -- validation ------------------------------------------------------------

def test_missing_required_input():
    with pytest.raises(ToolInputError):
        FakeSolar()(light="front")


def test_unexpected_input():
    with pytest.raises(ToolInputError):
        FakeSolar()(captured_utc="2024-04-20 21:35:52", heading=94.5)


def test_wrong_type():
    with pytest.raises(ToolInputError):
        FakeSolar()(captured_utc=1713648952)


def test_enum_is_enforced():
    with pytest.raises(ToolInputError):
        FakeSolar()(captured_utc="x", light="sideways")


def test_a_boolean_is_not_a_number():
    schema = {"type": "object", "properties": {"n": {"type": "number"}}}
    validate_inputs(schema, {"n": 3})
    with pytest.raises(ToolInputError):
        validate_inputs(schema, {"n": True})


# -- failure ---------------------------------------------------------------

def test_a_failing_tool_returns_a_result_rather_than_raising():
    result = Broken()()
    assert result.ok is False
    assert "overpass timed out" in result.error
    assert result.constraints == ()


def test_a_failed_call_still_lands_on_the_board():
    board = Board("t")
    registry = Registry([Broken()])
    result = registry.call(board, "broken")
    assert result.ok is False
    assert len(board.evidence) == 1
    assert len(board.constraints) == 0
    ev = next(iter(board.evidence.values()))
    assert "error" in ev.result


# -- attaching to the board ------------------------------------------------

def test_one_call_becomes_one_evidence_record_that_everything_cites():
    board = Board("rural_7ee09e498b")
    result = FakeSolar()(captured_utc="2024-04-20 21:35:52")
    ev = attach(board, result)

    assert len(board.evidence) == 1
    assert len(board.constraints) == 1
    assert len(board.candidates) == 1
    constraint = next(iter(board.constraints.values()))
    candidate = next(iter(board.candidates.values()))
    assert ev.id in constraint.evidence_ids
    assert ev.id in candidate.evidence_ids
    assert candidate.origin == "solar_band"
    assert ev.inputs == {"captured_utc": "2024-04-20 21:35:52"}
    assert ev.result == {"lon_lo": -115.0, "lon_hi": -85.0}


def test_two_calls_do_not_collide_on_constraint_ids():
    board = Board("t")
    tool = FakeSolar()
    attach(board, tool(captured_utc="a"))
    attach(board, tool(captured_utc="b"))
    assert len(board.constraints) == 2
    assert len(set(board.constraints)) == 2


def test_a_tool_cannot_put_a_claim_on_the_board():
    """The contract has no route for it, which is the point. Only the board
    mints claims, and only from evidence that is already on it."""
    assert not hasattr(ToolResult, "claims")
    board = Board("t")
    attach(board, FakeSolar()(captured_utc="2024-04-20 21:35:52"))
    assert board.claims == {}
    assert board.resolve().answer is None


def test_registry_call_wires_a_successful_result_up():
    board = Board("t")
    registry = Registry([FakeSolar()])
    assert "solar_band" in registry and len(registry) == 1
    registry.call(board, "solar_band", captured_utc="2024-04-20 21:35:52")
    assert len(board.constraints) == 1
    assert board.rank_candidates()[0].admissibility == 1.0


def test_registry_rejects_a_duplicate_name():
    registry = Registry([FakeSolar()])
    with pytest.raises(ValueError):
        registry.add(FakeSolar())


def test_registry_reports_an_unknown_tool():
    with pytest.raises(KeyError):
        Registry().get("solar_band")


# -- cache -----------------------------------------------------------------

def test_a_second_call_with_the_same_inputs_does_not_do_the_work(tmp_path):
    tool = FakeSolar(DiskCache(tmp_path))
    first = tool(captured_utc="2024-04-20 21:35:52")
    second = tool(captured_utc="2024-04-20 21:35:52")
    assert tool.calls == 1
    assert first.cached is False and second.cached is True
    assert second.value == first.value


def test_different_inputs_miss(tmp_path):
    tool = FakeSolar(DiskCache(tmp_path))
    tool(captured_utc="a")
    tool(captured_utc="b")
    assert tool.calls == 2


def test_a_version_bump_invalidates_the_cache(tmp_path):
    cache = DiskCache(tmp_path)
    old = FakeSolar(cache)
    old(captured_utc="a")

    class FakeSolarV2(FakeSolar):
        version = "2"

    new = FakeSolarV2(cache)
    new(captured_utc="a")
    assert new.calls == 1


def test_a_tool_that_hits_something_live_is_never_cached(tmp_path):
    tool = Live(DiskCache(tmp_path))
    tool(q="x")
    tool(q="x")
    assert tool.calls == 2


def test_a_failure_is_not_cached(tmp_path):
    cache = DiskCache(tmp_path)
    tool = Broken(cache)
    tool()
    assert list(tmp_path.glob("**/*.json")) == []


def test_a_corrupt_cache_entry_is_a_miss_not_a_crash(tmp_path):
    cache = DiskCache(tmp_path)
    tool = FakeSolar(cache)
    tool(captured_utc="a")
    for p in tmp_path.glob("**/*.json"):
        p.write_text("{not json")
    tool(captured_utc="a")
    assert tool.calls == 2


def test_constraints_survive_the_cache(tmp_path):
    """A cached result has to rebuild its constraints as real objects, since an
    eval rerun works entirely off cache hits and would otherwise lose them."""
    cache = DiskCache(tmp_path)
    tool = FakeSolar(cache)
    tool(captured_utc="2024-04-20 21:35:52")

    board = Board("t")
    cached = FakeSolar(cache)(captured_utc="2024-04-20 21:35:52")
    assert cached.cached is True
    attach(board, cached)
    constraint = next(iter(board.constraints.values()))
    assert isinstance(constraint, LongitudeBand)
    assert constraint.lo == -115.0 and constraint.weight == 0.9
    assert board.rank_candidates()[0].admissibility == 1.0


def test_the_cache_key_ignores_argument_order(tmp_path):
    a = DiskCache.key("t", "1", {"a": 1, "b": 2})
    b = DiskCache.key("t", "1", {"b": 2, "a": 1})
    assert a == b


def test_a_tool_result_round_trips():
    result = FakeSolar()(captured_utc="2024-04-20 21:35:52")
    again = ToolResult.from_dict(json.loads(json.dumps(result.to_dict())))
    assert again.value == result.value
    assert again.constraints[0].lo == result.constraints[0].lo
    assert again.candidates[0].point == result.candidates[0].point


class FakeMeta(Tool):
    """Emits the constraint type that carries code with it, which is the one
    that can go wrong quietly on the way through the cache."""

    name = "meta_rules"
    description = "Country set from a road-furniture observation"
    input_schema = {"type": "object", "properties": {"cue": {"type": "string"}}}

    def _run(self, cue=""):
        from vestigo.board import RegionSet
        return self.result(
            value={"codes": ["GB", "TH", "JP"]},
            summary="left-hand traffic",
            constraints=(RegionSet(id="", description="left-hand traffic",
                                   codes=frozenset({"GB", "TH", "JP"}),
                                   resolver=lambda p: "MX"),),
        )


def test_a_cached_region_set_abstains_rather_than_vetoing(tmp_path):
    """The resolver is code, so it cannot survive a JSON cache. Losing it has
    to cost the constraint its vote, never cost the truth its candidacy. This
    is the one place where a silent failure would look like a working system
    that has quietly stopped ruling anything out, so it gets its own test."""
    cache = DiskCache(tmp_path)
    fresh = FakeMeta(cache)(cue="road markings")
    assert fresh.constraints[0].resolver is not None

    cached = FakeMeta(cache)(cue="road markings")
    assert cached.cached is True
    assert cached.constraints[0].resolver is None
    assert cached.constraints[0].codes == frozenset({"GB", "TH", "JP"})

    board = Board("t")
    attach(board, cached)
    board.add_candidate(MEXICO, prior=1.0)
    assert board.rank_candidates()[0].admissibility == 1.0
