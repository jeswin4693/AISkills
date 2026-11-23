"""Slice X: the Settings page's backend. What can be changed (a fixed list), what a value may look like, how `.env` is edited and
written, and the one fact that matters most: a key is never sent back, in any answer or any error."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from skillforge.providers.factory import key_variables, supported_names
from skillforge.settings import EnvSettings, GROUPS, SettingsError, catalogue, check_value, edit_env_text, setting_named

GEMINI_KEY = "AIzaSyFILE-KEY_0123456789abcdef"
OPENAI_KEY = "sk-proj-ENVKEY_0123456789ABCDEF"


@pytest.fixture(autouse=True)
def private_environment(monkeypatch):
    """Each test gets its own copy of the process environment, so a setting applied here never leaks into another test."""
    monkeypatch.setattr(os, "environ", dict(os.environ))


def settings_for(tmp_path: Path, text: str | bytes | None = None, environ: dict | None = None) -> EnvSettings:
    path = tmp_path / ".env"
    if text is not None:
        path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return EnvSettings(path, environ if environ is not None else {})


# ---- the list of what can be changed ---------------------------------------------------------------------------


def test_every_provider_key_is_on_the_list_as_a_secret():
    names = {s.name: s for s in catalogue()}
    for provider, variable in key_variables().items():
        assert variable in names and names[variable].kind == "secret", provider


def test_the_list_holds_no_hosted_option_and_nothing_that_is_not_a_plain_name():
    for s in catalogue():
        assert s.name.startswith(("LLM_", "SKILLFORGE_LLM_")) or s.name in key_variables().values(), s.name
        assert s.name.replace("_", "").isalnum() and s.name == s.name.upper()
    for hosted in ("SKILLFORGE_MODE", "SKILLFORGE_ACCESS_TOKEN", "SKILLFORGE_DATA_DIR", "SKILLFORGE_ALLOWED_HOSTS", "PATH"):
        assert setting_named(hosted) is None


def test_the_kinds_of_work_on_the_page_are_the_engines_tiers_plus_the_escalation_model():
    from skillforge.ai import Tier
    from skillforge.settings.catalogue import WORK

    assert set(WORK) == {t.name for t in Tier} | {"ESCALATION"}
    for prefix in WORK:
        assert setting_named(f"LLM_{prefix}_PROVIDER") is not None and setting_named(f"LLM_{prefix}_MODEL") is not None


def test_every_setting_belongs_to_a_known_group_and_names_are_unique():
    groups = {g["key"] for g in GROUPS}
    names = [s.name for s in catalogue()]
    assert len(names) == len(set(names)) and {s.group for s in catalogue()} <= groups
    assert {"LLM_PROVIDER", "LLM_MODEL", "LLM_FALLBACKS", "LLM_BASE_URL", "LLM_CODE_MODEL", "LLM_ESCALATION_MODEL", "LLM_MAX_CALLS"} <= set(names)


# ---- what a value may look like ---------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["AIzaSyA-1_2b3C", "sk-proj-abc_DEF-123", "sk-ant-api03-xYz_09-AA", "gsk_0123456789abcdefABCDEF", "a1b2c3d4e5f6"])
def test_ordinary_keys_are_accepted(key):
    assert check_value(setting_named("GOOGLE_API_KEY"), key) == key


@pytest.mark.parametrize("bad", ["two words", 'has"quote', "has'quote", "has#hash", "line\nbreak", "carriage\rreturn", "nul\x00byte", "zero\u200bwidth",
                                 "flip\u202edirection", "dollar$sign", "back`tick", "back\\slash", "semi;colon", "tab\there", "caf\u00e9"])
def test_a_value_outside_the_safe_characters_is_refused_and_never_repeated(bad):
    with pytest.raises(ValueError) as info:
        check_value(setting_named("GOOGLE_API_KEY"), bad)
    shown = str(info.value)
    assert bad not in shown and bad.strip() not in shown and "put it in the .env file by hand" in shown


def test_a_key_that_is_too_long_is_refused():
    with pytest.raises(ValueError, match="too long"):
        check_value(setting_named("GOOGLE_API_KEY"), "a" * 401)
    assert check_value(setting_named("GOOGLE_API_KEY"), "a" * 400)


def test_the_provider_must_be_one_that_is_supported_and_is_kept_in_lower_case():
    assert check_value(setting_named("LLM_PROVIDER"), "Gemini") == "gemini"
    for good in supported_names():
        assert check_value(setting_named("LLM_PROVIDER"), good) == good
    with pytest.raises(ValueError, match="not a provider"):
        check_value(setting_named("LLM_PROVIDER"), "skynet")
    assert check_value(setting_named("LLM_CODE_PROVIDER"), "groq") == "groq"


def test_a_model_name_may_hold_slashes_colons_and_dots_but_nothing_that_changes_the_line():
    for good in ("gemini-2.5-flash", "openai/gpt-oss-20b", "models/gemini-pro", "llama3:8b", "claude-sonnet-4-5-20250929", "@cf/meta/llama-3"):
        assert check_value(setting_named("LLM_MODEL"), good) == good
    with pytest.raises(ValueError):
        check_value(setting_named("LLM_MODEL"), "a model")
    with pytest.raises(ValueError):
        check_value(setting_named("LLM_MODEL"), "a" * 201)


def test_the_custom_address_must_be_http_or_https_and_carry_no_login():
    assert check_value(setting_named("LLM_BASE_URL"), "http://localhost:1234/v1") == "http://localhost:1234/v1"
    assert check_value(setting_named("LLM_BASE_URL"), "https://gateway.example.com/openai/v1") == "https://gateway.example.com/openai/v1"
    for bad in ("ftp://example.com/v1", "example.com/v1", "https://user:pass@example.com/v1", "https://", "file:///etc/passwd", "javascript:alert(1)"):
        with pytest.raises(ValueError):
            check_value(setting_named("LLM_BASE_URL"), bad)


def test_numbers_must_be_positive_and_within_the_limit():
    assert check_value(setting_named("LLM_TIMEOUT_S"), "30") == "30"
    assert check_value(setting_named("LLM_TIMEOUT_S"), "2.5") == "2.5"
    assert check_value(setting_named("LLM_MAX_CALLS"), "40") == "40"
    for name, bad in (("LLM_TIMEOUT_S", "abc"), ("LLM_TIMEOUT_S", "0"), ("LLM_TIMEOUT_S", "-1"), ("LLM_TIMEOUT_S", "nan"), ("LLM_TIMEOUT_S", "inf"),
                      ("LLM_TIMEOUT_S", "1e999"), ("LLM_TIMEOUT_S", "99999"), ("LLM_MAX_CALLS", "2.5"), ("LLM_MAX_CALLS", "0"), ("LLM_MAX_INPUT_TOKENS", "-5")):
        with pytest.raises(ValueError):
            check_value(setting_named(name), bad)


def test_backup_models_must_be_provider_colon_model_with_a_known_provider():
    assert check_value(setting_named("LLM_FALLBACKS"), "groq:openai/gpt-oss-20b,gemini:gemini-2.5-flash") == "groq:openai/gpt-oss-20b,gemini:gemini-2.5-flash"
    for bad in ("groq", "groq:", ":model", "skynet:model", "groq:model,", "groq:a,,gemini:b", ",".join(f"groq:m{i}" for i in range(11))):
        with pytest.raises(ValueError):
            check_value(setting_named("LLM_FALLBACKS"), bad)


def test_the_cache_switch_is_only_one():
    assert check_value(setting_named("SKILLFORGE_LLM_CACHE"), "1") == "1"
    for bad in ("0", "true", "yes", "2"):
        with pytest.raises(ValueError):
            check_value(setting_named("SKILLFORGE_LLM_CACHE"), bad)


# ---- editing the text of .env ------------------------------------------------------------------------------------


def test_a_line_is_replaced_in_place_and_comments_and_other_lines_stay():
    text = "# my keys\nLLM_PROVIDER=gemini\n\n# the model\nLLM_MODEL=old\nGOOGLE_API_KEY=abc\n"
    assert edit_env_text(text, {"LLM_MODEL": "new"}) == "# my keys\nLLM_PROVIDER=gemini\n\n# the model\nLLM_MODEL=new\nGOOGLE_API_KEY=abc\n"


def test_a_missing_name_is_added_at_the_end_with_a_note_once():
    out = edit_env_text("LLM_PROVIDER=gemini\n", {"LLM_MODEL": "m", "LLM_MAX_CALLS": "9"})
    assert out.startswith("LLM_PROVIDER=gemini\n") and out.count("Added by the SkillForge Settings page") == 1
    assert out.endswith("LLM_MODEL=m\nLLM_MAX_CALLS=9\n")
    again = edit_env_text(out, {"LLM_TIMEOUT_S": "5"})
    assert again.count("Added by the SkillForge Settings page") == 1 and again.endswith("LLM_TIMEOUT_S=5\n")


def test_a_file_without_a_last_newline_and_an_empty_file_are_both_handled():
    assert edit_env_text("LLM_PROVIDER=gemini", {"LLM_MODEL": "m"}).endswith("\nLLM_MODEL=m\n")
    out = edit_env_text("", {"LLM_MODEL": "m"})
    assert out.strip().endswith("LLM_MODEL=m") and out.endswith("\n")


def test_the_files_own_line_endings_are_kept():
    crlf = edit_env_text("LLM_PROVIDER=gemini\r\nLLM_MODEL=old\r\n", {"LLM_MODEL": "new", "LLM_MAX_CALLS": "3"})
    assert "\n" not in crlf.replace("\r\n", "") and "LLM_MODEL=new\r\n" in crlf and crlf.endswith("LLM_MAX_CALLS=3\r\n")
    lf = edit_env_text("LLM_PROVIDER=gemini\nLLM_MODEL=old\n", {"LLM_MODEL": "new"})
    assert "\r" not in lf


def test_every_active_copy_of_a_name_is_updated_and_export_is_understood():
    out = edit_env_text("LLM_MODEL=a\nexport LLM_MODEL=b\n  LLM_MODEL = c\n", {"LLM_MODEL": "z"})
    assert out == "LLM_MODEL=z\nLLM_MODEL=z\nLLM_MODEL=z\n"


def test_a_commented_out_line_is_left_alone_and_the_name_is_added_below():
    out = edit_env_text("#LLM_MODEL=example\n", {"LLM_MODEL": "real"})
    assert out.startswith("#LLM_MODEL=example\n") and out.endswith("LLM_MODEL=real\n")


def test_removing_a_name_removes_every_active_copy_and_nothing_else():
    out = edit_env_text("# keep\nLLM_MODEL=a\nOTHER=1\nexport LLM_MODEL=b\n#LLM_MODEL=c\n", {"LLM_MODEL": None})
    assert out == "# keep\nOTHER=1\n#LLM_MODEL=c\n"
    assert edit_env_text("A=1\n", {"LLM_MODEL": None}) == "A=1\n"


def test_a_name_that_only_starts_the_same_way_is_not_touched():
    out = edit_env_text("LLM_MODEL_EXTRA=keep\nLLM_MODEL=old\n", {"LLM_MODEL": "new"})
    assert out == "LLM_MODEL_EXTRA=keep\nLLM_MODEL=new\n"


# ---- the settings, read and applied -----------------------------------------------------------------------------


def row(view: dict, name: str) -> dict:
    return next(s for s in view["settings"] if s["name"] == name)


def test_a_fresh_setup_shows_everything_unset(tmp_path):
    view = settings_for(tmp_path).view()
    assert view["file"] == ".env" and view["file_exists"] is False
    assert all(s["set"] is False and s["source"] == "unset" and s["editable"] is True for s in view["settings"])


def test_the_view_never_holds_a_key_in_any_form(tmp_path):
    s = settings_for(tmp_path, f"GOOGLE_API_KEY={GEMINI_KEY}\nLLM_MODEL=m1\n", environ={"OPENAI_API_KEY": OPENAI_KEY})
    view = s.view()
    dump = json.dumps(view)
    for key in (GEMINI_KEY, OPENAI_KEY):
        assert key not in dump and key[-6:] not in dump and key[:7] not in dump
    assert row(view, "GOOGLE_API_KEY")["set"] is True and row(view, "GOOGLE_API_KEY")["source"] == "file" and "value" not in row(view, "GOOGLE_API_KEY")
    assert row(view, "OPENAI_API_KEY")["set"] is True and row(view, "OPENAI_API_KEY")["source"] == "environment"
    assert row(view, "LLM_MODEL")["value"] == "m1"


def test_a_setting_from_the_computers_environment_is_shown_but_cannot_be_changed_here(tmp_path):
    s = settings_for(tmp_path, "LLM_MODEL=from-file\n", environ={"LLM_MODEL": "from-environment"})
    r = row(s.view(), "LLM_MODEL")
    assert r["source"] == "environment" and r["editable"] is False and r["value"] == "from-environment"
    before = (tmp_path / ".env").read_bytes()
    with pytest.raises(SettingsError) as info:
        s.apply({"LLM_MODEL": "x"})
    assert "environment" in str(info.value) and info.value.problems[0]["name"] == "LLM_MODEL"
    assert (tmp_path / ".env").read_bytes() == before and s.environ["LLM_MODEL"] == "from-environment"


def test_applying_a_change_writes_the_file_and_takes_effect_at_once(tmp_path):
    s = settings_for(tmp_path, "# mine\nLLM_PROVIDER=gemini\n")
    s.apply({"GOOGLE_API_KEY": GEMINI_KEY, "LLM_MODEL": "gemini-2.5-flash"})
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "# mine\nLLM_PROVIDER=gemini\n" in written and f"GOOGLE_API_KEY={GEMINI_KEY}" in written and "LLM_MODEL=gemini-2.5-flash" in written
    assert s.environ["GOOGLE_API_KEY"] == GEMINI_KEY and s.environ["LLM_MODEL"] == "gemini-2.5-flash"
    view = s.view()
    assert row(view, "GOOGLE_API_KEY")["source"] == "file" and row(view, "LLM_MODEL")["value"] == "gemini-2.5-flash" and view["file_exists"] is True


def test_a_value_is_changed_again_without_a_restart(tmp_path):
    s = settings_for(tmp_path)
    s.apply({"LLM_MODEL": "one"})
    s.apply({"LLM_MODEL": "two"})
    assert s.environ["LLM_MODEL"] == "two" and (tmp_path / ".env").read_text(encoding="utf-8").count("LLM_MODEL=") == 1


def test_removing_a_setting_clears_the_file_and_the_running_process(tmp_path):
    s = settings_for(tmp_path, f"GOOGLE_API_KEY={GEMINI_KEY}\nLLM_MODEL=m\n")
    s.sync()
    assert s.environ["GOOGLE_API_KEY"] == GEMINI_KEY
    s.apply({"GOOGLE_API_KEY": None})
    assert "GOOGLE_API_KEY" not in s.environ and "GOOGLE_API_KEY" not in (tmp_path / ".env").read_text(encoding="utf-8")
    assert row(s.view(), "GOOGLE_API_KEY")["set"] is False and s.environ["LLM_MODEL"] == "m"


def test_an_empty_value_means_remove_it(tmp_path):
    s = settings_for(tmp_path, "LLM_MODEL=m\n")
    s.apply({"LLM_MODEL": "  "})
    assert "LLM_MODEL" not in s.environ and "LLM_MODEL" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_one_bad_value_means_nothing_is_changed(tmp_path):
    s = settings_for(tmp_path, "LLM_MODEL=keep\n")
    before = (tmp_path / ".env").read_bytes()
    with pytest.raises(SettingsError) as info:
        s.apply({"LLM_MODEL": "good-model", "GOOGLE_API_KEY": "has a space", "LLM_MAX_CALLS": "zero"})
    assert (tmp_path / ".env").read_bytes() == before and s.environ.get("LLM_MODEL", "keep") == "keep" and "GOOGLE_API_KEY" not in s.environ
    assert {p["name"] for p in info.value.problems} == {"GOOGLE_API_KEY", "LLM_MAX_CALLS"}
    assert "has a space" not in str(info.value) and "has a space" not in json.dumps(info.value.problems)


def test_a_name_that_is_not_on_the_list_is_refused(tmp_path):
    s = settings_for(tmp_path)
    for name in ("PATH", "SKILLFORGE_MODE", "SKILLFORGE_ACCESS_TOKEN", "llm_model", "LLM_MODEL ", "LLM_MODEL=x\nPATH", ""):
        with pytest.raises(SettingsError):
            s.apply({name: "x"})
    assert not (tmp_path / ".env").exists()


def test_a_hand_edit_of_the_file_is_picked_up_and_a_real_environment_variable_wins(tmp_path):
    s = settings_for(tmp_path, "LLM_MODEL=one\nLLM_MAX_CALLS=5\n", environ={"LLM_MAX_CALLS": "9"})
    s.sync()
    assert s.environ["LLM_MODEL"] == "one" and s.environ["LLM_MAX_CALLS"] == "9"
    (tmp_path / ".env").write_text("LLM_MODEL=two\nLLM_MAX_CALLS=5\n", encoding="utf-8")
    s.sync()
    assert s.environ["LLM_MODEL"] == "two" and s.environ["LLM_MAX_CALLS"] == "9"
    (tmp_path / ".env").write_text("LLM_MAX_CALLS=5\n", encoding="utf-8")
    s.sync()
    # taken out of the file by hand: a running server keeps it (only a save from the page removes one; see the review tests below)
    assert s.environ["LLM_MODEL"] == "two" and s.environ["LLM_MAX_CALLS"] == "9"


def test_a_file_that_cannot_be_read_right_now_changes_nothing_in_the_process(tmp_path):
    """A cloud-synced folder can hold the file for a moment. That must not look like "every setting was removed"."""
    s = settings_for(tmp_path, f"GOOGLE_API_KEY={GEMINI_KEY}\nLLM_MODEL=m\n")
    s.sync()
    (tmp_path / ".env").write_bytes(b"LLM_MODEL=\xff\xfe\x00bad\n")  # cannot be read as text
    s.sync()
    assert s.environ["GOOGLE_API_KEY"] == GEMINI_KEY and s.environ["LLM_MODEL"] == "m"
    assert row(s.view(), "GOOGLE_API_KEY")["set"] is True


def test_a_value_set_by_something_else_in_this_process_is_never_overwritten_or_removed(tmp_path):
    s = settings_for(tmp_path, "LLM_MODEL=from-file\n")
    s.sync()
    s.environ["LLM_MODEL"] = "changed-by-code"
    (tmp_path / ".env").write_text("LLM_MODEL=another\n", encoding="utf-8")
    s.sync()
    assert s.environ["LLM_MODEL"] == "changed-by-code"
    assert row(s.view(), "LLM_MODEL")["source"] == "environment"


def test_a_hand_written_address_is_shown_without_a_login_or_a_query(tmp_path):
    s = settings_for(tmp_path, "LLM_BASE_URL=https://user:secret@gateway.example.com/v1?token=abc123\n")
    r = row(s.view(), "LLM_BASE_URL")
    assert "secret" not in json.dumps(r) and "abc123" not in json.dumps(r) and "gateway.example.com" in r["value"]


def test_the_file_is_created_when_missing_and_no_temporary_file_is_left(tmp_path):
    s = settings_for(tmp_path)
    s.apply({"LLM_MODEL": "m"})
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]


def test_a_failed_write_leaves_the_old_file_and_the_process_untouched_and_no_leftover(tmp_path, monkeypatch):
    s = settings_for(tmp_path, "LLM_MODEL=keep\n")
    before = (tmp_path / ".env").read_bytes()
    monkeypatch.setattr("skillforge.settings.envfile.RETRY_DELAY", 0)

    def refuse(*_a, **_k):
        raise PermissionError("locked by another program")

    monkeypatch.setattr("skillforge.settings.envfile.os.replace", refuse)
    with pytest.raises(SettingsError, match="Could not write the .env file"):
        s.apply({"LLM_MODEL": "new", "GOOGLE_API_KEY": GEMINI_KEY})
    assert (tmp_path / ".env").read_bytes() == before and "GOOGLE_API_KEY" not in s.environ
    assert sorted(p.name for p in tmp_path.iterdir()) == [".env"]


def test_a_file_that_is_not_text_is_not_rewritten(tmp_path):
    s = settings_for(tmp_path, b"LLM_MODEL=\xff\xfe\x00bad\n")
    before = (tmp_path / ".env").read_bytes()
    with pytest.raises(SettingsError, match="not valid UTF-8"):
        s.apply({"LLM_MODEL": "m"})
    assert (tmp_path / ".env").read_bytes() == before


def test_a_file_that_starts_with_a_byte_order_mark_still_has_its_first_line_found(tmp_path):
    s = settings_for(tmp_path, b"\xef\xbb\xbfLLM_MODEL=old\nOTHER=1\n")
    s.apply({"LLM_MODEL": "new"})
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert text.count("LLM_MODEL=") == 1 and "LLM_MODEL=new" in text and "OTHER=1" in text


def test_two_saves_at_once_both_land(tmp_path):
    s = settings_for(tmp_path)
    errors: list[BaseException] = []

    def save(name: str, value: str) -> None:
        try:
            s.apply({name: value})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(n, v)) for n, v in (("LLM_MODEL", "m"), ("LLM_MAX_CALLS", "7"), ("LLM_TIMEOUT_S", "20"), ("LLM_PROVIDER", "groq"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert all(x in text for x in ("LLM_MODEL=m", "LLM_MAX_CALLS=7", "LLM_TIMEOUT_S=20", "LLM_PROVIDER=groq"))


def test_a_single_value_with_an_equals_sign_survives_a_round_trip(tmp_path):
    s = settings_for(tmp_path)
    s.apply({"GOOGLE_API_KEY": "abc=def==", "LLM_BASE_URL": "http://localhost:1234/v1"})
    fresh = EnvSettings(tmp_path / ".env", {})
    fresh.sync()
    assert fresh.environ["GOOGLE_API_KEY"] == "abc=def==" and fresh.environ["LLM_BASE_URL"] == "http://localhost:1234/v1"


# ---- what the independent review found (each of these failed before the fix) ------------------------------------

from skillforge.ai.redact import redact  # noqa: E402

CANNOT_EDIT = "cannot edit safely"


def test_a_value_that_spans_several_lines_is_never_edited_into(tmp_path):
    raw = b'PEM="line1\nGOOGLE_API_KEY=inside\nline3"\nLLM_MODEL=a\n'
    s = settings_for(tmp_path, raw)
    for changes in ({"GOOGLE_API_KEY": "newkey123"}, {"GOOGLE_API_KEY": None}):
        with pytest.raises(SettingsError, match=CANNOT_EDIT):
            s.apply(changes)
        assert (tmp_path / ".env").read_bytes() == raw
    s.apply({"LLM_MODEL": "b"})  # a change that does not touch that value is still fine
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert 'PEM="line1\nGOOGLE_API_KEY=inside\nline3"' in text and "LLM_MODEL=b" in text


def test_a_lone_carriage_return_is_not_edited_over(tmp_path):
    raw = b"LLM_MODEL=a\rGOOGLE_API_KEY=old\nOTHER=keep\n"
    s = settings_for(tmp_path, raw)
    for changes in ({"LLM_MODEL": "newmodel"}, {"GOOGLE_API_KEY": None}):
        with pytest.raises(SettingsError, match=CANNOT_EDIT):
            s.apply(changes)
        assert (tmp_path / ".env").read_bytes() == raw


def test_a_file_that_is_not_text_is_reported_not_silently_ignored(tmp_path):
    s = settings_for(tmp_path, b"# caf\xe9\nGOOGLE_API_KEY=abc12345\n")
    view = s.view()
    assert view["file_exists"] is True and view["file_readable"] is False
    (tmp_path / "other").mkdir()
    assert settings_for(tmp_path / "other", "LLM_MODEL=m\n").view()["file_readable"] is True
    assert settings_for(tmp_path.parent / "no-such-folder").view()["file_readable"] is True  # no file is nothing to read, not a problem


def test_a_lowercase_name_in_the_file_is_the_same_setting_where_names_are_not_case_sensitive(tmp_path, monkeypatch):
    monkeypatch.setattr("skillforge.settings.store.FOLD_CASE", True)  # Windows
    s = settings_for(tmp_path, "google_api_key=abc12345\n")
    r = row(s.view(), "GOOGLE_API_KEY")
    assert r["set"] is True and r["source"] == "file" and r["editable"] is True
    s.apply({"GOOGLE_API_KEY": "newkey12345"})
    assert s.environ["GOOGLE_API_KEY"] == "newkey12345"
    s.apply({"GOOGLE_API_KEY": None})
    assert "GOOGLE_API_KEY" not in s.environ and "google_api_key" not in (tmp_path / ".env").read_text(encoding="utf-8")
    s.sync()
    assert "GOOGLE_API_KEY" not in s.environ  # the lowercase line is gone, so nothing brings it back


def test_a_value_that_uses_another_is_worked_out_the_way_it_always_was_with_the_real_environment_first(tmp_path, monkeypatch):
    monkeypatch.setenv("BASEX", "fromenv")
    s = settings_for(tmp_path, "BASEX=fromfile\nLLM_MODEL=${BASEX}-model\n")
    s.sync()
    assert s.environ["LLM_MODEL"] == "fromenv-model"


def test_names_the_page_does_not_manage_are_applied_once_as_before_and_never_changed_or_removed(tmp_path):
    s = settings_for(tmp_path, "LLM_CODE_TIMEOUT_S=120\nHTTPS_PROXY=http://a\n")
    s.sync()
    assert s.environ["LLM_CODE_TIMEOUT_S"] == "120" and s.environ["HTTPS_PROXY"] == "http://a"  # still read, as load_dotenv did
    (tmp_path / ".env").write_text("LLM_CODE_TIMEOUT_S=999\nHTTPS_PROXY=http://b\nSKILLFORGE_DATA_DIR=C:/x\n", encoding="utf-8")
    s.sync()
    assert s.environ["HTTPS_PROXY"] == "http://a" and s.environ["LLM_CODE_TIMEOUT_S"] == "120"  # a running server does not change them
    assert s.environ["SKILLFORGE_DATA_DIR"] == "C:/x"  # a name that was not set yet is applied, as before
    (tmp_path / ".env").write_text("", encoding="utf-8")
    s.sync()
    assert s.environ["HTTPS_PROXY"] == "http://a"


def test_a_name_taken_out_of_the_file_by_hand_is_not_dropped_from_a_running_server(tmp_path):
    """A half-written file must never look like "every setting was removed". Only a save from the page removes one."""
    s = settings_for(tmp_path, f"GOOGLE_API_KEY={GEMINI_KEY}\nLLM_MODEL=m\n")
    s.sync()
    (tmp_path / ".env").write_text("", encoding="utf-8")  # what a reader sees between a truncate and a write
    s.sync()
    assert s.environ["GOOGLE_API_KEY"] == GEMINI_KEY and s.environ["LLM_MODEL"] == "m"
    (tmp_path / ".env").write_text(f"GOOGLE_API_KEY={GEMINI_KEY}\nLLM_MODEL=m2\n", encoding="utf-8")
    s.sync()
    assert s.environ["LLM_MODEL"] == "m2"  # a changed value does go live


def test_the_model_lookup_gets_one_consistent_copy_of_the_settings(tmp_path):
    s = settings_for(tmp_path, "LLM_MODEL=a\n")
    snap = s.snapshot()
    assert snap == {"LLM_MODEL": "a"} and snap is not s.environ
    s.apply({"LLM_MODEL": "b"})
    assert snap["LLM_MODEL"] == "a"  # a copy: a later save cannot change what a lookup already holds


def test_a_symlinked_env_file_is_edited_through_the_link(tmp_path):
    real, link = tmp_path / "real.env", tmp_path / ".env"
    real.write_text("LLM_MODEL=a\n", encoding="utf-8")
    try:
        link.symlink_to(real)
    except (OSError, NotImplementedError):
        pytest.skip("this account cannot create symbolic links")
    EnvSettings(link, {}).apply({"LLM_MODEL": "b"})
    assert link.is_symlink() and "LLM_MODEL=b" in real.read_text(encoding="utf-8")


def test_a_read_only_or_locked_file_says_both_things_it_could_be(tmp_path, monkeypatch):
    s = settings_for(tmp_path, "LLM_MODEL=keep\n")
    monkeypatch.setattr("skillforge.settings.envfile.RETRY_DELAY", 0)

    def refuse(*_a, **_k):
        raise PermissionError("denied")

    monkeypatch.setattr("skillforge.settings.envfile.os.replace", refuse)
    with pytest.raises(SettingsError, match=r"read-only, or open in another program"):
        s.apply({"LLM_MODEL": "new"})


def test_a_hand_written_address_with_a_bad_port_is_still_shown_as_something(tmp_path):
    r = row(settings_for(tmp_path, "LLM_BASE_URL=http://host:99999/v1\n").view(), "LLM_BASE_URL")
    assert r["set"] is True and r["value"] == "(not a valid address)"


def test_an_address_may_be_an_ipv6_literal_and_round_trips(tmp_path):
    assert check_value(setting_named("LLM_BASE_URL"), "http://[::1]:1234/v1") == "http://[::1]:1234/v1"
    s = settings_for(tmp_path)
    s.apply({"LLM_BASE_URL": "http://[::1]:1234/v1"})
    assert row(s.view(), "LLM_BASE_URL")["value"] == "http://[::1]:1234/v1"
    with pytest.raises(ValueError):  # brackets are for an address only, not a key or a model name
        check_value(setting_named("LLM_MODEL"), "a[b]")


@pytest.mark.parametrize("message", [
    "Incorrect API key provided: sk-proj-****...abcd.", "invalid key AIzaSy****WXYZ was refused", "your key ending in ****wxyz is wrong",
])
def test_a_masked_key_in_a_providers_error_is_redacted_too(message):
    out = redact(message)
    for tail in ("abcd", "WXYZ", "wxyz", "sk-proj", "AIzaSy"):
        assert tail not in out, out


def test_ordinary_error_text_is_left_alone_by_redaction():
    text = "Rate limited. Try again in 20 seconds. The model m-1 was not found."
    assert redact(text) == text


def test_a_value_over_several_lines_in_a_windows_file_reads_as_it_always_did(tmp_path):
    """load_dotenv opened the file as text, so a line ending inside a quoted value was read as a plain newline."""
    s = settings_for(tmp_path, b'PEM="a\r\nb"\r\nLLM_MODEL=m\r\n')
    s.sync()
    assert s.environ["PEM"] == "a\nb" and s.environ["LLM_MODEL"] == "m"
