"""The provider interface. Nothing outside this package knows which vendor is behind it."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """A provider call failed in a way the user can act on. `retryable` means asking again may succeed."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    name: str
    model: str

    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T:
        """Return an instance of `schema` validated by Pydantic, or raise ProviderError."""
        ...
