"""Token budget management for ContextPack generation."""

from __future__ import annotations

from photon_action_memory.api.schema_v2 import TokenBudget


class TokenBudgetTracker:
    """Track token usage against a fixed budget."""

    def __init__(self, max_tokens: int) -> None:
        self._max = max(0, max_tokens)
        self._used: int = 0
        self._raw: int = 0

    @property
    def max_tokens(self) -> int:
        return self._max

    def fits(self, tokens: int) -> bool:
        """Return True if consuming *tokens* stays within budget."""
        return self._used + tokens <= self._max

    def consume(self, tokens: int) -> None:
        self._used += tokens

    def add_raw(self, tokens: int) -> None:
        """Record the raw-equivalent cost for tokens_saved_vs_raw accounting."""
        self._raw += tokens

    def to_token_budget(self) -> TokenBudget:
        return TokenBudget(
            max_tokens=self._max,
            estimated_tokens=self._used,
            tokens_saved_vs_raw=max(0, self._raw - self._used),
        )


__all__ = ["TokenBudgetTracker"]
