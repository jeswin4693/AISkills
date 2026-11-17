"""Step 0 hello-world: one structured-output call to the configured LLM provider.

Reads LLM_PROVIDER, LLM_MODEL and the provider's key from the repo-root .env.
Supported providers:
  ollama     Ollama Cloud through its OpenAI-compatible endpoint (OLLAMA_API_KEY, OLLAMA_BASE_URL)
  anthropic  Anthropic Messages API (ANTHROPIC_API_KEY)

This is a throwaway smoke test. Step 1 replaces it with the provider interface
(`generate_structured(schema, prompt)`).

Run from the repo root:
    C:\\dev\\venvs\\aiskills\\Scripts\\python.exe backend\\scripts\\hello_structured.py
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import openai
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434/v1"  # free local Ollama is the default

PROMPT = (
    "Greet SkillForge AI in one short sentence, then list exactly "
    "three things a reusable AI skill needs."
)


class HelloResult(BaseModel):
    greeting: str = Field(description="One short sentence greeting SkillForge AI.")
    skill_ingredients: list[str] = Field(
        description="Exactly three things a reusable AI skill needs."
    )


@dataclass
class Reply:
    parsed: HelloResult
    served_by: str
    stop_reason: str | None
    tokens_in: int | None
    tokens_out: int | None
    request_id: str | None


class ProviderError(Exception):
    """A provider call failed in a way the user can act on."""


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ProviderError(f"{name} is empty. Set it in .env (never commit that file).")
    return value


def is_local_url(url: str) -> bool:
    return (urlparse(url).hostname or "") in {"localhost", "127.0.0.1", "::1"}


def call_ollama(model: str) -> Reply:
    base_url = os.getenv("OLLAMA_BASE_URL", "").strip() or DEFAULT_OLLAMA_BASE_URL
    local = is_local_url(base_url)
    api_key = os.getenv("OLLAMA_API_KEY", "").strip()
    if not api_key:
        if not local:
            raise ProviderError("OLLAMA_API_KEY is empty. Set it in .env (never commit that file).")
        api_key = "ollama"  # a local Ollama ignores the key, but the client needs a non-empty value
    client = openai.OpenAI(base_url=base_url, api_key=api_key)
    try:
        response = client.chat.completions.parse(
            model=model,
            messages=[{"role": "user", "content": PROMPT}],
            response_format=HelloResult,
        )
    except openai.AuthenticationError:
        raise ProviderError("The API key was rejected (401). Check OLLAMA_API_KEY in .env.")
    except openai.PermissionDeniedError as exc:
        raise ProviderError(f"The key lacks permission for this request: {exc.message}")
    except openai.NotFoundError:
        hint = f"Run: ollama pull {model}" if local else "Check LLM_MODEL in .env."
        raise ProviderError(f"Model '{model}' was not found. {hint}")
    except openai.BadRequestError as exc:
        raise ProviderError(f"Bad request (400): {exc.message}")
    except openai.RateLimitError:
        raise ProviderError("Rate limited (429). Wait a moment and run it again.")
    except openai.APIStatusError as exc:
        raise ProviderError(f"API error {exc.status_code}: {exc.message}")
    except openai.APIConnectionError:
        if local:
            raise ProviderError(
                f"Could not reach Ollama at {base_url}. Install it from https://ollama.com, "
                "start it, then run: ollama pull " + model
            )
        raise ProviderError("Could not reach the Ollama API. Check network and proxy settings.")
    except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
        raise ProviderError(f"The model did not finish cleanly: {exc}")
    except ValidationError as exc:
        raise ProviderError(f"The model's JSON did not match the schema:\n{exc}")

    choice = response.choices[0]
    if choice.message.refusal:
        raise ProviderError(f"The model refused the request: {choice.message.refusal}")
    if choice.message.parsed is None:
        raise ProviderError(f"No parsed output. finish_reason={choice.finish_reason}")
    usage = response.usage
    return Reply(
        parsed=choice.message.parsed,
        served_by=response.model,
        stop_reason=choice.finish_reason,
        tokens_in=usage.prompt_tokens if usage else None,
        tokens_out=usage.completion_tokens if usage else None,
        request_id=getattr(response, "_request_id", None),
    )


def call_anthropic(model: str) -> Reply:
    require_env("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic()  # key comes from the environment loaded above
    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=16000,
            # Refusal fallback: if a safety classifier declines, the API re-runs on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": PROMPT}],
            output_format=HelloResult,
        )
    except anthropic.AuthenticationError:
        raise ProviderError("The API key was rejected (401). Check ANTHROPIC_API_KEY in .env.")
    except anthropic.PermissionDeniedError as exc:
        raise ProviderError(f"The key lacks permission for this request: {exc.message}")
    except anthropic.NotFoundError:
        raise ProviderError(f"Model '{model}' was not found. Check LLM_MODEL in .env.")
    except anthropic.BadRequestError as exc:
        raise ProviderError(f"Bad request (400): {exc.message}")
    except anthropic.RateLimitError:
        raise ProviderError("Rate limited (429). Wait a moment and run it again.")
    except anthropic.APIStatusError as exc:
        raise ProviderError(f"API error {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError:
        raise ProviderError("Could not reach the Anthropic API. Check network and proxy settings.")

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ProviderError(f"The model refused the request (category: {category}).")
    if response.parsed_output is None:
        raise ProviderError(f"No parsed output. stop_reason={response.stop_reason}")
    return Reply(
        parsed=response.parsed_output,
        served_by=response.model,
        stop_reason=response.stop_reason,
        tokens_in=response.usage.input_tokens,
        tokens_out=response.usage.output_tokens,
        request_id=response._request_id,
    )


PROVIDERS = {"ollama": call_ollama, "anthropic": call_anthropic}


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    provider = os.getenv("LLM_PROVIDER", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()

    try:
        if provider not in PROVIDERS:
            raise ProviderError(
                f"LLM_PROVIDER is '{provider}'. Supported: {', '.join(sorted(PROVIDERS))}."
            )
        if not model:
            raise ProviderError("LLM_MODEL is empty. Set it in .env.")
        reply = PROVIDERS[provider](model)
    except ProviderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Structured output (validated against the Pydantic model):")
    print(reply.parsed.model_dump_json(indent=2))
    print()
    print(f"provider     : {provider}")
    print(f"served by    : {reply.served_by}")
    print(f"stop_reason  : {reply.stop_reason}")
    print(f"tokens in/out: {reply.tokens_in}/{reply.tokens_out}")
    print(f"request id   : {reply.request_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
