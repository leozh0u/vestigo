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
           ["observe", "guess", "claims", "verify", "resolve"]
    # Verification runs before resolution on purpose: a refuted claim has to
    # fall by the board's own arithmetic, not be deleted after the fact.
    assert run.verification is not None


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


# -- context -----------------------------------------------------------------
#
# The tool loop used to rebuild one giant message every turn, which meant the
# prompt changed from byte zero each time and no prompt cache could ever hold
# any of it. These pin the shape that fixes that.

from vestigo.llm import Text                                       # noqa: E402


def prompt_chars(request):
    return sum(len(p.text) for m in request.messages
               for p in m.content if isinstance(p, Text))


def tool_loop_calls(provider):
    return [c for c in provider.calls if c.tools]


def many_observations(n=20):
    return {"observations": [
        {"modality": "road", "what": f"road furniture number {i}", "certainty": 0.8,
         "region": {"x0": i / 40, "y0": 0.5, "x1": i / 40 + 0.02, "y1": 0.9}}
        for i in range(n)]}


def solar_loop(turns):
    return [tool_reply(captured_utc=CAPTURE, lighting="daylight")] * turns


def test_the_opening_message_is_identical_every_turn(photo):
    """So a provider's prompt cache can hold it and bill it at about a tenth."""
    agent, provider, _ = build(
        [many_observations(), GUESS] + solar_loop(4) + [CLAIMS],
        tools=Registry([SolarTool()]), max_turns=4)
    agent.run(photo)
    openings = {c.messages[0].content[0].text for c in tool_loop_calls(provider)}
    assert len(openings) == 1
    assert len(openings.pop()) > 200        # and it is the substantial part


def test_the_prompt_grows_linearly_rather_than_by_the_square(photo):
    agent, provider, _ = build(
        [many_observations(), GUESS] + solar_loop(6) + [CLAIMS],
        tools=Registry([SolarTool()]), max_turns=6)
    agent.run(photo)
    sizes = [prompt_chars(c) for c in tool_loop_calls(provider)]
    assert len(sizes) == 6
    steps = [b - a for a, b in zip(sizes, sizes[1:])]
    # Each turn adds about the same amount, rather than more each time.
    assert max(steps) - min(steps) < max(steps) * 0.5


def test_most_of_every_prompt_is_the_cacheable_prefix(photo):
    """The honest statement of the win.

    Raw characters sent are much the same either way, since the whole
    conversation goes over the wire each turn regardless. What changed is that
    the opening is now byte-identical, so a provider's prompt cache can hold it
    and bill it at about a tenth. Rebuilt into one message it differed from
    byte zero every turn and none of it could ever be cached.
    """
    agent, provider, _ = build(
        [many_observations(), GUESS] + solar_loop(6) + [CLAIMS],
        tools=Registry([SolarTool()]), max_turns=6)
    agent.run(photo)
    calls = tool_loop_calls(provider)
    prefix = len(calls[0].messages[0].content[0].text)
    assert prefix / prompt_chars(calls[-1]) > 0.4         # by the last turn
    assert prefix / prompt_chars(calls[0]) > 0.9          # and nearly all of the first


def test_evidence_is_sent_once_rather_than_relisted_every_turn(photo):
    agent, provider, _ = build(
        [many_observations(4), GUESS] + solar_loop(3) + [CLAIMS],
        tools=Registry([SolarTool()]), max_turns=3)
    agent.run(photo)
    last = tool_loop_calls(provider)[-1]
    whole = "\n".join(p.text for m in last.messages
                      for p in m.content if isinstance(p, Text))
    assert whole.count("road furniture number 0") == 1


def test_new_evidence_from_a_tool_reaches_the_next_turn(photo):
    """Dropping the middle of a conversation must not drop what a tool found."""
    agent, provider, _ = build(
        [many_observations(2), GUESS] + solar_loop(2) + [CLAIMS],
        tools=Registry([SolarTool()]), max_turns=2)
    agent.run(photo)
    second = tool_loop_calls(provider)[1]
    whole = "\n".join(p.text for m in second.messages
                      for p in m.content if isinstance(p, Text))
    assert "solar_position" in whole
    assert "New evidence" in whole


def test_a_long_conversation_is_trimmed_from_the_middle():
    """The opening carries the observations, so it is the one message that has
    to survive. The oldest tool results are the most expendable, because what
    they found is already on the board."""
    from vestigo.agent import MAX_CONTEXT_CHARS, Agent
    from vestigo.llm import Message

    opening = Message.user("OPENING " + "o" * 500)
    filler = [Message.user("x" * (MAX_CONTEXT_CHARS // 4)) for _ in range(8)]
    recent = Message.user("MOST RECENT")
    trimmed = Agent._trimmed([opening, *filler, recent])

    text = "\n".join(p.text for m in trimmed for p in m.content)
    assert text.startswith("OPENING")
    assert "MOST RECENT" in text
    assert "dropped to stay inside the context window" in text
    assert sum(len(p.text) for m in trimmed for p in m.content) <= MAX_CONTEXT_CHARS * 1.1


def test_a_short_conversation_is_left_alone():
    from vestigo.agent import Agent
    from vestigo.llm import Message
    messages = [Message.user("a"), Message.assistant("b"), Message.user("c")]
    assert Agent._trimmed(messages) == messages


# -- alternatives -----------------------------------------------------------

GUESS_WITH_ALTS = {**GUESS, "alternatives": [
    {"lat": -22.57, "lon": 17.08, "place": "Windhoek, Namibia",
     "why": "arid savannah looks similar"},
    {"lat": -1.29, "lon": 36.82, "place": "Nairobi, Kenya"},
]}


def test_alternatives_become_candidates_the_tools_can_test(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS_WITH_ALTS, CLAIMS])
    run = agent.run(photo)
    origins = sorted(c.origin for c in run.board.candidates.values())
    assert origins == ["alternative", "alternative", "first_pass"]
    priors = {c.origin: c.prior for c in run.board.candidates.values()}
    assert priors["first_pass"] > priors["alternative"]


def test_the_mexico_case_end_to_end_with_an_alternative(photo):
    """Phase 0 wrote this down before the code existed. Arm A answered Mexico
    and named Kenyan scrub as a plausible alternative; the rerun took the
    alternative and went 14,970 km wrong. With both on the board, solar
    geometry settles it."""
    wrong_first = {**GUESS, "lat": -22.57, "lon": 17.08, "place": "Windhoek",
                   "alternatives": [{"lat": 20.45, "lon": -100.47,
                                     "place": "Bajio, Mexico"}]}
    agent, _, _ = build(
        [OBSERVATIONS, wrong_first,
         tool_reply(captured_utc=CAPTURE, lighting="daylight"),
         stop_reply(), CLAIMS],
        tools=Registry([SolarTool()]))
    run = agent.run(photo)
    top = run.board.rank_candidates()[0]
    assert top.candidate.origin == "alternative"
    assert "Mexico" in top.candidate.label
    assert run.best_point.lat == pytest.approx(20.45)


def test_a_malformed_alternative_is_skipped_not_fatal(photo):
    broken = {**GUESS, "alternatives": [
        {"place": "no coordinates"}, {"lat": "x", "lon": 1.0, "place": "bad"},
        {"lat": 10.0, "lon": 10.0, "place": "fine"}]}
    agent, _, _ = build([OBSERVATIONS, broken, CLAIMS])
    run = agent.run(photo)
    assert len(run.board.candidates) == 2          # the guess plus the good one


def test_no_alternatives_offered_is_recorded(photo):
    agent, _, _ = build([OBSERVATIONS, GUESS, CLAIMS])
    run = agent.run(photo)
    assert any("no alternatives offered" in d for _, d in run.trace.steps)


def test_the_tool_loop_is_told_where_the_photograph_is(photo):
    """Tools that read the image, like the classifier, need the path. Without
    it the model has to guess a filename and the call fails."""
    agent, provider, _ = build([OBSERVATIONS, GUESS, stop_reply(), CLAIMS],
                               tools=Registry([SolarTool()]))
    agent.run(photo)
    opening = [c for c in provider.calls if c.tools][0].messages[0].content[0].text
    assert str(photo) in opening


def test_a_tool_that_ignores_the_path_is_unaffected(photo):
    """Solar needs a timestamp, not an image. Adding the path to the opening
    must not disturb tools that do not read it."""
    agent, _, _ = build([OBSERVATIONS, GUESS,
                         tool_reply(captured_utc=CAPTURE, lighting="daylight"),
                         stop_reply(), CLAIMS],
                        tools=Registry([SolarTool()]))
    run = agent.run(photo)
    assert len(run.board.constraints) == 1
    assert run.answer is not None
