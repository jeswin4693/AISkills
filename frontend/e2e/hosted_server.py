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

from skillforge.ai import AIService
from skillforge.ai.doctor import Ping
from skillforge.api import create_app
from skillforge.api.builds import builder_options
from skillforge.api.hosted import Hosted, User, make_cookie
from skillforge.builder import Builder, JobRunner, ModelOptions
from skillforge.builder.keybox import KeyBox
from skillforge.db import Database
from skillforge.db.users import UserStore
from skillforge.library import Library
from skillforge.library.registry import Libraries
from skillforge.providers import MockProvider, ProviderError
from skillforge.settings import EnvSettings

DATA = Path(os.environ["SKILLFORGE_DATA_DIR"])
PORT = int(os.environ.get("E2E_API_PORT", "8100"))


def no_model():
    raise ProviderError("LLM_PROVIDER is ''. This throwaway server has no model on purpose.")


def fake_build(_env):
    """What a PERSON's own provider is built as here: a fake that answers the check's tiny question. A key typed in the browser never reaches a real provider,
    so the check needs no network and spends nothing."""
    return AIService.single(MockProvider([Ping(reply="ok")] * 20))


def make_builder(hosted, library, database, builds) -> Builder:
    """The builder of this throwaway server: made through `builder_options` like the real `serve` command (so it can never forget the limits), with only the
    person's model replaced by a fake that answers the check's tiny question."""
    options = builder_options(hosted)
    options["model_options"] = ModelOptions(keybox=KeyBox(hosted.token), shared_calls_per_day=hosted.shared_calls_per_day, build=fake_build)
    return Builder(database, library, builds, provider_factory=no_model, runner=JobRunner(),
                   sandbox_note=lambda: "unavailable. (the browser check does not use the sandbox)", **options)


def main() -> None:
    hosted = Hosted.from_env(os.environ)
    if hosted is None:
        raise SystemExit("This server is for the hosted-mode check: set SKILLFORGE_MODE=hosted and SKILLFORGE_ACCESS_TOKEN.")
    library = Library(DATA / "library")
    database = Database(f"sqlite:///{(DATA / 'phone.db').as_posix()}")
    database.migrate()
    builder = make_builder(hosted, library, database, DATA / "builds")
    # One made-up person, with a real session cookie made by the product's own make_cookie, so the browser check can be a signed-in PERSON without a Google ticket.
    # tester@example.com is on the allow-list the check sets, which is what a real sign-in would have needed.
    person = UserStore(database).upsert_google("phone-check-sub", "tester@example.com", "Phone Tester")
    (DATA / "person-cookie.txt").write_text(make_cookie(hosted, user=User(person.id, person.email)), encoding="utf-8")
    # Something of the person's own for the owner to erase: one skill in their library, put there through the product's own library code.
    Libraries(library).for_user(person.id).add(
        "phone-skill", {"SKILL.md": b"---\nname: phone-skill\ndescription: A skill the phone check erases.\n---\nSay hello.\n"}, source_kind="check", source_label="phone check",
    )
    settings = EnvSettings(DATA / "phone.env", {})  # a throwaway file in an empty environment: never the real .env
    uvicorn.run(create_app(library, builder=builder, env_settings=settings, hosted=hosted), host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
