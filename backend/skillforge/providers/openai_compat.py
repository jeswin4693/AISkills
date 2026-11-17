"""One adapter for OpenAI and for any OpenAI-compatible endpoint (Gemini has one)."""

from __future__ import annotations

import openai
from pydantic import ValidationError

from .base import ProviderError, T

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        key_env: str,
        base_url: str | None = None,
        client: openai.OpenAI | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._key_env = key_env
        self._client = client or openai.OpenAI(api_key=api_key, base_url=base_url)

    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        try:
            response = self._client.chat.completions.parse(
                model=self.model, messages=messages, response_format=schema
            )
        except openai.AuthenticationError:
            raise ProviderError(f"The API key was rejected (401). Check {self._key_env} in .env.")
        except openai.PermissionDeniedError as exc:
            raise ProviderError(f"The key lacks permission for this request: {exc.message}")
        except openai.NotFoundError as exc:
            raise ProviderError(
                f"Model '{self.model}' is not available to this key: {exc.message}\n"
                "Check LLM_MODEL in .env. A model can appear in the provider's list and still be retired."
            )
        except openai.BadRequestError as exc:
            raise ProviderError(f"Bad request (400): {exc.message}")
        except openai.RateLimitError as exc:
            raise ProviderError(f"Rate limited or out of quota (429): {exc.message}")
        except openai.APIStatusError as exc:
            raise ProviderError(
                f"API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500
            )
        except openai.APIConnectionError:
            raise ProviderError(f"Could not reach the {self.name} API. Check network and proxy settings.")
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
            raise ProviderError(f"The model did not finish cleanly: {exc}", retryable=True)
        except ValidationError as exc:
            raise ProviderError(f"The model's JSON did not match the schema:\n{exc}", retryable=True)

        choice = response.choices[0]
        if choice.message.refusal:
            raise ProviderError(f"The model refused the request: {choice.message.refusal}")
        if choice.message.parsed is None:
            raise ProviderError(f"No parsed output. finish_reason={choice.finish_reason}", retryable=True)
        return choice.message.parsed
