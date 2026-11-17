"""A provider for tests: returns what it was told to, and records every call. No network, no key."""

from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel

from .base import ProviderError, T


class MockProvider:
    name = "mock"
    model = "mock-1"

    def __init__(self, responses: list[Any] | Callable[[type[BaseModel], str, str | None], Any] | None = None) -> None:
        """`responses`: a list consumed one per call, or a function(schema, prompt, system).

        Each item may be an instance of the schema, a dict to validate against it, or an Exception to raise.
        """
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T:
        self.calls.append({"schema": schema, "prompt": prompt, "system": system})
        if callable(self._responses):
            item = self._responses(schema, prompt, system)
        elif self._responses:
            item = self._responses.pop(0)
        else:
            raise ProviderError("MockProvider has no response left for this call.")
        if isinstance(item, Exception):
            raise item
        if isinstance(item, schema):
            return item
        return schema.model_validate(item)
