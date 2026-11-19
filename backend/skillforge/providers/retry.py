"""One retry rule for every feature, kept under its old name.

`generate_with_retry` is what every builder calls. It now hands the work to the AI service (`skillforge.ai`), which holds the
one retry policy: it retries only the failures a second try can fix, and decides by the error's kind. Given a bare provider
(a test double) it behaves as it always did: no pauses, and the old messages.
"""

from __future__ import annotations

from .base import LLMProvider, T


def generate_with_retry(
    provider: LLMProvider, schema: type[T], prompt: str, system: str | None, attempts: int | None = None, *, task=None
) -> tuple[T, int]:
    """Returns (answer, model calls used). Non-retryable errors (bad key, no quota) are raised at once.

    `attempts` is a hard cap on the calls made in total; without it each kind of failure has its own limit. `task` says what
    kind of work this is (`skillforge.ai.Task`), which decides the model when tiers are configured."""
    from ..ai.service import AIService  # imported here: the ai package builds on providers, so it cannot be imported at the top
    from ..ai.tasks import Task

    service = provider if isinstance(provider, AIService) else AIService.single(provider)
    return service.generate(task or Task.DESIGN, schema, prompt, system, attempts=attempts)
