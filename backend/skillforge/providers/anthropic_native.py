"""The native Anthropic adapter (Claude), using the API's structured output: `output_config.format` carries a JSON schema
built by the SDK's `transform_schema`, and the reply text is validated here (so a refusal is seen before any parsing).

Same contract as the OpenAI-compatible adapter: one attempt per call, no hidden SDK retries, usage reported, every failure
classified. Structured output does not use forced tool calls (some Claude models reject them), and no beta flags are used.

Status: checked against a mocked HTTP server only. There is no Anthropic key on the development machine, so it has never
made a real call.
"""

from __future__ import annotations

import time

import anthropic
from pydantic import ValidationError

from ._errors import retry_after, short
from .base import CallOptions, Capabilities, Generation, ProviderError, T, Usage

DEFAULT_TIMEOUT_S = 90.0
CONNECT_TIMEOUT_S = 5.0
DEFAULT_MAX_TOKENS = 16000  # the API requires a limit; this is the cap when the caller sets none


class AnthropicProvider:
    capabilities = Capabilities()

    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        key_env: str,
        client: anthropic.Anthropic | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.name = name
        self.model = model
        self._key_env = key_env
        self.secrets: tuple[str, ...] = (api_key,) if api_key else ()
        self._client = client or anthropic.Anthropic(
            api_key=api_key, max_retries=0, timeout=anthropic.Timeout(timeout_s, connect=CONNECT_TIMEOUT_S)
        )

    def generate_structured(self, schema: type[T], prompt: str, *, system: str | None = None) -> T:
        return self.generate(schema, prompt, system=system).value

    def generate(
        self, schema: type[T], prompt: str, *, system: str | None = None, options: CallOptions = CallOptions()
    ) -> Generation[T]:
        extra: dict = {}
        if system:
            extra["system"] = system
        if options.timeout_s is not None:
            extra["timeout"] = options.timeout_s
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self.model, max_tokens=options.max_output_tokens or DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": anthropic.transform_schema(schema)}}, **extra,
            )
        except anthropic.AuthenticationError:
            raise ProviderError(f"The API key was rejected (401). Check {self._key_env} in .env.", kind="auth")
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError(f"The key lacks permission for this request: {exc.message}", kind="auth")
        except anthropic.NotFoundError as exc:
            raise ProviderError(
                f"Model '{self.model}' was not found for this key: {exc.message}\nCheck LLM_MODEL in .env.", kind="model_missing"
            )
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"Bad request (400): {exc.message}", kind="bad_request")
        except anthropic.RateLimitError as exc:
            raise ProviderError(
                f"Rate limited (429): {exc.message}", kind="rate_limit", retry_after_s=retry_after(exc.response.headers, exc.message)
            )
        except anthropic.APIStatusError as exc:
            if exc.status_code == 408:
                raise ProviderError(f"API error 408: {exc.message}", retryable=True, kind="timeout")
            if exc.status_code == 413:  # Request Entity Too Large
                raise ProviderError(f"The request is too big for this model (413): {exc.message}", kind="input_too_large")
            raise ProviderError(
                f"API error {exc.status_code}: {exc.message}",
                retryable=exc.status_code >= 500, kind="overloaded" if exc.status_code >= 500 else "other",
            )
        except anthropic.APITimeoutError:
            raise ProviderError(f"The {self.name} API did not answer in time.", retryable=True, kind="timeout")
        except anthropic.APIConnectionError:
            raise ProviderError(
                f"Could not reach the {self.name} API. Check network and proxy settings.", retryable=True, kind="connection"
            )

        # The stop reason is read first: a refusal has no content, which would otherwise look like invalid output.
        if response.stop_reason == "refusal":
            raise ProviderError("The model refused the request.", kind="refused")
        if response.stop_reason == "max_tokens":
            raise ProviderError("The model's answer was cut off (too long).", kind="too_long")
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        try:
            value = schema.model_validate_json(text)
        except ValidationError as exc:
            raise ProviderError(
                f"The model's JSON did not match the schema:\n{exc}", retryable=True, kind="invalid_output", detail=short(exc)
            )
        return Generation(
            value,
            Usage(response.usage.input_tokens, response.usage.output_tokens),
            time.monotonic() - started,
            getattr(response, "model", "") or "",
        )
