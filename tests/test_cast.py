"""Proiectarea pe televizor: adresa semnată pentru o poză, fără token, valabilă câteva ore."""
import io
import time
from urllib.parse import parse_qs, urlsplit

from PIL import Image

from poze import cast
from poze.users import photos_root
from tests.fixtures import make_jpeg
from tests.test_library import asset_id, headers, scan


def _poza(env, user="ana", size=(3000, 2000)):
    p = photos_root(user) / "cam" / "a.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    make_jpeg(p, "2024:05:01 10:00:00", size=size)
    scan(env, user)
    return asset_id(env, user)


def test_cast_link_and_media(client, env):
    aid = _poza(env)
    j = client.post(f"/api/cast/{aid}", headers=headers(env)).json()
    assert j["kind"] == "photo" and j["mime"] == "image/jpeg" and j["path"].startswith(f"api/cast/{aid}/media?")
    r = client.get("/" + j["path"])  # fără token: televizorul
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["access-control-allow-origin"] == "*"
    with Image.open(io.BytesIO(r.content)) as img:
        assert max(img.size) == cast.TV_SIZE  # micșorată pentru televizor, nu originalul


def test_cast_link_needs_token(client, env):
    aid = _poza(env)
    assert client.post(f"/api/cast/{aid}").status_code == 401


def test_cast_link_other_users_photo_refused(client, env):
    aid = _poza(env, "bogdan")
    assert client.post(f"/api/cast/{aid}", headers=headers(env)).status_code == 404


def test_cast_media_signature_bound_to_asset_user_and_time(client, env):
    aid = _poza(env)
    path = client.post(f"/api/cast/{aid}", headers=headers(env)).json()["path"]
    q = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
    base = f"/api/cast/{aid}/media"
    assert client.get(base, params={**q, "s": "0" * 64}).status_code == 404       # semnătură falsă
    assert client.get(base, params={**q, "u": "bogdan"}).status_code == 404       # alt cont
    assert client.get(base, params={**q, "e": int(q["e"]) + 1}).status_code == 404  # expirare mutată
    assert client.get(f"/api/cast/{aid + 1}/media", params=q).status_code == 404   # altă poză


def test_cast_media_expired(client, env, monkeypatch):
    aid = _poza(env)
    path = client.post(f"/api/cast/{aid}", headers=headers(env)).json()["path"]
    monkeypatch.setattr(time, "time", lambda: 9_999_999_999)
    assert client.get("/" + path).status_code == 410


def test_cast_media_deleted_photo_gone(client, env):
    aid = _poza(env)
    h = headers(env)
    path = client.post(f"/api/cast/{aid}", headers=h).json()["path"]
    assert client.delete(f"/api/assets/{aid}", headers=h).status_code == 204
    assert client.get("/" + path).status_code == 404


def test_cast_heic_goes_as_jpeg(client, env):
    from tests.fixtures import make_heic
    (photos_root("ana") / "cam").mkdir(parents=True)
    p = make_heic(photos_root("ana") / "cam" / "b.heic")
    scan(env)
    aid = asset_id(env)
    path = client.post(f"/api/cast/{aid}", headers=headers(env)).json()["path"]
    r = client.get("/" + path)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and p.suffix == ".heic"


def test_cast_video_original_with_range(client, env):
    import pytest
    from tests.fixtures import make_mp4
    (photos_root("ana") / "cam").mkdir(parents=True)
    p = make_mp4(photos_root("ana") / "cam" / "c.mp4")
    if p is None:
        pytest.skip("fără ffmpeg")
    scan(env)
    aid = asset_id(env)
    j = client.post(f"/api/cast/{aid}", headers=headers(env)).json()
    assert j["kind"] == "video" and j["mime"] == "video/mp4"
    r = client.get("/" + j["path"], headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10


def test_mov_goes_as_mp4():
    assert cast._mime("IMG_1.MOV") == "video/mp4" and cast._mime("a.webm") == "video/webm"
