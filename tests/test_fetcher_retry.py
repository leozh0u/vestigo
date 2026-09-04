"""Tests for the fetcher's backoff and rate limiting.

The run that produced 64,881 images lost 166,258 queries to connection errors,
an 87% failure rate, because this file had no retries and no throttle. These
tests exist so that cannot come back quietly.

Nothing here touches the network. What is being tested is the decision to
retry, the shape of the wait, and the distinction between a box that answered
with nothing and a box that never answered.
"""
import sys
import pathlib
import urllib.error

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import fetch_training as ft


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    """Record sleeps instead of taking them, so the suite stays fast."""
    slept: list[float] = []
    monkeypatch.setattr(ft.time, "sleep", slept.append)
    monkeypatch.setattr(ft.LIMITER, "take", lambda: None)
    return slept


def responder(*outcomes):
    """A fake urlopen that yields each outcome in turn."""
    calls = {"n": 0}

    class Body:
        def __init__(self, data): self.data = data
        def read(self): return self.data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def _open(url, timeout=None):
        outcome = outcomes[min(calls["n"], len(outcomes) - 1)]
        calls["n"] += 1
        if isinstance(outcome, Exception):
            raise outcome
        return Body(outcome)

    _open.calls = calls
    return _open


def http_error(code, retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("u", code, "boom", headers, None)


# --------------------------------------------------------------------------
# What gets retried
# --------------------------------------------------------------------------

def test_a_transient_network_error_is_retried_and_can_succeed(monkeypatch, no_waiting):
    """The exact failure that cost the last run 87% of its queries."""
    opener = responder(urllib.error.URLError("connection reset"), b'{"data":[1]}')
    monkeypatch.setattr(ft.urllib.request, "urlopen", opener)
    errors = {}
    assert ft.get("u", 30, errors, label="query") == b'{"data":[1]}'
    assert opener.calls["n"] == 2
    assert errors["retried network"] == 1


def test_it_gives_up_after_the_attempt_budget_and_says_so(monkeypatch, no_waiting):
    opener = responder(urllib.error.URLError("down"))
    monkeypatch.setattr(ft.urllib.request, "urlopen", opener)
    errors = {}
    assert ft.get("u", 30, errors, label="query") is None
    assert opener.calls["n"] == ft.MAX_ATTEMPTS
    assert errors["query: URLError"] == 1


@pytest.mark.parametrize("code", sorted(ft.RETRY_STATUS))
def test_server_side_and_rate_limit_codes_are_retried(monkeypatch, no_waiting, code):
    opener = responder(http_error(code), b"ok")
    monkeypatch.setattr(ft.urllib.request, "urlopen", opener)
    assert ft.get("u", 30, {}, label="query") == b"ok"
    assert opener.calls["n"] == 2


def test_a_client_error_is_not_retried(monkeypatch, no_waiting):
    """A 400 means the request is wrong. Sending it four more times is rude and
    cannot work, and the oversized-bbox path needs the error to reach it."""
    opener = responder(http_error(400))
    monkeypatch.setattr(ft.urllib.request, "urlopen", opener)
    with pytest.raises(urllib.error.HTTPError):
        ft.get("u", 30, {}, label="query")
    assert opener.calls["n"] == 1


# --------------------------------------------------------------------------
# The shape of the wait
# --------------------------------------------------------------------------

def test_the_ceiling_doubles_with_each_attempt():
    ceilings = [max(ft._sleep_for(i) for _ in range(200)) for i in range(4)]
    assert ceilings == sorted(ceilings)
    assert ceilings[3] > ceilings[0] * 2


def test_waits_are_jittered_rather_than_fixed():
    """Threads that fail together and back off by the same amount retry
    together and collide again. Spreading them is the point."""
    draws = {ft._sleep_for(3) for _ in range(50)}
    assert len(draws) > 40


def test_the_wait_is_capped():
    assert all(ft._sleep_for(40) <= ft.MAX_DELAY_S for _ in range(100))


def test_an_explicit_retry_after_beats_the_guess():
    """The server knows when it will be ready, and guessing over the top of
    that is how a client earns a longer ban."""
    assert ft._sleep_for(0, retry_after="7") == 7.0


def test_an_http_date_retry_after_falls_back_rather_than_crashing():
    assert 0.0 <= ft._sleep_for(1, retry_after="Wed, 21 Oct 2026 07:28:00 GMT") <= ft.MAX_DELAY_S


# --------------------------------------------------------------------------
# Empty is not the same as failed
# --------------------------------------------------------------------------

def test_an_empty_box_returns_an_empty_list(monkeypatch, no_waiting):
    monkeypatch.setattr(ft.urllib.request, "urlopen", responder(b'{"data":[]}'))
    assert ft.query("tok", 0.0, 0.0, 6, {}) == []


def test_a_box_that_never_answered_returns_none(monkeypatch, no_waiting):
    """These two were the same value before, which is how a run reported
    166,258 unanswered boxes as if the world had been searched."""
    monkeypatch.setattr(ft.urllib.request, "urlopen",
                        responder(urllib.error.URLError("down")))
    assert ft.query("tok", 0.0, 0.0, 6, {}) is None


def test_an_oversized_box_is_halved_and_retried(monkeypatch, no_waiting):
    """The densest boxes are the best ones in the run, so shrink rather than
    discard."""
    seen = []

    def _open(url, timeout=None):
        seen.append(url)
        if len(seen) == 1:
            raise urllib.error.HTTPError(
                "u", 400, "bad", {},
                __import__("io").BytesIO(b"Please reduce the amount of data you're asking for"))
        class B:
            def read(self): return b'{"data":[{"id":"x"}]}'
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return B()

    monkeypatch.setattr(ft.urllib.request, "urlopen", _open)
    errors = {}
    assert ft.query("tok", 0.0, 0.0, 6, errors) == [{"id": "x"}]
    assert errors["shrunk"] == 1


def test_unreadable_json_is_a_failure_not_an_empty_box(monkeypatch, no_waiting):
    monkeypatch.setattr(ft.urllib.request, "urlopen", responder(b"<html>nope"))
    errors = {}
    assert ft.query("tok", 0.0, 0.0, 6, errors) is None
    assert errors["JSONDecodeError"] == 1


# --------------------------------------------------------------------------
# The rate limiter
# --------------------------------------------------------------------------

def test_the_limiter_holds_the_line_once_the_burst_is_spent():
    limiter = ft.RateLimiter(per_second=50.0, burst=3.0)
    started = ft.time.monotonic()
    for _ in range(9):
        limiter.take()
    elapsed = ft.time.monotonic() - started
    # Three free, six at 50 a second: about 0.12s. Generous bounds, because the
    # assertion is that it waits at all, not that it is a stopwatch.
    assert 0.05 < elapsed < 1.0


def test_the_burst_lets_a_run_start_without_stalling():
    limiter = ft.RateLimiter(per_second=1.0, burst=5.0)
    started = ft.time.monotonic()
    for _ in range(5):
        limiter.take()
    assert ft.time.monotonic() - started < 0.1
