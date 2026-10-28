import httpx
import pytest

from poze import auth, db


@pytest.fixture
def dsm(monkeypatch):
    """DSM simulat. `state` setează răspunsul; `calls` păstrează query-urile primite."""
    state = {"response": {"success": True, "data": {"sid": "SID1"}}}
    calls = []

    def handler(request: httpx.Request):
        calls.append(dict(request.url.params))
        if request.url.params.get("method") == "logout":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json=state["response"])

    monkeypatch.setattr(auth, "_transport", httpx.MockTransport(handler))
    auth._attempts.clear()
    state["calls"] = calls
    return state


def login(client, user="ana", password="pw", **extra):
    return client.post("/api/login", json={"user": user, "password": password, "device": "tel", **extra})


def test_health(client):
    r = client.get("/api/health")
    assert r.json() == {"ok": True, "version": "0.6.0", "api": 1}


def test_login_ok_returns_token_and_logs_out_dsm(client, dsm):
    r = login(client)
    assert r.status_code == 200
    assert r.json()["user"] == "ana" and r.json()["token"]
    methods = [c.get("method") for c in dsm["calls"]]
    assert methods == ["login", "logout"]
    assert dsm["calls"][1]["_sid"] == "SID1"


def test_login_needs_otp(client, dsm):
    dsm["response"] = {"success": False, "error": {"code": 403}}
    r = login(client)
    assert r.status_code == 401
    assert r.json()["need_otp"] is True
    assert r.json()["error"] == "Introdu codul din aplicația de autentificare."


def test_login_with_otp_ok(client, dsm):
    r = login(client, otp="123456")
    assert r.status_code == 200
    assert dsm["calls"][0]["otp_code"] == "123456"


def test_wrong_otp_message(client, dsm):
    dsm["response"] = {"success": False, "error": {"code": 404}}
    r = login(client, otp="000000")
    assert r.status_code == 401
    assert r.json() == {"error": "Cod greșit."}


def test_bad_password(client, dsm):
    dsm["response"] = {"success": False, "error": {"code": 400}}
    r = login(client)
    assert r.status_code == 401
    assert r.json() == {"error": "Utilizator sau parolă greșită."}


def test_token_stored_hashed(client, dsm, env):
    token = login(client).json()["token"]
    conn = db.connect(env["data"])
    rows = [r["hash"] for r in conn.execute("select hash from tokens")]
    assert len(rows) == 1 and rows[0] != token and len(rows[0]) == 64


def test_rate_limit(client, dsm):
    dsm["response"] = {"success": False, "error": {"code": 400}}
    for _ in range(5):
        assert login(client).status_code == 401
    dsm["response"] = {"success": True, "data": {"sid": "S"}}
    r = login(client)
    assert r.status_code == 429
    assert r.json() == {"error": "Prea multe încercări. Încearcă din nou peste 15 minute."}


@pytest.mark.parametrize("user", ["../bogdan", "..", ".", "nu_exista", "a/b", ""])
def test_invalid_user_never_reaches_dsm(client, dsm, user):
    r = login(client, user=user)
    assert r.status_code == 401
    assert r.json() == {"error": "Utilizator sau parolă greșită."}
    assert dsm["calls"] == []


def test_invalid_user_counts_toward_limit(client, dsm):
    for _ in range(5):
        login(client, user="nu_exista")
    assert login(client, user="nu_exista").status_code == 429


def test_logout_revokes(client, dsm):
    token = login(client).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/me", headers=h).json() == {"user": "ana"}
    assert client.post("/api/logout", headers=h).status_code == 204
    r = client.get("/api/me", headers=h)
    assert r.status_code == 401
    assert r.json() == {"error": "Autentificare necesară."}


def test_me_without_token(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_last_used_updated(client, dsm, env):
    token = login(client).json()["token"]
    conn = db.connect(env["data"])
    conn.execute("update tokens set last_used='2000-01-01 00:00:00'")
    conn.commit()
    client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert conn.execute("select last_used from tokens").fetchone()[0] > "2000-01-01 00:00:00"


def test_login_with_capital_letter_uses_real_account(client, dsm):
    # tastatura telefonului pune singură majusculă la început
    r = login(client, user="Ana")
    assert r.status_code == 200
    assert r.json()["user"] == "ana"
    assert dsm["calls"][0]["account"] == "ana"


def test_login_uses_dsm_app_session(client, dsm):
    # un cont fără drept de administrator e refuzat (402) la o sesiune inventată
    login(client)
    assert {c["session"] for c in dsm["calls"]} == {"webui"}


def test_no_dsm_permission_is_explained(client, dsm):
    dsm["response"] = {"success": False, "error": {"code": 402}}
    r = login(client)
    assert r.status_code == 403
    assert "Application" in r.json()["error"] or "Applications" in r.json()["error"]
