"""Per-run budget: credits, LLM tokens, deadline (plan §3.1C). At stop_noncritical_at (80%) only critical
work continues; at 100% everything stops → ⚪ N5. Limits can be cut live (PATCH /runs/{id}/limits)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .errors import BudgetExhausted


@dataclass
class Budget:
    max_credits: float = 300
    max_llm_tokens: int = 400_000
    deadline_s: float = 900
    stop_noncritical_at: float = 0.8
    used_credits: float = 0.0
    used_tokens: int = 0
    started: float = field(default_factory=time.time)

    @classmethod
    def for_family(cls, limits_cfg: dict, family: str, overrides: dict | None = None) -> "Budget":
        d = dict(limits_cfg.get("defaults", {}))
        d.update(limits_cfg.get("by_family", {}).get(family, {}))
        d.update(overrides or {})
        return cls(**{k: v for k, v in d.items() if k in ("max_credits", "max_llm_tokens", "deadline_s", "stop_noncritical_at")})

    def fraction(self) -> float:
        el = (time.time() - self.started) / self.deadline_s if self.deadline_s else 0
        return max(self.used_credits / self.max_credits if self.max_credits else 0,
                   self.used_tokens / self.max_llm_tokens if self.max_llm_tokens else 0, el)

    def check(self, est_credits: float = 0.0, critical: bool = True) -> None:
        """Raise BudgetExhausted if this call would exceed the budget (non-critical stop at 80%)."""
        if self.max_credits and self.used_credits + est_credits > self.max_credits:
            raise BudgetExhausted(f"credits {self.used_credits:.2f}+{est_credits:.2f} > {self.max_credits}")
        if self.deadline_s and time.time() - self.started > self.deadline_s:
            raise BudgetExhausted("deadline reached")
        if not critical and self.fraction() >= self.stop_noncritical_at:
            raise BudgetExhausted(f"non-critical work stopped at {self.stop_noncritical_at:.0%} of budget")

    def charge(self, credits: float = 0.0, tokens: int = 0) -> None:
        self.used_credits += credits or 0.0
        self.used_tokens += tokens or 0

    def cut(self, max_credits: float | None = None, deadline_s: float | None = None) -> None:
        if max_credits is not None:
            self.max_credits = max_credits
        if deadline_s is not None:
            self.deadline_s = deadline_s

    def snapshot(self) -> dict:
        return {"max_credits": self.max_credits, "used_credits": round(self.used_credits, 3), "max_llm_tokens": self.max_llm_tokens,
                "used_tokens": self.used_tokens, "deadline_s": self.deadline_s, "fraction": round(self.fraction(), 3)}
