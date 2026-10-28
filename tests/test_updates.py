"""„E o versiune nouă”: doar administratorii o văd, cu fișierul potrivit NAS-ului."""
import httpx
import pytest

from poze import updates

RELEASES = [
    {"tag_name": "app-0.12.2", "assets": [{"name": "amintiri-0.12.2-38.apk", "browser_download_url": "https://github.com/a.apk"}]},
    {"tag_name": "v0.6.0", "prerelease": True, "html_url": "https://github.com/r/v0.6.0", "assets": []},
    {"tag_name": "v0.5.10", "html_url": "https://github.com/r/v0.5.10", "assets": [
        {"name": "amintiri-0.5.10-x86_64.spk", "browser_download_url": "https://github.com/d/x86.spk"},
        {"name": "amintiri-0.5.10-armv8.spk", "browser_download_url": "https://github.com/d/arm.spk"}]},
    {"tag_name": "v0.5.9", "html_url": "https://github.com/r/v0.5.9", "assets": []},
]


@pytest.fixture
def github(env, monkeypatch, tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=RELEASES)

    monkeypatch.setattr(updates, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(updates, "_cache", {"at": None, "latest": None})
    monkeypatch.setattr(updates, "__version__", "0.5.2")
    group = tmp_path / "group"
    group.write_text("users:x:100:\nadministrators:x:101:admin,ana,certadmin\n")
    monkeypatch.setenv("POZE_GROUP_FILE", str(group))
    monkeypatch.setattr(updates.platform, "machine", lambda: "x86_64")
    return calls


def test_admin_on_package_gets_the_spk_for_its_cpu(github, monkeypatch):
    monkeypatch.setenv("POZE_INSTALL", "spk")
    # 0.5.10 > 0.5.9 > 0.5.2 ca numere, nu ca text; versiunile de test (prerelease) și APK-urile nu contează
    assert updates.check("ana") == {"current": "0.5.2", "admin": True, "available": True, "version": "0.5.10",
                                    "how": "spk", "url": "https://github.com/d/x86.spk"}
    monkeypatch.setattr(updates.platform, "machine", lambda: "aarch64")
    assert updates.check("ana")["url"] == "https://github.com/d/arm.spk"
    assert len(github) == 1  # ține minte răspunsul: GitHub e întrebat o dată la câteva ore


def test_container_gets_the_release_page(github, monkeypatch):
    monkeypatch.delenv("POZE_INSTALL", raising=False)
    assert updates.check("ana") == {"current": "0.5.2", "admin": True, "available": True, "version": "0.5.10",
                                         "how": "docker", "url": "https://github.com/r/v0.5.10"}


def test_not_admin_sees_nothing_and_github_is_not_asked(github):
    assert updates.check("dana") == {"current": "0.5.2", "admin": False, "available": False}
    assert github == []


def test_up_to_date(github, monkeypatch):
    monkeypatch.setattr(updates, "__version__", "0.5.10")
    assert updates.check("ana") == {"current": "0.5.10", "admin": True, "available": False}


def test_github_down_is_quiet(github, monkeypatch):
    monkeypatch.setattr(updates, "_transport", httpx.MockTransport(lambda r: httpx.Response(503)))
    assert updates.check("ana")["available"] is False


def test_route(client, env, github):
    from tests.test_library import headers

    r = client.get("/api/update", headers=headers(env))
    assert r.status_code == 200 and r.json()["available"] is True
    assert client.get("/api/update").status_code == 401
