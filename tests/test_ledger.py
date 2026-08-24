"""Tests for the persistent spend ledger.

`Budget` guards one run, which is the wrong unit for a monthly cap: nothing
stops a two dollar eval being run ten times in a week. These check that the
ledger survives across runs, knows about calendar months, and fails in the safe
direction when it cannot read itself.
"""
import json

import pytest

from vestigo.ledger import Ledger
from vestigo.llm import Budget, BudgetExceeded, Usage

SONNET = "claude-sonnet-5"


def test_spend_survives_across_runs(tmp_path):
    path = tmp_path / "spend.json"
    Ledger(path).record(1.50, calls=10)
    assert Ledger(path).spent().usd == pytest.approx(1.50)
    assert Ledger(path).spent().calls == 10


def test_it_refuses_once_the_month_is_spent(tmp_path):
    ledger = Ledger(tmp_path / "spend.json", monthly_limit_usd=20.0)
    ledger.record(19.50)
    ledger.check(0.40)                                   # still room
    with pytest.raises(BudgetExceeded, match="monthly limit"):
        ledger.check(1.00)


def test_it_says_how_much_is_left(tmp_path):
    ledger = Ledger(tmp_path / "spend.json", monthly_limit_usd=20.0)
    ledger.record(4.00)
    assert ledger.remaining() == pytest.approx(16.0)
    assert "$16.00 of $20.00 left" in ledger.summary()


def test_months_are_kept_apart(tmp_path):
    ledger = Ledger(tmp_path / "spend.json", monthly_limit_usd=20.0)
    ledger.record(18.0, month="2026-07")
    ledger.record(2.0, month="2026-08")
    assert ledger.spent("2026-07").usd == pytest.approx(18.0)
    assert ledger.spent("2026-08").usd == pytest.approx(2.0)
    assert len(ledger.history()) == 2


def test_a_finished_run_folds_in(tmp_path):
    budget = Budget(10.0)
    budget.record("reason", Usage(1_000_000, 0, model=SONNET))
    ledger = Ledger(tmp_path / "spend.json", monthly_limit_usd=20.0)
    ledger.absorb(budget)
    assert ledger.spent().usd == pytest.approx(budget.spent_usd)
    assert ledger.spent().calls == 1


def test_ten_small_runs_add_up_to_a_refusal(tmp_path):
    """The failure a per-run budget cannot see."""
    path = tmp_path / "spend.json"
    for _ in range(10):
        ledger = Ledger(path, monthly_limit_usd=20.0)
        ledger.check(2.0)
        ledger.record(2.0)
    with pytest.raises(BudgetExceeded):
        Ledger(path, monthly_limit_usd=20.0).check(2.0)


def test_a_corrupt_ledger_refuses_rather_than_reading_as_zero(tmp_path):
    """The safe direction. A damaged file resetting to a clean slate would let
    the month start over every time something went wrong with it."""
    path = tmp_path / "spend.json"
    path.write_text("{not json")
    with pytest.raises(BudgetExceeded, match="unreadable"):
        Ledger(path)


def test_no_limit_means_no_refusal(tmp_path):
    ledger = Ledger(tmp_path / "spend.json", monthly_limit_usd=None)
    ledger.record(1000.0)
    ledger.check(1000.0)
    assert ledger.remaining() == float("inf")
    assert "no monthly limit" in ledger.summary()


def test_a_fresh_ledger_starts_empty(tmp_path):
    ledger = Ledger(tmp_path / "spend.json")
    assert ledger.spent().usd == 0.0
    assert ledger.history() == []


def test_the_file_is_readable_json(tmp_path):
    path = tmp_path / "spend.json"
    Ledger(path).record(1.25, calls=3, month="2026-08")
    assert json.loads(path.read_text())["months"]["2026-08"]["usd"] == pytest.approx(1.25)
