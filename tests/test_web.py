"""Accesul din browser: sesiune în cookie HttpOnly, apărare CSRF, expirare, pagina statică."""
import pytest
from fastapi.testclient import TestClient

from poze import auth, db
from tests.test_auth import dsm  # noqa: F401  (fixture)


@pytest.fixture
def web(env):
    from poze.app import create_app

    # https: cookie-ul e Secure, deci clientul nu-l trimite pe http
    return TestClient(create_app(start_indexer=False), base_url="https://testserver")


def web_login(web, **extra):
    return web.post("/api/web/login", json={"user": "ana", "password": "pw", **extra},
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux) Firefox/140.0"})


def test_web_login_sets_strict_httponly_cookie_and_no_token_in_body(web, dsm):
    r = web_login(web)
    assert r.status_code == 200
    assert r.json() == {"user": "ana"}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{auth.COOKIE}=")
    for flag in ("HttpOnly", "Secure", "SameSite=strict", "Path=/", f"Max-Age={auth.WEB_DAYS * 86400}"):
        assert flag.lower() in cookie.lower()


def test_web_login_needs_otp_like_the_app(web, dsm):
    dsm["response"] = {"success": False, "error": {"code": 403}}
    r = web_login(web)
    assert r.status_code == 401 and r.json()["need_otp"] is True
    assert "set-cookie" not in r.headers


def test_cookie_authenticates_reads(web, dsm):
    web_login(web)
    assert web.get("/api/me").json() == {"user": "ana"}
    assert web.get("/api/assets").status_code == 200


def test_cookie_writes_need_the_custom_header(web, dsm):
    web_login(web)
    r = web.post("/api/albums", json={"name": "Vara"})
    assert r.status_code == 403
    r = web.post("/api/albums", json={"name": "Vara"}, headers={"X-Poze": "1"})
    assert r.status_code in (200, 201)


def test_bearer_needs_no_custom_header(client, dsm):
    from tests.test_auth import login

    token = login(client).json()["token"]
    r = client.post("/api/albums", json={"name": "Vara"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code in (200, 201)


def test_web_session_records_browser_and_expires_after_idle_days(web, dsm, env):
    web_login(web)
    conn = db.connect(env["data"])
    row = conn.execute("select device, web from tokens").fetchone()
    assert row["web"] == 1 and row["device"] == "Browser: Firefox pe Linux"
    conn.execute("update tokens set last_used='2000-01-01 00:00:00'")
    conn.commit()
    r = web.get("/api/me")
    assert r.status_code == 401
    assert conn.execute("select count(*) from tokens").fetchone()[0] == 0  # sesiunea expirată e ștearsă


def test_app_tokens_do_not_expire(client, dsm, env):
    from tests.test_auth import login

    token = login(client).json()["token"]
    conn = db.connect(env["data"])
    conn.execute("update tokens set last_used='2000-01-01 00:00:00'")
    conn.commit()
    assert client.get("/api/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_web_logout_revokes_and_clears_cookie(web, dsm, env):
    web_login(web)
    r = web.post("/api/logout", headers={"X-Poze": "1"})
    assert r.status_code == 204
    assert f"{auth.COOKIE}=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()
    assert db.connect(env["data"]).execute("select count(*) from tokens").fetchone()[0] == 0
    web.cookies.clear()
    assert web.get("/api/me").status_code == 401


def test_index_page_is_served_with_strict_headers(web):
    r = web.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "<title>Amintiri</title>" in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and "unsafe-inline" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert web.get("/app.js").status_code == 200


def test_unknown_api_path_stays_json(web):
    r = web.get("/api/nu-exista")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("ua,label", [
    ("Mozilla/5.0 (Windows NT 10.0; Win64) AppleWebKit Chrome/131.0 Safari/537.36", "Browser: Chrome pe Windows"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit Version/18.0 Safari/605.1.15", "Browser: Safari pe Mac"),
    ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/131.0 Safari/537.36 Edg/131.0", "Browser: Edge pe Windows"),
    ("Mozilla/5.0 (Linux; Android 15) AppleWebKit Chrome/131.0 Mobile Safari/537.36", "Browser: Chrome pe Android"),
    ("", "Browser"),
])
def test_browser_label(ua, label):
    assert auth.browser_label(ua) == label


def test_login_creates_photos_folder_for_new_user(client, dsm, env, no_chown):
    import shutil

    from tests.test_auth import login

    shutil.rmtree(env["homes"] / "ana" / "Photos")
    assert login(client).status_code == 200
    assert (env["homes"] / "ana" / "Photos").is_dir()
    assert (str(env["homes"] / "ana" / "Photos"), 1030, 100) in no_chown


def test_login_without_home_folder_creates_nothing(client, dsm, env):
    import shutil

    from tests.test_auth import login

    shutil.rmtree(env["homes"] / "ana")
    assert login(client).status_code == 200
    assert not (env["homes"] / "ana").exists()


def test_unexpected_error_is_logged_and_json(env, monkeypatch, dsm):
    from fastapi.testclient import TestClient

    from poze import users
    from poze.app import create_app

    def boom(_user):
        raise PermissionError("nu am voie")

    monkeypatch.setattr(users, "ensure_photos", boom)
    c = TestClient(create_app(start_indexer=False), raise_server_exceptions=False)
    r = c.post("/api/login", json={"user": "ana", "password": "pw", "device": "t"})
    assert r.status_code == 500 and r.json()["error"].startswith("Eroare pe server")
    log = (env["data"] / "erori.log").read_text()
    assert "POST /api/login" in log and "PermissionError: nu am voie" in log


def test_browser_can_download_the_apk(web, dsm, env):
    # linkul „Aplicația Android” din meniul contului: o simplă descărcare cu cookie-ul, fără antetul CSRF
    apk = env["data"] / "apk"
    apk.mkdir(parents=True)
    (apk / "latest.json").write_text('{"version_code": 8, "version_name": "0.5.2"}')
    (apk / "amintiri.apk").write_bytes(b"PK\x03\x04apk")
    web_login(web)
    assert web.get("/api/app/latest").json()["url"] == "/api/app/apk"
    r = web.get("/api/app/apk")
    assert r.status_code == 200 and r.content == b"PK\x03\x04apk"
    assert "amintiri.apk" in r.headers["content-disposition"]


def test_web_files_are_revalidated(web):
    # altfel Cloudflare pune max-age=14400 și o versiune nouă nu se vede ore întregi
    for path in ("/", "/app.js", "/style.css"):
        assert web.get(path).headers["cache-control"] == "no-cache"
    assert web.get("/app.js", headers={"If-None-Match": web.get("/app.js").headers["etag"]}).status_code == 304


def test_index_points_to_versioned_assets(web):
    # Cloudflare ține .js/.css pe nodurile lui; adresa cu amprentă se schimbă la fiecare versiune
    html = web.get("/").text
    assert 'src="app.js?v=' in html and 'href="style.css?v=' in html
    assert web.get("/index.html").text == html
    assert web.get("/app.js?v=orice").status_code == 200


def test_stats_counts_own_live_assets(web, dsm, env):
    from poze import db as dbm
    conn = dbm.connect(env["data"])
    rows = [("ana", "a.jpg", "s1", 100, "photo", None), ("ana", "b.mp4", "s2", 300, "video", None),
            ("ana", "c.jpg", "s3", 50, "photo", "2026-10-01 10:00:00"), ("bogdan", "d.jpg", "s4", 999, "photo", None)]
    conn.executemany("INSERT INTO assets(user, relpath, sha256, size, kind, deleted_at, taken_at) "
                     "VALUES(?,?,?,?,?,?,'2026-01-01 10:00:00')", rows)
    conn.commit()
    web_login(web)
    r = web.get("/api/stats").json()
    assert (r["photos"], r["videos"], r["bytes"]) == (1, 1, 400)
    assert r["free_bytes"] > 0


def test_timeline_filters_by_kind(web, dsm, env):
    from poze import db as dbm
    conn = dbm.connect(env["data"])
    conn.executemany("INSERT INTO assets(user, relpath, sha256, size, kind, taken_at) VALUES('ana',?,?,1,?,?)",
                     [("a.jpg", "s1", "photo", "2026-01-02 10:00:00"), ("b.mp4", "s2", "video", "2026-01-01 10:00:00")])
    conn.commit()
    web_login(web)
    assert [i["kind"] for i in web.get("/api/assets?kind=video").json()["items"]] == ["video"]
    assert [i["kind"] for i in web.get("/api/assets?kind=photo").json()["items"]] == ["photo"]
    assert len(web.get("/api/assets").json()["items"]) == 2
    assert web.get("/api/assets?kind=altceva").status_code == 422


def test_errors_follow_accept_language(web):
    bad = {"user": 5}  # tip greșit: eroare de validare
    r = web.post("/api/web/login", json=bad, headers={"Accept-Language": "en-GB,en;q=0.9"})
    assert r.json()["error"] == "Invalid request."
    r = web.post("/api/web/login", json=bad, headers={"Accept-Language": "ro-RO,ro;q=0.9"})
    assert r.json()["error"] == "Cerere invalidă."
    assert web.post("/api/web/login", json=bad).json()["error"] == "Cerere invalidă."


def test_every_english_message_is_used():
    """Un mesaj schimbat în cod, dar nu și aici, ar rămâne netradus: dicționarul trebuie să se potrivească."""
    import pathlib
    from poze.i18n import EN
    src = "".join(p.read_text() for p in pathlib.Path("poze").glob("*.py") if p.name != "i18n.py")
    flat = src.replace('"\n', "").replace('                                     "', "").replace('           "', "")
    missing = [ro for ro in EN if ro not in flat and ro.split(" În DSM")[0] not in src]
    assert not missing, missing


def test_place_names_follow_language():
    from poze.geo import english
    assert english("Grecia") == "Greece"
    assert english("Statele Unite") == "United States"
    assert english("Roma") == "Rome"
    assert english("Brașov") == "Brașov"
