"""One retry rule for every feature: retry only failures a second try can fix."""

from __future__ import annotations

from .base import LLMProvider, ProviderError, T


def generate_with_retry(
    provider: LLMProvider, schema: type[T], prompt: str, system: str | None, attempts: int = 2
) -> tuple[T, int]:
    """Returns (answer, model calls used). Non-retryable errors (bad key, no quota) are raised at once."""
    last: ProviderError | None = None
    for used in range(1, attempts + 1):
        try:
            return provider.generate_structured(schema, prompt, system=system), used
        except ProviderError as exc:
            if not exc.retryable:
                raise
            last = exc
    raise ProviderError(f"No usable answer after {attempts} attempt(s): {last}") from last
