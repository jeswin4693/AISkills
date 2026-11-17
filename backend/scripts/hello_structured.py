"""Step 0 hello-world: one structured-output call to the configured LLM provider.

Reads LLM_PROVIDER, LLM_MODEL and ANTHROPIC_API_KEY from the repo-root .env.
This is a throwaway smoke test. Step 1 replaces it with the provider interface
(`generate_structured(schema, prompt)`).

Run from the repo root:
    C:\\dev\\venvs\\aiskills\\Scripts\\python.exe backend\\scripts\\hello_structured.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]


class HelloResult(BaseModel):
    greeting: str = Field(description="One short sentence greeting SkillForge AI.")
    skill_ingredients: list[str] = Field(
        description="Exactly three things a reusable AI skill needs."
    )


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")

    provider = os.getenv("LLM_PROVIDER", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if provider != "anthropic":
        return fail(f"LLM_PROVIDER is '{provider}'. This script only supports 'anthropic'.")
    if not model:
        return fail("LLM_MODEL is empty. Set it in .env (for example claude-sonnet-5-5).")
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        return fail("ANTHROPIC_API_KEY is empty. Add it to .env (never commit that file).")

    client = anthropic.Anthropic()  # key comes from the environment loaded above

    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=16000,
            # Refusal fallback: if a safety classifier declines, the API re-runs on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Greet SkillForge AI in one short sentence, then list exactly "
                        "three things a reusable AI skill needs."
                    ),
                }
            ],
            output_format=HelloResult,
        )
    except anthropic.AuthenticationError:
        return fail("The API key was rejected (401). Check ANTHROPIC_API_KEY in .env.")
    except anthropic.PermissionDeniedError as exc:
        return fail(f"The API key lacks permission for this request: {exc.message}")
    except anthropic.NotFoundError:
        return fail(f"Model '{model}' was not found. Check LLM_MODEL in .env.")
    except anthropic.BadRequestError as exc:
        return fail(f"Bad request (400): {exc.message}")
    except anthropic.RateLimitError:
        return fail("Rate limited (429). Wait a moment and run it again.")
    except anthropic.APIStatusError as exc:
        return fail(f"API error {exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError:
        return fail("Could not reach the Anthropic API. Check network and proxy settings.")

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        return fail(f"The model refused the request (category: {category}).")
    if response.parsed_output is None:
        return fail(f"No parsed output. stop_reason={response.stop_reason}")

    result = response.parsed_output
    print("Structured output (validated against the Pydantic model):")
    print(result.model_dump_json(indent=2))
    print()
    print(f"served by    : {response.model}")
    print(f"stop_reason  : {response.stop_reason}")
    print(f"tokens in/out: {response.usage.input_tokens}/{response.usage.output_tokens}")
    print(f"request id   : {response._request_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
