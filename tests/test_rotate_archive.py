"""Rotirea (fără să atingă originalul) și arhiva (ascunde din cronologie și din amintiri)."""
import io

from PIL import Image

from poze.users import photos_root
from tests.test_albums import headers, photos


def _one(client, h):
    return client.get("/api/assets", headers=h).json()["items"]


def test_rotate_turns_thumb_and_swaps_size(client, env):
    shas = photos(env, n=1)  # 60x43
    h = headers(env)
    a = _one(client, h)[0]
    assert (a["width"], a["height"], a["rotation"]) == (60, 43, 0)
    before = (photos_root("ana") / "ana0.jpg").read_bytes()
    r = client.post(f"/api/assets/{a['id']}/rotate", json={"degrees": 90}, headers=h)
    assert r.status_code == 200
    assert (r.json()["width"], r.json()["height"], r.json()["rotation"]) == (43, 60, 90)
    thumb = Image.open(io.BytesIO(client.get(f"/api/assets/{a['id']}/thumb", headers=h).content))
    assert thumb.size == (43, 60)
    # originalul de pe NAS rămâne neatins
    assert (photos_root("ana") / "ana0.jpg").read_bytes() == before
    # încă trei sferturi: se întoarce de unde a plecat
    client.post(f"/api/assets/{a['id']}/rotate", json={"degrees": -90}, headers=h)
    assert _one(client, h)[0]["rotation"] == 0
    assert Image.open(io.BytesIO(client.get(f"/api/assets/{a['id']}/thumb", headers=h).content)).size == (60, 43)
    assert shas


def test_rotate_only_own_photos_and_valid_angles(client, env):
    photos(env, n=1)
    a = _one(client, headers(env))[0]
    assert client.post(f"/api/assets/{a['id']}/rotate", json={"degrees": 45}, headers=headers(env)).status_code == 422
    assert client.post(f"/api/assets/{a['id']}/rotate", json={"degrees": 90},
                       headers=headers(env, "bogdan")).status_code == 404


def test_archive_hides_from_timeline_but_not_from_albums(client, env):
    shas = photos(env, n=3)
    h = headers(env)
    aid = client.post("/api/albums", json={"name": "A", "sha256": shas}, headers=h).json()["album"]["id"]
    assert client.post("/api/archive", json={"sha256": shas[:2]}, headers=h).status_code == 200
    assert {i["sha256"] for i in _one(client, h)} == {shas[2]}
    assert {i["sha256"] for i in client.get("/api/archive/assets", headers=h).json()["items"]} == set(shas[:2])
    assert len(client.get(f"/api/albums/{aid}/assets", headers=h).json()["items"]) == 3
    months = client.get("/api/assets/months", headers=h).json()["months"]
    assert sum(m["count"] for m in months) == 1
    # scoasă din arhivă: se întoarce în cronologie
    client.request("DELETE", "/api/archive", json={"sha256": [shas[0]]}, headers=h)
    assert len(_one(client, h)) == 2


def test_archive_is_per_account(client, env):
    shas = photos(env, n=1)
    client.post("/api/archive", json={"sha256": shas}, headers=headers(env))
    assert client.get("/api/archive/assets", headers=headers(env, "bogdan")).json()["items"] == []


def test_archived_photos_are_not_memories(client, env):
    from datetime import date

    from poze import db
    import hashlib

    from poze import indexer
    from poze.memories import on_this_day
    from tests.fixtures import make_jpeg
    # destul de mare ca să fie amintire (cele mici sunt sărite)
    p = make_jpeg(photos_root("ana") / "mare.jpg", "2024:05:01 10:00:00", size=(400, 300))
    shas = [hashlib.sha256(p.read_bytes()).hexdigest()]
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "ana")
    assert on_this_day(conn, "ana", date(2026, 5, 1))
    client.post("/api/archive", json={"sha256": shas}, headers=headers(env))
    assert on_this_day(conn, "ana", date(2026, 5, 1)) == []
