"""People in the database: a users table, and an owner on everything a person makes.

Every row that exists before this change belongs to the one person who used the app then (the owner, id `local`), so an upgrade loses nothing and shows nothing to anyone else.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from skillforge.db import BuildSession, Database, EvalRun, ModelCall, SuggestRun
from skillforge.db.users import LOCAL_USER_ID, UserRecord, UserStore


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'u.db').as_posix()}")
    database.migrate()
    yield database
    database.close()


# ---- the migration ------------------------------------------------------------------------------------


def test_the_migration_adds_the_users_table_and_an_owner_column_to_what_a_person_makes(db):
    with db.engine.connect() as c:
        tables = inspect(c).get_table_names()
        assert "users" in tables
        for table in ("build_sessions", "suggest_runs", "eval_runs", "model_calls"):
            columns = {col["name"]: col for col in inspect(c).get_columns(table)}
            assert "user_id" in columns and not columns["user_id"]["nullable"], table
            assert any("user_id" in ix["column_names"] for ix in inspect(c).get_indexes(table)), f"{table}.user_id is not indexed"


def test_a_database_from_before_accounts_upgrades_and_every_old_row_belongs_to_the_owner(tmp_path):
    old = Database(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    old.migrate("0005")  # the schema as it is today
    with old.session() as s:
        s.execute(text(
            "INSERT INTO build_sessions (id, created_at, updated_at, status, description, words, round, with_scripts, questions, error, retryable, model_calls, notes, "
            f"saved_name, saved_version, kind) VALUES ('{'b' * 32}', 't', 't', 'done', 'd', 'd', 1, 0, '[]', '', 0, 0, '[]', '', '', 'skill')"
        ))
        s.execute(text(
            "INSERT INTO suggest_runs (id, created_at, updated_at, status, repo, repo_name, with_ideas, error, retryable) "
            f"VALUES ('{'c' * 32}', 't', 't', 'done', '/r', 'r', 1, '', 0)"
        ))
        s.execute(text(
            "INSERT INTO eval_runs (id, created_at, updated_at, status, kind, name, version, content_hash, runs, baseline, cases_total, cases_done, error, retryable) "
            f"VALUES ('{'d' * 32}', 't', 't', 'done', 'skill', 'x', 1, 'h', 1, 1, 3, 3, '', 0)"
        ))
        s.execute(text(
            "INSERT INTO model_calls (created_at, task, tier, provider, model, attempt, status, error_kind, latency_ms) VALUES ('t', 'act', 'actor', 'p', 'm', 1, 'ok', '', 5)"
        ))
    old.migrate()
    with old.session() as s:
        assert s.get(BuildSession, "b" * 32).user_id == LOCAL_USER_ID
        assert s.get(SuggestRun, "c" * 32).user_id == LOCAL_USER_ID
        assert s.get(EvalRun, "d" * 32).user_id == LOCAL_USER_ID
        assert s.query(ModelCall).one().user_id == LOCAL_USER_ID
    old.close()


def test_a_new_row_made_without_saying_whose_it_is_belongs_to_the_owner(db):
    with db.session() as s:
        s.add(BuildSession(id="a" * 32, created_at="t", updated_at="t", status="done", description="d", words="d", round=1, with_scripts=False, questions=[],
                           error="", retryable=False, model_calls=0, notes=[], saved_name="", saved_version=""))
    with db.session() as s:
        assert s.get(BuildSession, "a" * 32).user_id == LOCAL_USER_ID


# ---- the users ----------------------------------------------------------------------------------------


def test_the_owner_has_a_fixed_id_that_is_not_a_random_hex_id():
    assert LOCAL_USER_ID == "local" and not re.fullmatch(r"[0-9a-f]{32}", LOCAL_USER_ID)


def test_a_new_google_account_becomes_a_user_with_a_random_id(db):
    who = UserStore(db).upsert_google("sub-1", "ada@example.com", "Ada", "https://lh3.googleusercontent.com/a")
    assert isinstance(who, UserRecord) and re.fullmatch(r"[0-9a-f]{32}", who.id)
    assert (who.email, who.name, who.picture) == ("ada@example.com", "Ada", "https://lh3.googleusercontent.com/a")


def test_the_same_google_account_is_the_same_user_each_time_even_if_its_email_or_name_changed(db):
    store = UserStore(db)
    first = store.upsert_google("sub-1", "ada@example.com", "Ada", "")
    again = store.upsert_google("sub-1", "ada@new-name.example.com", "Ada L.", "https://x.example/p.png")
    assert again.id == first.id and again.email == "ada@new-name.example.com" and again.name == "Ada L."
    assert store.get(first.id) == again


def test_two_different_google_accounts_are_two_users(db):
    store = UserStore(db)
    assert store.upsert_google("sub-1", "a@example.com", "A", "").id != store.upsert_google("sub-2", "b@example.com", "B", "").id


def test_an_unknown_or_odd_id_finds_nobody(db):
    store = UserStore(db)
    for odd in ("", "local", "x" * 32, "0" * 32, "../../etc", None, 5):
        assert store.get(odd) is None


def test_a_google_subject_can_only_be_stored_once_by_the_database_itself(db):
    store = UserStore(db)
    store.upsert_google("sub-1", "a@example.com", "A", "")
    with db.session() as s, pytest.raises(IntegrityError):
        s.execute(text("INSERT INTO users (id, google_sub, email, name, picture, created_at, last_login_at) VALUES ('" + "e" * 32 + "', 'sub-1', 'x@example.com', 'X', '', 't', 't')"))


def test_the_last_sign_in_time_moves_forward_and_the_first_one_stays(db):
    store = UserStore(db)
    first = store.upsert_google("sub-1", "a@example.com", "A", "")
    with db.session() as s:
        created = s.execute(text("SELECT created_at, last_login_at FROM users WHERE id = :i"), {"i": first.id}).one()
    store.upsert_google("sub-1", "a@example.com", "A", "")
    with db.session() as s:
        created_after, login_after = s.execute(text("SELECT created_at, last_login_at FROM users WHERE id = :i"), {"i": first.id}).one()
    assert created_after == created[0] and login_after >= created[1]
