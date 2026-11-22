"""Typed errors (docs/AGENTS.md §1). Each maps to a verdict code or a fail-closed result."""


class DDError(Exception):
    """Base error."""


class SecretMissing(DDError):
    """A secret is absent or still __ASK_USER__ → run /setup-secrets."""


class SourceUnavailable(DDError):
    """A source failed after retries/fallbacks or its breaker is open → ⚪ N2."""

    def __init__(self, source: str, reason: str = ""):
        super().__init__(f"{source}: {reason}")
        self.source, self.reason = source, reason


class BudgetExhausted(DDError):
    """Credit/token/deadline budget reached → ⚪ N5."""


class EntityUnresolved(DDError):
    """Entity score below threshold → ⚪ N4 / HOLD."""


class ParseFailed(DDError):
    """Structured output did not validate twice → 'could not parse' (never a guess)."""


class ContractError(DDError):
    """A 4xx (non-429) from an API: our request is wrong. Never retried."""


class CassetteMiss(DDError):
    """Replay mode found no recorded response for a request."""
