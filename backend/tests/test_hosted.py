"""The hosted version: a sign-in in front of the whole API, and the local-only behaviour left exactly as it was."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from skillforge.api import create_app
from skillforge.api.hosted import (
    COOKIE, Hosted, HostedConfigError, LoginGuard, bearer_ok, make_cookie, valid_cookie,
)
from skillforge.library import Library

TOKEN = "a-long-enough-access-token-1234567890"


def hosted(**kw) -> Hosted:
    return Hosted(token=kw.pop("token", TOKEN), **kw)


def client(tmp_path, *, hosted_cfg=None, base="http://localhost", **kw) -> TestClient:
    app = create_app(Library(tmp_path / "library"), hosted=hosted_cfg, **kw)
    return TestClient(app, base_url=base)


def signed_in(tmp_path, **kw) -> TestClient:
    c = client(tmp_path, hosted_cfg=hosted(**kw))
    assert c.post("/api/auth/login", json={"token": TOKEN}).status_code == 200
    return c


# ---- configuration ------------------------------------------------------------------------------------------


def test_the_environment_turns_hosted_mode_on_only_when_asked():
    assert Hosted.from_env({}) is None
    assert Hosted.from_env({"SKILLFORGE_MODE": "local"}) is None
    h = Hosted.from_env({
        "SKILLFORGE_MODE": "Hosted", "SKILLFORGE_ACCESS_TOKEN": f"  {TOKEN} ",
        "SKILLFORGE_ALLOWED_HOSTS": " App.Example.com:443 , ,other.example ", "SKILLFORGE_COOKIE_SECURE": "1",
    })
    assert h is not None and h.token == TOKEN and h.allowed_hosts == frozenset({"app.example.com", "other.example"}) and h.secure_cookie is True


def test_hosted_mode_refuses_to_start_without_a_strong_token():
    with pytest.raises(HostedConfigError, match="SKILLFORGE_ACCESS_TOKEN"):
        Hosted.from_env({"SKILLFORGE_MODE": "hosted"})
    with pytest.raises(HostedConfigError, match="at least 20"):
        Hosted.from_env({"SKILLFORGE_MODE": "hosted", "SKILLFORGE_ACCESS_TOKEN": "too-short"})
    with pytest.raises(HostedConfigError, match="SKILLFORGE_MODE"):
        Hosted.from_env({"SKILLFORGE_MODE": "public"})


# ---- the cookie and the bearer token ------------------------------------------------------------------------


def test_a_cookie_is_valid_only_if_signed_with_this_token_and_not_expired():
    h = hosted()
    value = make_cookie(h, now=1_000.0)
    assert valid_cookie(h, value, now=1_001.0)
    assert not valid_cookie(h, value, now=1_000.0 + h.session_days * 86400 + 1)  # expired
    assert not valid_cookie(hosted(token="another-long-enough-token-0987654321"), value, now=1_001.0)  # another token
    head, _, sig = value.rpartition(".")
    assert not valid_cookie(h, f"{head}.{'0' * len(sig)}", now=1_001.0)  # tampered signature
    assert not valid_cookie(h, head.replace("v1.", "v1.9") + "." + sig, now=1_001.0)  # tampered expiry
    for junk in ("", "x", "v1.abc.def", "v2.1.2", "....", None):
        assert not valid_cookie(h, junk, now=1.0)


def test_bearer_must_match_exactly():
    h = hosted()
    assert bearer_ok(h, f"Bearer {TOKEN}")
    assert not bearer_ok(h, f"bearer {TOKEN}x") and not bearer_ok(h, TOKEN) and not bearer_ok(h, None) and not bearer_ok(h, "Bearer ")


def test_the_login_guard_locks_after_five_failures_and_unlocks_later():
    now = {"t": 100.0}
    g = LoginGuard(clock=lambda: now["t"])
    for _ in range(4):
        g.failed()
    assert g.locked_for() == 0
    g.failed()
    assert 0 < g.locked_for() <= 60
    now["t"] += 61
    assert g.locked_for() == 0
    g.failed()
    g.succeeded()  # a good sign-in forgets the failures
    for _ in range(4):
        g.failed()
    assert g.locked_for() == 0


# ---- the API in hosted mode -----------------------------------------------------------------------------------


def test_everything_but_health_and_sign_in_needs_a_sign_in(tmp_path):
    c = client(tmp_path, hosted_cfg=hosted())
    for method, path in (("get", "/api/library"), ("get", "/api/builds"), ("get", "/api/sandbox"), ("get", "/api/provider"),
                         ("post", "/api/provider/check"), ("post", "/api/builds"), ("get", "/api/rescan"), ("get", "/api/languages")):
        r = getattr(c, method)(path)
        assert r.status_code == 401 and r.json()["detail"] == "Sign in first.", path
    health = c.get("/api/health")
    assert health.status_code == 200 and health.json()["mode"] == "hosted"
    assert c.get("/api/auth/status").json() == {"required": True, "authenticated": False}


def test_signing_in_sets_a_safe_cookie_and_opens_the_api(tmp_path):
    c = client(tmp_path, hosted_cfg=hosted())
    bad = c.post("/api/auth/login", json={"token": "nope"})
    assert bad.status_code == 401 and COOKIE not in bad.headers.get("set-cookie", "")
    ok = c.post("/api/auth/login", json={"token": TOKEN})
    assert ok.status_code == 200 and ok.json() == {"authenticated": True}
    cookie = ok.headers["set-cookie"].lower()
    assert COOKIE in cookie and "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie and "secure" not in cookie
    assert c.get("/api/library").status_code == 200 and c.get("/api/auth/status").json() == {"required": True, "authenticated": True}
    assert TOKEN not in ok.text and TOKEN not in c.get("/api/auth/status").text


def test_the_cookie_is_secure_behind_https_or_when_forced(tmp_path):
    c = client(tmp_path, hosted_cfg=hosted())
    r = c.post("/api/auth/login", json={"token": TOKEN}, headers={"x-forwarded-proto": "https"})
    assert "secure" in r.headers["set-cookie"].lower()
    forced = client(tmp_path, hosted_cfg=hosted(secure_cookie=True)).post("/api/auth/login", json={"token": TOKEN})
    assert "secure" in forced.headers["set-cookie"].lower()


def test_a_script_can_use_the_bearer_token_instead_of_a_cookie(tmp_path):
    c = client(tmp_path, hosted_cfg=hosted())
    assert c.get("/api/library", headers={"authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert c.get("/api/library", headers={"authorization": "Bearer wrong"}).status_code == 401


def test_signing_out_ends_the_session(tmp_path):
    c = signed_in(tmp_path)
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/library").status_code == 401


def test_a_forged_cookie_does_not_open_anything(tmp_path):
    c = client(tmp_path, hosted_cfg=hosted())
    c.cookies.set(COOKIE, "v1.99999999999." + "0" * 64)
    assert c.get("/api/library").status_code == 401


def test_too_many_wrong_tokens_lock_sign_in_even_for_the_right_one(tmp_path):
    c = client(tmp_path, hosted_cfg=hosted())
    for _ in range(5):
        assert c.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
    locked = c.post("/api/auth/login", json={"token": TOKEN})
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0 and "Too many" in locked.json()["detail"]
    assert c.get("/api/library").status_code == 401


def test_installing_into_a_folder_on_the_server_is_turned_off(tmp_path):
    c = signed_in(tmp_path)
    r = c.post("/api/library/anything/install", json={"target": "folder", "folder": str(tmp_path)})
    assert r.status_code == 403 and "Export" in r.json()["detail"]


def test_the_interactive_docs_are_off_in_hosted_mode(tmp_path):
    c = signed_in(tmp_path)
    assert c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404


def test_only_loopback_and_the_listed_hosts_may_be_used(tmp_path):
    other = client(tmp_path, hosted_cfg=hosted(), base="http://app.example.com")
    assert other.get("/api/health").status_code == 403
    allowed = client(tmp_path, hosted_cfg=hosted(allowed_hosts=frozenset({"app.example.com"})), base="http://app.example.com")
    assert allowed.get("/api/health").status_code == 200
    anywhere = client(tmp_path, hosted_cfg=hosted(allowed_hosts=frozenset({"*"})), base="http://whatever.example")
    assert anywhere.get("/api/health").status_code == 200


def test_a_page_on_a_listed_host_is_trusted_and_any_other_page_is_not(tmp_path):
    c = client(tmp_path, hosted_cfg=hosted(allowed_hosts=frozenset({"app.example.com"})), base="http://app.example.com")
    body = {"token": TOKEN}
    assert c.post("/api/auth/login", json=body, headers={"origin": "https://app.example.com"}).status_code == 200
    assert c.post("/api/auth/login", json=body, headers={"origin": "https://evil.example"}).status_code == 403


# ---- local mode is unchanged --------------------------------------------------------------------------------


def test_local_mode_has_no_sign_in_and_says_so(tmp_path):
    c = client(tmp_path)
    assert c.get("/api/library").status_code == 200
    assert c.get("/api/health").json()["mode"] == "local"
    assert c.get("/api/auth/status").json() == {"required": False, "authenticated": True}
    r = c.post("/api/auth/login", json={"token": "x"})
    assert r.status_code == 400 and "no sign-in" in r.json()["detail"]
    assert c.get("/api/docs").status_code == 200  # the interactive docs stay available on your own machine


def test_local_mode_still_refuses_other_host_names(tmp_path):
    assert client(tmp_path, base="http://app.example.com").get("/api/health").status_code == 403


def test_no_response_ever_contains_the_token(tmp_path):
    c = signed_in(tmp_path)
    login = c.post("/api/auth/login", json={"token": TOKEN})
    seen = [c.get(p).text for p in ("/api/health", "/api/auth/status", "/api/library", "/api/sandbox")] + [login.text, json.dumps(dict(login.headers))]
    assert all(TOKEN not in text for text in seen)
