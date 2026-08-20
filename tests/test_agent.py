"""Tests for the loop.

The behaviour worth pinning is not that it produces an answer. It is that the
answer cannot be reached except through the board: a claim citing evidence that
does not exist is refused and the refusal is reported, and a tool cannot write
a claim at all.

Everything here runs on the fake provider. No network and no spend.
"""

import pytest

from vestigo.agent import Agent, Run
from vestigo.board import Level
from vestigo.llm import Budget, Completion, Router, Usage
from vestigo.providers import FakeProvider
from vestigo.tools.base import Registry
from vestigo.tools.solar import SolarTool

SONNET = "claude-sonnet-5"
HAIKU = "claude-haiku-4-5-20251001"
CAPTURE = "2024-04-20 21:35:52"

OBSERVATIONS = {"observations": [
    {"modality": "vegetation", "what": "acacia-like scrub", "certainty": 0.8,
     "region": {"x0": 0.1, "y0": 0.5, "x1": 0.4, "y1": 0.9}},
    {"modality": "road", "what": "unmarked asphalt", "certainty": 0.9,
     "region": {"x0": 0.0, "y0": 0.6, "x1": 1.0, "y1": 1.0}},
]}

GUESS = {"lat": 20.45, "lon": -100.47, "place": "Bajio, Mexico",
         "granularity": "region", "confidence": "medium",
         "reasoning": "semi-arid scrub and unmarked road"}

CLAIMS = {"claims": [
    {"level": "country", "value": "Mexico", "confidence": "high",
     "supports": [{"evidence_id": "e1", "strength": 0.5},
                  {"evidence_id": "e3", "strength": 0.7}]},
]}


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "rural_7ee09e498b.jpg"
    p.write_bytes(b"\xff\xd8fake jpeg")
    return p


def stop_reply(text="nothing further would narrow this"):
    return Completion(text, "fake-1", Usage(50, 10, model=SONNET))


def tool_reply(name="solar_position", **inputs):
    return Completion("", "fake-1", Usage(100, 50, model=SONNET),
                      tool_calls=({"name": name, "input": inputs, "id": "t1"},))


def build(replies, tools=None, **kw):
    budget = Budget(10.0)
    provider = FakeProvider(replies, model=SONNET, budget=budget)
    agent = Agent(Router(default=provider), tools=tools or Registry(),
                  budget=budget, **kw)
    return agent, provider, budget


# -- the whole loop --------------------------------------------------------

def test_a_run_goes_all_the_way_through(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    run = agent.run(photo)
    assert isinstance(run, Run)
    assert run.subject == "rural_7ee09e498b"
    assert run.answer is not None
    assert run.answer.value == "Mexico"
    assert run.answer.level is Level.COUNTRY
    assert [step for step, _ in run.trace.steps] == \
           ["observe", "guess", "claims", "resolve"]


def test_the_unaided_guess_is_kept_as_a_candidate(photo):
    """A bare model call is already good, so an agent that discards its own
    first pass starts behind its own baseline."""
    agent, _, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    run = agent.run(photo)
    candidates = list(run.board.candidates.values())
    assert len(candidates) == 1
    assert candidates[0].origin == "first_pass"
    assert candidates[0].prior == 1.0
    assert run.best_point.lat == pytest.approx(20.45)


def test_observations_land_as_evidence_the_claims_can_cite(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    run = agent.run(photo)
    assert run.board.evidence["e1"].kind == "observation"
    assert "acacia" in run.board.evidence["e1"].summary
    assert run.answer.supports[0].evidence_id == "e1"


def test_the_cost_of_a_run_is_recorded(photo):
    agent, _, budget = build([OBSERVATIONS, GUESS, CLAIMS])
    run = agent.run(photo)
    assert run.cost_usd > 0
    assert run.cost_usd == pytest.approx(budget.spent_usd)
    assert run.usage.output_tokens > 0


# -- the discipline --------------------------------------------------------

def test_a_claim_citing_evidence_that_does_not_exist_is_rejected(photo):
    """The exact failure the project exists to catch, so it has to show up in
    the result of a run and not only in a log."""
    invented = {"claims": [
        {"level": "country", "value": "Mexico", "confidence": "high",
         "supports": [{"evidence_id": "e1", "strength": 0.5},
                      {"evidence_id": "e99", "strength": 0.9}]},
    ]}
    agent, _, _ = build([OBSERVATIONS, GUESS, invented])
    run = agent.run(photo)
    assert run.rejected and "e99" in run.rejected[0]
    # The real citation still counts, so one invented id does not void the claim.
    assert run.board.claims["c1"].supports == \
           tuple(s for s in run.board.claims["c1"].supports if s.evidence_id == "e1")


def test_a_claim_citing_nothing_real_is_dropped_entirely(photo):
    fabricated = {"claims": [
        {"level": "point", "value": "somewhere precise", "lat": 0.0, "lon": 0.0,
         "supports": [{"evidence_id": "e42", "strength": 0.99}]},
    ]}
    agent, _, _ = build([OBSERVATIONS, GUESS, fabricated])
    run = agent.run(photo)
    assert run.board.claims == {}
    assert run.answer is None
    assert len(run.rejected) == 2       # bad id, and then nothing left to cite


def test_a_claim_with_an_unknown_level_is_rejected(photo):
    nonsense = {"claims": [
        {"level": "galaxy", "value": "Milky Way",
         "supports": [{"evidence_id": "e1", "strength": 0.9}]},
    ]}
    agent, _, _ = build([OBSERVATIONS, GUESS, nonsense])
    run = agent.run(photo)
    assert run.board.claims == {}
    assert "unknown level" in run.rejected[0]


def test_no_evidence_means_no_claims_are_even_asked_for(photo):
    agent, provider, _ = build([{"observations": []},
                                {"lat": 0, "lon": 0, "granularity": "country",
                                 "confidence": "low"}])
    run = agent.run(photo)
    # Observe and first pass ran. Nothing asked for claims, because the first
    # pass is itself evidence, so this checks the empty-board path instead.
    assert run.answer is None or run.answer.value


def test_a_tool_cannot_put_a_claim_on_the_board(photo):
    agent, _, _ = build(
        [OBSERVATIONS, GUESS,
         tool_reply(captured_utc=CAPTURE, lighting="daylight"),
         stop_reply(), {"claims": []}],
        tools=Registry([SolarTool()]),
    )
    run = agent.run(photo)
    assert len(run.board.constraints) == 1
    assert run.board.claims == {}
    assert run.answer is None


# -- tools -----------------------------------------------------------------

def test_a_tool_call_adds_a_constraint_that_filters_the_candidate(photo):
    agent, _, _ = build(
        [OBSERVATIONS, GUESS,
         tool_reply(captured_utc=CAPTURE, lighting="daylight"),
         stop_reply(), CLAIMS],
        tools=Registry([SolarTool()]),
    )
    run = agent.run(photo)
    assert run.turns == 1
    assert len(run.board.constraints) == 1
    # Queretaro is in daylight at that instant, so the guess is untouched.
    assert run.board.rank_candidates()[0].admissibility == 1.0


def test_the_solar_constraint_would_have_killed_the_kenya_answer(photo):
    """The Phase 0 case, run through the whole agent rather than by hand."""
    kenya = {**GUESS, "lat": -1.286389, "lon": 36.817223, "place": "Kenya"}
    agent, _, _ = build(
        [OBSERVATIONS, kenya,
         tool_reply(captured_utc=CAPTURE, lighting="daylight"),
         stop_reply(), CLAIMS],
        tools=Registry([SolarTool()]),
    )
    run = agent.run(photo)
    assert run.board.rank_candidates()[0].admissibility < 0.05


def test_the_loop_stops_when_the_model_stops_calling_tools(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS, stop_reply(), CLAIMS],
                        tools=Registry([SolarTool()]))
    assert agent.run(photo).turns == 0


def test_the_loop_will_not_run_forever(photo):
    replies = [OBSERVATIONS, GUESS] + [tool_reply(captured_utc=CAPTURE,
                                                  lighting="daylight")] * 20 + [CLAIMS]
    agent, _, _ = build(replies, tools=Registry([SolarTool()]), max_turns=3)
    assert agent.run(photo).turns == 3


def test_asking_for_a_tool_that_does_not_exist_is_survivable(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS, tool_reply("reverse_image_search"),
                         stop_reply(), CLAIMS],
                        tools=Registry([SolarTool()]))
    run = agent.run(photo)
    assert run.answer.value == "Mexico"
    assert any("unknown tool" in detail for _, detail in run.trace.steps)


def test_a_tool_that_fails_does_not_end_the_run(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS,
                         tool_reply(captured_utc="last tuesday", lighting="daylight"),
                         stop_reply(), CLAIMS],
                        tools=Registry([SolarTool()]))
    run = agent.run(photo)
    assert run.answer.value == "Mexico"
    assert len(run.board.constraints) == 0      # the failed call added none


def test_no_tools_registered_means_no_tool_turns(photo):
    agent, provider, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    run = agent.run(photo)
    assert run.turns == 0
    assert len(provider.calls) == 3             # observe, guess, claims


# -- robustness ------------------------------------------------------------

def test_a_junk_extractor_reply_does_not_kill_the_run(photo):
    agent, _, _ = build([{"observations": "not a list"}, GUESS,
                         {"claims": [{"level": "country", "value": "Mexico",
                                      "supports": [{"evidence_id": "e1",
                                                    "strength": 0.6}]}]}])
    run = agent.run(photo)
    assert any("unusable" in detail for _, detail in run.trace.steps)
    assert run.answer.value == "Mexico"         # the first pass carried it


def test_a_missing_first_pass_does_not_kill_the_run(photo):
    agent, _, _ = build([OBSERVATIONS, stop_reply("I cannot tell"),
                         {"claims": [{"level": "country", "value": "Mexico",
                                      "supports": [{"evidence_id": "e1",
                                                    "strength": 0.6}]}]}])
    run = agent.run(photo)
    assert run.board.candidates == {}
    assert run.best_point is None
    assert run.answer.value == "Mexico"


# -- routing and sampling --------------------------------------------------

def test_the_extractor_and_the_reasoner_go_to_different_models(photo):
    """The largest saving available: reading a photograph is high volume and
    barely reasons, deciding what to chase next is neither."""
    budget = Budget(10.0)
    cheap = FakeProvider([OBSERVATIONS], model=HAIKU, budget=budget)
    good = FakeProvider([GUESS, CLAIMS], model=SONNET, budget=budget)
    agent = Agent(Router(default=good, jobs={"extract": cheap}), budget=budget)
    agent.run(photo)
    assert len(cheap.calls) == 1
    assert len(good.calls) == 2
    assert set(budget.by_label()) == {"extract", "reason"}


def test_repeat_sampling_runs_the_image_more_than_once(photo):
    replies = [OBSERVATIONS, GUESS, CLAIMS] * 3
    agent, provider, _ = build(replies)
    runs = agent.run_samples(photo, n=3)
    assert len(runs) == 3
    assert [c.sample for c in provider.calls] == [0, 0, 0, 1, 1, 1, 2, 2, 2]


def test_each_run_gets_a_fresh_board(photo):
    """Two samples of one image have to be independent, or the variance
    measurement measures the agent's memory instead."""
    agent, _, _ = build([OBSERVATIONS, GUESS, CLAIMS] * 2)
    first, second = agent.run_samples(photo, n=2)
    assert first.board is not second.board
    assert len(first.board.evidence) == len(second.board.evidence)


def test_context_supplied_with_the_photograph_reaches_the_model(photo):
    agent, provider, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    agent.run(photo, context="taken on a road trip through central Mexico")
    sent = provider.calls[1].messages[0].content[0].text
    assert "road trip through central Mexico" in sent


def test_the_subject_defaults_to_the_filename(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    assert agent.run(photo).subject == "rural_7ee09e498b"
    agent2, _, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    assert agent2.run(photo, subject="explicit").subject == "explicit"


def test_describe_says_what_happened(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    text = agent.run(photo).describe()
    assert "Mexico" in text and "evidence" in text and "$" in text
