"""One adapter for OpenAI and for any OpenAI-compatible endpoint (Gemini has one).

It makes exactly one attempt per call. The SDK's own hidden retries are off (`max_retries=0`): the AI service owns the
retry policy, so every real attempt is counted, timed and recorded in one place.
"""

from __future__ import annotations

import time

import openai
from pydantic import ValidationError

from ._errors import retry_after, short
from .base import CallOptions, Capabilities, Generation, ProviderError, T, Usage

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_TIMEOUT_S = 90.0  # the SDK's own default is 600 s, which would hold a job thread for ten minutes
CONNECT_TIMEOUT_S = 5.0


class OpenAICompatibleProvider:
    capabilities = Capabilities()

    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        key_env: str,
        base_url: str | None = None,
        client: openai.OpenAI | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.name = name
        self.model = model
        self._key_env = key_env
        self.secrets: tuple[str, ...] = (api_key,) if api_key else ()
        self._client = client or openai.OpenAI(
            api_key=api_key, base_url=base_url, max_retries=0, timeout=openai.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        )

    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T:
        return self.generate(schema, prompt, system=system).value

    def generate(
        self, schema: type[T], prompt: str, *, system: str | None = None, options: CallOptions = CallOptions()
    ) -> Generation[T]:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        extra: dict = {}
        if options.timeout_s is not None:
            extra["timeout"] = options.timeout_s
        if options.max_output_tokens is not None:
            extra["max_completion_tokens"] = options.max_output_tokens
        started = time.monotonic()
        try:
            response = self._client.chat.completions.parse(
                model=self.model, messages=messages, response_format=schema, **extra
            )
        except openai.AuthenticationError:
            raise ProviderError(f"The API key was rejected (401). Check {self._key_env} in .env.", kind="auth")
        except openai.PermissionDeniedError as exc:
            raise ProviderError(f"The key lacks permission for this request: {exc.message}", kind="auth")
        except openai.NotFoundError as exc:
            raise ProviderError(
                f"Model '{self.model}' is not available to this key: {exc.message}\n"
                "Check LLM_MODEL in .env. A model can appear in the provider's list and still be retired.",
                kind="model_missing",
            )
        except openai.BadRequestError as exc:
            if getattr(exc, "code", None) == "context_length_exceeded":  # OpenAI's own code for a prompt over the model's window
                raise ProviderError(f"The request is too big for this model (400): {exc.message}", kind="input_too_large")
            if getattr(exc, "code", None) == "json_validate_failed":
                # Groq: the model's own JSON did not match the schema (found by a real run: it wrote one part and stopped). That is invalid output, not a
                # bad request: it is asked again once with what it wrote, and another model may do better. `failed_generation` is what the model wrote.
                wrote = exc.body.get("failed_generation") if isinstance(exc.body, dict) else None
                raise ProviderError(
                    f"The model's JSON did not match the schema (400): {exc.message}", retryable=True, kind="invalid_output",
                    detail=short(f"The JSON did not match the schema. The model wrote: {wrote}" if wrote else "The JSON did not match the schema."),
                )
            raise ProviderError(f"Bad request (400): {exc.message}", kind="bad_request")
        except openai.RateLimitError as exc:
            quota = exc.code == "insufficient_quota" or "no credits" in exc.message.lower()
            raise ProviderError(
                f"Rate limited or out of quota (429): {exc.message}",
                kind="quota" if quota else "rate_limit",
                retry_after_s=None if quota else retry_after(exc.response.headers, exc.message),
            )
        except openai.APIStatusError as exc:
            if exc.status_code == 408:
                raise ProviderError(f"API error 408: {exc.message}", retryable=True, kind="timeout")
            if exc.status_code == 413:  # Request Entity Too Large (Groq says so for a prompt over its tokens-per-minute limit)
                raise ProviderError(f"The request is too big for this model (413): {exc.message}", kind="input_too_large")
            raise ProviderError(
                f"API error {exc.status_code}: {exc.message}",
                retryable=exc.status_code >= 500, kind="overloaded" if exc.status_code >= 500 else "other",
            )
        except openai.APITimeoutError:
            raise ProviderError(f"The {self.name} API did not answer in time.", retryable=True, kind="timeout")
        except openai.APIConnectionError:
            raise ProviderError(
                f"Could not reach the {self.name} API. Check network and proxy settings.", retryable=True, kind="connection"
            )
        except openai.LengthFinishReasonError as exc:
            raise ProviderError(f"The model's answer was cut off (too long): {exc}", kind="too_long")
        except openai.ContentFilterFinishReasonError as exc:
            raise ProviderError(f"The model did not finish cleanly: {exc}", retryable=True)
        except ValidationError as exc:
            raise ProviderError(
                f"The model's JSON did not match the schema:\n{exc}", retryable=True, kind="invalid_output", detail=short(exc)
            )

        choice = response.choices[0]
        if choice.message.refusal:
            raise ProviderError(f"The model refused the request: {choice.message.refusal}", kind="refused")
        if choice.message.parsed is None:
            raise ProviderError(
                f"No parsed output. finish_reason={choice.finish_reason}", retryable=True, kind="invalid_output",
                detail=f"no parsed output (finish_reason={choice.finish_reason})",
            )
        usage = response.usage
        return Generation(
            choice.message.parsed,
            Usage(usage.prompt_tokens, usage.completion_tokens) if usage else Usage(),
            time.monotonic() - started,
            getattr(response, "model", "") or "",
        )
