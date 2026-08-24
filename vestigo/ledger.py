"""What this project has spent, across runs and across months.

`Budget` guards one run. That is the wrong unit for a person with a monthly
cap, because nothing stops a two dollar eval being run ten times in a week. The
ledger persists, groups by calendar month, and refuses once the month is spent.

Two ceilings, and they are not redundant. This one is enforced by code that
could have a bug in it. The one in the provider's console is enforced by the
provider and is the ceiling that actually holds. Set both.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .llm import Budget, BudgetExceeded

LEDGER_PATH = pathlib.Path(".cache/spend.json")
MONTHLY_LIMIT_USD = 20.0


def _month(when: datetime | None = None) -> str:
    return (when or datetime.now(timezone.utc)).strftime("%Y-%m")


@dataclass(frozen=True, slots=True)
class MonthSpend:
    month: str
    usd: float
    calls: int

    def __str__(self) -> str:
        return f"{self.month}: ${self.usd:.4f} over {self.calls} calls"


class Ledger:
    """A running total on disk, in whole months.

    Kept in `.cache/`, which is gitignored, because how much someone has spent
    is not a fact about the code.
    """

    def __init__(self, path: pathlib.Path | str = LEDGER_PATH,
                 monthly_limit_usd: float | None = MONTHLY_LIMIT_USD):
        self.path = pathlib.Path(path)
        self.monthly_limit_usd = monthly_limit_usd
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"months": {}}
        try:
            return json.loads(self.path.read_text())
        except (json.JSONDecodeError, ValueError):
            # A corrupt ledger must not read as zero spent. Refusing is the
            # safe direction, since the alternative is a silent reset to a
            # clean slate every time the file gets damaged.
            raise BudgetExceeded(
                f"{self.path} is unreadable, so this month's spend is unknown. "
                "Check the provider's console, then delete the file to start over."
            ) from None

    def spent(self, month: str | None = None) -> MonthSpend:
        month = month or _month()
        row = self._data["months"].get(month, {"usd": 0.0, "calls": 0})
        return MonthSpend(month, row["usd"], row["calls"])

    def remaining(self) -> float:
        if self.monthly_limit_usd is None:
            return float("inf")
        return max(0.0, self.monthly_limit_usd - self.spent().usd)

    def check(self, planned_usd: float = 0.0) -> None:
        if self.monthly_limit_usd is None:
            return
        spent = self.spent()
        if spent.usd + planned_usd > self.monthly_limit_usd:
            raise BudgetExceeded(
                f"{spent.month} would reach "
                f"${spent.usd + planned_usd:.2f} against a "
                f"${self.monthly_limit_usd:.2f} monthly limit. "
                f"${self.remaining():.2f} left this month."
            )

    def record(self, usd: float, calls: int = 1, month: str | None = None) -> MonthSpend:
        month = month or _month()
        row = self._data["months"].setdefault(month, {"usd": 0.0, "calls": 0})
        row["usd"] = round(row["usd"] + usd, 6)
        row["calls"] += calls
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, indent=2, sort_keys=True) + "\n")
        return self.spent(month)

    def absorb(self, budget: Budget) -> MonthSpend:
        """Fold a finished run's budget into the running total."""
        return self.record(budget.spent_usd, len(budget.entries))

    def history(self) -> list[MonthSpend]:
        return [MonthSpend(m, r["usd"], r["calls"])
                for m, r in sorted(self._data["months"].items())]

    def summary(self) -> str:
        spent = self.spent()
        if self.monthly_limit_usd is None:
            return f"{spent}, no monthly limit set"
        return (f"{spent}, ${self.remaining():.2f} of "
                f"${self.monthly_limit_usd:.2f} left this month")
