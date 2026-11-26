"""A person's own model in the database: the table, the column that says whose key paid, and the store (slice AI).

The table holds ciphertext only; the sealing itself is test_keybox.py.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from test_accounts_review import _fill

from skillforge.builder.keybox import KeyBox
from skillforge.db import Database, ModelCall
from skillforge.db.user_models import ModelStore, StoredModel
from skillforge.db.users import UserStore

TOKEN = "a-long-enough-access-token-1234567890"


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    database.migrate()
    yield database
    database.close()


def a_person(db: Database, n: int = 1) -> str:
    return UserStore(db).upsert_google(f"sub-{n}", f"p{n}@example.com", f"P{n}").id


# ---- the migration ------------------------------------------------------------------------------------


def test_the_migration_creates_user_models_and_says_whose_key_paid_for_each_call(db):
    with db.engine.connect() as c:
        inspector = inspect(c)
        assert "user_models" in inspector.get_table_names()
        columns = {col["name"]: col for col in inspector.get_columns("user_models")}
        assert set(columns) == {"user_id", "provider", "model", "key_ciphertext", "key_nonce", "updated_at"}
        assert all(not col["nullable"] for col in columns.values())
        assert inspector.get_pk_constraint("user_models")["constrained_columns"] == ["user_id"]  # one model per person
        source = {col["name"]: col for col in inspector.get_columns("model_calls")}["key_source"]
        assert not source["nullable"]


def test_a_database_from_before_this_slice_upgrades_and_every_old_call_is_the_servers(tmp_path):
    old = Database(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    old.migrate("0006")
    with old.session() as s:
        s.execute(text(
            "INSERT INTO model_calls (created_at, task, tier, provider, model, attempt, status, error_kind, latency_ms) "
            "VALUES ('t', 'act', 'actor', 'p', 'm', 1, 'ok', '', 5)"
        ))
    old.migrate()
    with old.session() as s:
        assert s.query(ModelCall).one().key_source == "server"  # until now the server's model was the only one
    old.close()


def test_going_back_down_keeps_every_job_and_usage_row(tmp_path):
    from alembic import command
    from alembic.config import Config

    from skillforge.db.database import MIGRATIONS

    db = Database(f"sqlite:///{(tmp_path / 'down.db').as_posix()}")
    db.migrate()
    with db.engine.begin() as c:
        _fill(c, "build_sessions", {"id": "s1"})
        _fill(c, "jobs", {"session_id": "s1"})
        _fill(c, "model_calls", {"session_id": "s1"})
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    with db.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0006")
    with db.engine.begin() as c:
        counts = {t: c.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in ("build_sessions", "jobs", "model_calls")}
        assert counts == {"build_sessions": 1, "jobs": 1, "model_calls": 1}, counts
        assert "key_source" not in {col["name"] for col in inspect(c).get_columns("model_calls")}
        assert "user_models" not in inspect(c).get_table_names()
    db.close()


# ---- the store ----------------------------------------------------------------------------------------


def test_a_model_round_trips_and_a_second_put_replaces_the_first(db):
    store, uid = ModelStore(db), a_person(db)
    saved = store.put(uid, "gemini", "gemini-x", b"cipher-1", b"n" * 12)
    assert isinstance(saved, StoredModel) and saved.updated_at
    got = store.get(uid)
    assert (got.provider, got.model, got.key_ciphertext, got.key_nonce) == ("gemini", "gemini-x", b"cipher-1", b"n" * 12)
    store.put(uid, "groq", "llama", b"cipher-2", b"m" * 12)
    got = store.get(uid)
    assert (got.provider, got.model, got.key_ciphertext) == ("groq", "llama", b"cipher-2")
    with db.engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM user_models")).scalar() == 1  # replaced, not added


def test_each_person_has_their_own_row(db):
    store = ModelStore(db)
    ada, bob = a_person(db, 1), a_person(db, 2)
    store.put(ada, "gemini", "g", b"a", b"n" * 12)
    assert store.get(bob) is None
    store.put(bob, "groq", "q", b"b", b"n" * 12)
    assert store.get(ada).provider == "gemini" and store.get(bob).provider == "groq"


def test_delete_says_whether_there_was_anything_to_delete(db):
    store, uid = ModelStore(db), a_person(db)
    store.put(uid, "gemini", "g", b"c", b"n" * 12)
    assert store.delete(uid) is True and store.get(uid) is None
    assert store.delete(uid) is False
    assert store.delete("not-an-id") is False


def test_an_id_we_did_not_make_finds_nothing(db):
    store = ModelStore(db)
    for odd in ("local", "../x", "A" * 32, "", None, 5):
        assert store.get(odd) is None, odd


def test_the_owner_and_odd_ids_cannot_have_a_stored_model(db):
    store = ModelStore(db)
    for odd in ("local", "../../etc", "x" * 31):
        with pytest.raises(ValueError):
            store.put(odd, "gemini", "g", b"c", b"n" * 12)


def test_a_model_cannot_be_stored_for_a_person_who_does_not_exist(db):
    with pytest.raises(IntegrityError):
        ModelStore(db).put("f" * 32, "gemini", "g", b"c", b"n" * 12)


def test_the_database_file_never_holds_the_key(tmp_path):
    path = tmp_path / "raw.db"
    db = Database(f"sqlite:///{path.as_posix()}")
    db.migrate()
    uid = a_person(db)
    key = "AIzaSyDistinctiveFakeKeyForTests_0123456789"
    ciphertext, nonce = KeyBox(TOKEN).seal(uid, key)
    ModelStore(db).put(uid, "gemini", "gemini-x", ciphertext, nonce)
    db.close()
    raw = b"".join(p.read_bytes() for p in tmp_path.glob("raw.db*"))
    assert key.encode() not in raw and key[:10].encode() not in raw
