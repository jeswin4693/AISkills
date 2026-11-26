"""A throwaway HOSTED server for the phone check (hosted-phone.mjs).

Hosted mode, its token and the made-up Google Client ID come from the environment, as on a real host. What it does NOT take from the machine: the real `.env` and any model key.
It has an empty settings file of its own and a model that is "not set up", like a missing .env, so a browser test can never read a real key or spend one
(the same rule as mock_server.py for the main suite).

Run with PYTHONPATH set to the backend folder, SKILLFORGE_DATA_DIR set to a throwaway folder, SKILLFORGE_MODE=hosted and SKILLFORGE_ACCESS_TOKEN set.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from skillforge.api import create_app
from skillforge.api.hosted import Hosted
from skillforge.builder import Builder, JobRunner
from skillforge.db import Database
from skillforge.library import Library
from skillforge.providers import ProviderError
from skillforge.settings import EnvSettings

DATA = Path(os.environ["SKILLFORGE_DATA_DIR"])
PORT = int(os.environ.get("E2E_API_PORT", "8100"))


def no_model():
    raise ProviderError("LLM_PROVIDER is ''. This throwaway server has no model on purpose.")


def main() -> None:
    hosted = Hosted.from_env(os.environ)
    if hosted is None:
        raise SystemExit("This server is for the hosted-mode check: set SKILLFORGE_MODE=hosted and SKILLFORGE_ACCESS_TOKEN.")
    library = Library(DATA / "library")
    database = Database(f"sqlite:///{(DATA / 'phone.db').as_posix()}")
    database.migrate()
    builder = Builder(database, library, DATA / "builds", provider_factory=no_model, runner=JobRunner(),
                      sandbox_note=lambda: "unavailable. (the browser check does not use the sandbox)")
    settings = EnvSettings(DATA / "phone.env", {})  # a throwaway file in an empty environment: never the real .env
    uvicorn.run(create_app(library, builder=builder, env_settings=settings, hosted=hosted), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
