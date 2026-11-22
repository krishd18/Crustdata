"""Injectable 'now' in IST; frozen in tests (plan §3.1C). Resolves relative windows."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
FROZEN_DEFAULT = "2026-11-22T16:30:00+05:30"


class Clock:
    def __init__(self, frozen: str | None = None):
        self.frozen = frozen if frozen is not None else os.environ.get("DD_FROZEN_NOW") or None

    def now(self) -> datetime:
        if self.frozen:
            return datetime.fromisoformat(self.frozen).astimezone(IST)
        return datetime.now(IST)

    def today(self) -> date:
        return self.now().date()

    def quarter_window(self) -> tuple[date, date, str]:
        """Calendar quarter containing now (IST) + Indian FY label (STANDARDS §5.2 'this quarter')."""
        d = self.today()
        q = (d.month - 1) // 3 + 1
        start = date(d.year, 3 * (q - 1) + 1, 1)
        fy_q = {1: 4, 2: 1, 3: 2, 4: 3}[q]
        fy = f"FY{d.year if q > 1 else d.year - 1}-{str((d.year + 1 if q > 1 else d.year))[2:]}"
        return start, d, f"Q{q} {d.year} (calendar) = Q{fy_q} {fy}"

    def last_n_months(self, n: int) -> tuple[date, date]:
        d = self.today()
        days = {1: 30, 3: 91, 6: 182, 12: 365}.get(n, 30 * n)
        return d - timedelta(days=days), d

    def last_n_days(self, n: int) -> tuple[date, date]:
        d = self.today()
        return d - timedelta(days=n), d
