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
import math
import os
import pathlib
import tempfile
from contextlib import contextmanager
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
        if monthly_limit_usd is not None and (
                not math.isfinite(monthly_limit_usd) or monthly_limit_usd < 0):
            raise ValueError("monthly limit must be finite and non-negative")
        self.path = pathlib.Path(path)
        self.monthly_limit_usd = monthly_limit_usd
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"months": {}}
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get("months"), dict):
                raise ValueError("missing month records")
            for month, row in data["months"].items():
                if not isinstance(month, str) or not isinstance(row, dict):
                    raise ValueError("invalid month record")
                usd, calls = row.get("usd"), row.get("calls")
                if (isinstance(usd, bool) or not isinstance(usd, (int, float))
                        or not math.isfinite(usd) or usd < 0
                        or isinstance(calls, bool) or not isinstance(calls, int) or calls < 0):
                    raise ValueError("invalid spend record")
            return data
        except (json.JSONDecodeError, ValueError, TypeError):
            # A corrupt ledger must not read as zero spent. Refusing is the
            # safe direction, since the alternative is a silent reset to a
            # clean slate every time the file gets damaged.
            raise BudgetExceeded(
                f"{self.path} is unreadable, so this month's spend is unknown. "
                "Check the provider's console, then delete the file to start over."
            ) from None

    def spent(self, month: str | None = None) -> MonthSpend:
        self._data = self._load()
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
        if isinstance(usd, bool) or not math.isfinite(usd) or usd < 0 or isinstance(calls, bool) \
                or not isinstance(calls, int) or calls < 0:
            raise ValueError("spend and calls must be non-negative and finite")
        month = month or _month()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked():
            self._data = self._load()
            row = self._data["months"].setdefault(month, {"usd": 0.0, "calls": 0})
            row["usd"] = round(row["usd"] + usd, 6)
            row["calls"] += calls
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=self.path.name,
                                        suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(self._data, handle, indent=2, sort_keys=True)
                    handle.write("\n")
                os.replace(name, self.path)
            finally:
                pathlib.Path(name).unlink(missing_ok=True)
        return self.spent(month)

    @contextmanager
    def _locked(self, suffix: str = ".lock"):
        """Serialize the full read/modify/write transaction across processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + suffix)
        with lock_path.open("a+") as handle:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                if not handle.read(1):
                    handle.write("\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    @contextmanager
    def session(self):
        """Keep two live evals from both claiming the same monthly allowance."""
        with self._locked(".run.lock"):
            yield

    def absorb(self, budget: Budget) -> MonthSpend:
        """Fold a finished run's budget into the running total."""
        return self.record(budget.spent_usd, len(budget.entries))

    def history(self) -> list[MonthSpend]:
        self._data = self._load()
        return [MonthSpend(m, r["usd"], r["calls"])
                for m, r in sorted(self._data["months"].items())]

    def summary(self) -> str:
        spent = self.spent()
        if self.monthly_limit_usd is None:
            return f"{spent}, no monthly limit set"
        return (f"{spent}, ${self.remaining():.2f} of "
                f"${self.monthly_limit_usd:.2f} left this month")
