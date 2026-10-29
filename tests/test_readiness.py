"""No-network regression checks for replay, grounding and concurrent budgets."""
import concurrent.futures
import copy
import json
import socket
import threading
import urllib.request

import pytest

from vestigo.agent import Agent
from vestigo.board import Board, Level, Support
from vestigo.demo import load_recording, scripted_run, validate_recording
from vestigo.ledger import Ledger
from vestigo.llm import (Budget, BudgetExceeded, CacheMiss, Completion,
                         CompletionCache, LLMError, Message, Provider, Request,
                         Router, Usage)
from vestigo.providers import AnthropicProvider, FakeProvider
from vestigo.tools.base import Registry, Tool

MODEL = "claude-sonnet-5"


def request():
    return Request(messages=(Message.user("hello"),), max_tokens=1000)


def test_in_flight_calls_reserve_budget_before_another_can_start():
    started, release = threading.Event(), threading.Event()
    budget = Budget(.02)

    class SlowProvider(Provider):
        name = "slow"
        default_model = MODEL

        def _send(self, request, model):
            started.set()
            assert release.wait(2)
            return Completion("done", model, Usage(1, 1000, model=model))

    provider = SlowProvider(budget=budget)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(provider.complete, request())
        try:
            assert started.wait(2)
            with pytest.raises(BudgetExceeded):
                provider.complete(request())
        finally:
            release.set()
        assert first.result().text == "done"
    assert budget.remaining_usd == pytest.approx(.02 - .015003)


def test_failed_request_releases_its_reserved_capacity():
    budget = Budget(.02)
    provider = FakeProvider([LLMError("failed"), "ok"], model=MODEL, budget=budget)
    with pytest.raises(LLMError):
        provider.complete(request())
    assert budget.remaining_usd == .02
    assert provider.complete(request()).text == "ok"


def test_cache_only_never_falls_through_to_provider(tmp_path):
    provider = FakeProvider(["must not run"], model=MODEL,
                            cache=CompletionCache(tmp_path), cache_only=True)
    with pytest.raises(CacheMiss, match="no request sent"):
        provider.complete(request())
    assert provider.calls == []


def test_cache_only_hit_is_free_even_when_budget_is_zero(tmp_path):
    cache = CompletionCache(tmp_path)
    FakeProvider(["recorded"], model=MODEL, cache=cache).complete(request())
    provider = FakeProvider([], model=MODEL, cache=cache, cache_only=True, budget=Budget(0))
    assert provider.complete(request()).text == "recorded"
    assert provider.calls == []
    assert provider.budget.spent_usd == 0


def test_sync_requests_cannot_claim_batch_prices():
    with pytest.raises(ValueError, match="Batch API"):
        AnthropicProvider(model=MODEL, batched=True)


@pytest.mark.parametrize("limit", [float("nan"), float("inf"), -1])
def test_invalid_budget_limits_cannot_disable_the_guard(limit):
    with pytest.raises(ValueError):
        Budget(limit)


@pytest.mark.parametrize("kwargs", [{"input_tokens": -1}, {"output_tokens": True},
                                     {"input_tokens": 1, "cached_tokens": 2}])
def test_invalid_usage_cannot_reduce_recorded_spend(kwargs):
    with pytest.raises(ValueError):
        Usage(**kwargs)


def test_parallel_runs_capture_only_their_own_calls():
    budget = Budget(1)
    gate = threading.Barrier(2)

    def one(tokens):
        with budget.capture() as entries:
            gate.wait(timeout=2)
            budget.record("reason", Usage(tokens, model=MODEL))
            return entries

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.map(one, [10, 20])
    assert a[0][1].input_tokens == 10
    assert b[0][1].input_tokens == 20
    assert len(budget.entries) == 2


def test_separate_ledger_instances_do_not_overwrite_each_other(tmp_path):
    path = tmp_path / "spend.json"
    a, b = Ledger(path), Ledger(path)
    a.record(1.25)
    b.record(.75)
    assert a.spent().usd == 2
    assert b.spent().calls == 2


def test_concurrent_ledger_writers_preserve_every_record(tmp_path):
    path = tmp_path / "spend.json"
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda _: Ledger(path).record(.1), range(20)))
    assert Ledger(path).spent().usd == 2
    assert Ledger(path).spent().calls == 20


@pytest.mark.parametrize("payload", [{}, {"months": []},
                                     {"months": {"2026-10": {"usd": -1, "calls": 1}}}])
def test_malformed_ledger_is_refused(tmp_path, payload):
    path = tmp_path / "spend.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(BudgetExceeded):
        Ledger(path)


class BrokenTool(Tool):
    name = "broken"

    def _run(self):
        raise ValueError("no result")


def test_failed_tool_result_cannot_support_a_claim():
    board = Board("failure")
    registry = Registry([BrokenTool()])
    registry.call(board, "broken")
    ev = next(iter(board.evidence.values()))
    claim = board.add_claim(Level.COUNTRY, "Mexico", supports=[Support(ev.id, 1)])
    assert ev.max_strength == 0
    assert not claim.grounded
    assert board.resolve().answer is None


def test_tool_replay_miss_never_executes_the_tool():
    class Uncallable(BrokenTool):
        def _run(self):
            pytest.fail("cache-only tool reached its implementation")

    result = Uncallable(cache_only=True)()
    assert not result.ok and "offline" in result.error


@pytest.mark.parametrize("case", ["landmark", "rural", "declined"])
def test_recorded_demos_have_valid_sources_and_links(case, monkeypatch):
    def no_network(*a, **kw):
        pytest.fail("recorded replay used the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    record, source = load_recording(case)
    assert source["source"].startswith("results/traces_v9/")
    assert record["steps"]
    if case == "declined":
        assert record["final"]["answer"] is None


def test_recorded_demo_rejects_an_invented_citation():
    record, _ = load_recording("landmark")
    corrupt = copy.deepcopy(record)
    next(s for s in corrupt["steps"] if s["kind"] == "claim")["cites"] = ["e99999"]
    with pytest.raises(ValueError, match="missing or future evidence"):
        validate_recording(corrupt)


def test_scripted_demo_exercises_current_grounding_without_network(monkeypatch):
    def no_network(*a, **kw):
        pytest.fail("scripted example used the network")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    result = scripted_run()
    assert result["spent_usd"] == 0 and result["paid_requests"] == 0
    assert result["accepted_level"] == "country"
    assert any("invented-id" in rejection for rejection in result["rejected"])


def test_malformed_model_claims_are_rejected_without_losing_the_run(tmp_path):
    image = tmp_path / "input.jpg"
    image.write_bytes(b"synthetic")
    replies = [{"observations": [{"modality": "vegetation", "what": "scrub"}]},
               {"lat": 0, "lon": 0, "place": "candidate"},
               {"claims": [None, {"value": "bad", "level": "country",
                                  "supports": [{"evidence_id": "e1", "strength": "NaN"}]},
                            {"value": "good", "level": "country",
                             "supports": [{"evidence_id": "e1", "strength": .9}]}]}]
    agent = Agent(Router(FakeProvider(replies, model=MODEL)))
    run = agent.run(image)
    assert len(run.rejected) == 3
    assert len(run.board.claims) == 1


def test_bad_first_pass_coordinates_do_not_crash_the_run(tmp_path):
    image = tmp_path / "input.jpg"
    image.write_bytes(b"synthetic")
    agent = Agent(Router(FakeProvider([{"observations": []}, {"lat": "NaN", "lon": 0}],
                                     model=MODEL)))
    run = agent.run(image)
    assert not run.board.candidates and run.answer is None
    assert any("unusable coordinates" in detail for _, detail in run.trace.steps)


@pytest.mark.parametrize("absolute_output", [False, True])
def test_clean_checkout_dry_harness_uses_gallery_only_for_scripted_mode(
        tmp_path, monkeypatch, capsys, absolute_output):
    from eval import harness
    import sys
    root = tmp_path / "checkout"
    root.mkdir()
    manifest = [{"id": "demo", "source": "im2gps", "file": "demo.jpg",
                 "truth": {"lat": 20, "lon": -100}}]
    (root / "data").mkdir()
    (root / "data/manifest.json").write_text(json.dumps(manifest))
    gallery = root / "site/public/photos"
    gallery.mkdir(parents=True)
    (gallery / "demo.jpg").write_bytes(b"synthetic gallery image")
    monkeypatch.setattr(harness, "ROOT", root)
    destination = tmp_path / "outside/eval.json" if absolute_output else root / "output/eval.json"
    arguments = ["harness", "--dry", "--samples", "1"]
    if absolute_output:
        arguments += ["--out", str(destination)]
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: pytest.fail("network used"))
    assert harness.main() == 0
    report = json.loads(destination.read_text())
    assert report["mode"] == "scripted" and report["spent_usd"] == 0
    assert not (root / ".cache/spend.json").exists()
    output = capsys.readouterr().out
    assert "no photograph is interpreted" in output
    assert "CORRECT AT THE LEVEL CLAIMED" not in output
    assert "expected calibration error" not in output
    assert f"wrote {destination if absolute_output else 'output/eval.json'}" in output
    assert report["metrics_valid"] is False
    assert harness.image_for(manifest[0], dry=True) == gallery / "demo.jpg"
    assert harness.image_for(manifest[0]) == root / "data/images/demo.jpg"
