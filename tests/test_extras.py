"""Favorite, detalii, căutare, coș, link public de album."""
import hashlib

import pytest
from PIL import Image

from poze import db, indexer
from poze.users import photos_root
from tests.fixtures import make_jpeg
from tests.test_albums import headers, photos


def ids_by_sha(client, h):
    return {i["sha256"]: i["id"] for i in client.get("/api/assets", headers=h).json()["items"]}


# ---------- favorite ----------
def test_favorite_toggle_and_list(client, env):
    shas = photos(env)
    h = headers(env)
    assert client.put(f"/api/favorites/{shas[0]}", headers=h).status_code == 204
    assert client.put(f"/api/favorites/{shas[0]}", headers=h).status_code == 204  # idempotent
    assert client.put(f"/api/favorites/{shas[2]}", headers=h).status_code == 204
    assert sorted(client.get("/api/favorites", headers=h).json()["sha256"]) == sorted([shas[0], shas[2]])
    items = client.get("/api/favorites/assets", headers=h).json()["items"]
    assert [i["sha256"] for i in items] == [shas[2], shas[0]]
    assert client.delete(f"/api/favorites/{shas[0]}", headers=h).status_code == 204
    assert client.get("/api/favorites", headers=h).json()["sha256"] == [shas[2]]


def test_cannot_favorite_someone_elses_photo(client, env):
    theirs = photos(env, "bogdan", n=1)
    r = client.put(f"/api/favorites/{theirs[0]}", headers=headers(env))
    assert r.status_code == 404


def test_deleted_photo_leaves_favorites(client, env, no_chown):
    shas = photos(env)
    h = headers(env)
    client.put(f"/api/favorites/{shas[1]}", headers=h)
    client.delete(f"/api/assets/{ids_by_sha(client, h)[shas[1]]}", headers=h)
    assert client.get("/api/favorites", headers=h).json()["sha256"] == []


# ---------- detalii ----------
def test_info_has_file_camera_place_albums_and_favorite(client, env):
    p = photos_root("ana") / "2024" / "IMG_1.jpg"
    p.parent.mkdir()
    make_jpeg(p, "2024:05:01 10:00:00", size=(80, 60), gps=(44.4268, 26.1025))
    with Image.open(p) as im:  # adăugăm producătorul și modelul
        ex = im.getexif()
        ex[0x010F], ex[0x0110] = "samsung", "SM-S918B"
        im.save(p, exif=ex)
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "ana")
    from poze import geo
    geo.backfill(conn, "ana")
    h = headers(env)
    a = client.get("/api/assets", headers=h).json()["items"][0]
    client.put(f"/api/favorites/{a['sha256']}", headers=h)
    client.post("/api/albums", json={"name": "Vara", "sha256": [a["sha256"]]}, headers=h)
    info = client.get(f"/api/assets/{a['id']}/info", headers=h).json()
    assert info["filename"] == "IMG_1.jpg" and info["folder"] == "2024"
    assert info["size"] == p.stat().st_size and (info["width"], info["height"]) == (80, 60)
    assert info["camera"] == "Samsung SM-S918B"
    assert info["place"]["name"] == "București" and info["lat"] == pytest.approx(44.4268, abs=1e-3)
    assert info["favorite"] is True
    assert [x["name"] for x in info["albums"]] == ["Vara"]


def test_info_of_someone_elses_photo_is_404(client, env):
    photos(env, "bogdan", n=1)
    their_id = client.get("/api/assets", headers=headers(env, "bogdan")).json()["items"][0]["id"]
    assert client.get(f"/api/assets/{their_id}/info", headers=headers(env)).status_code == 404


# ---------- căutare ----------
@pytest.fixture
def library(env):
    """Poze în ani/luni diferite, unele cu loc, una într-un album."""
    root = photos_root("ana")
    spots = [("r1", "2024:08:10 10:00:00", (41.9028, 12.4964)),   # Roma
             ("r2", "2023:08:11 10:00:00", (41.9028, 12.4964)),   # Roma
             ("b1", "2024:08:12 10:00:00", (44.4268, 26.1025)),   # București
             ("x1", "2024:01:05 10:00:00", None),
             ("x2", "2023:12:20 10:00:00", None)]
    for i, (name, when, gps) in enumerate(spots):
        make_jpeg(root / f"{name}.jpg", when, size=(50 + i, 40), gps=gps)
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "ana")
    from poze import geo
    geo.backfill(conn, "ana")
    return {n: hashlib.sha256((root / f"{n}.jpg").read_bytes()).hexdigest() for n, _, _ in spots}


def search(client, env, q):
    r = client.get("/api/search", params={"q": q}, headers=headers(env))
    assert r.status_code == 200, r.text
    return r.json()


def names(result, lib):
    back = {v: k for k, v in lib.items()}
    return sorted(back[i["sha256"]] for i in result["items"])


def test_search_by_place_without_diacritics(client, env, library):
    assert names(search(client, env, "roma"), library) == ["r1", "r2"]
    assert names(search(client, env, "bucuresti"), library) == ["b1"]
    assert names(search(client, env, "Italia"), library) == ["r1", "r2"]


def test_search_by_month_year_and_season(client, env, library):
    assert names(search(client, env, "august 2024"), library) == ["b1", "r1"]
    assert names(search(client, env, "2023"), library) == ["r2", "x2"]
    assert names(search(client, env, "aug"), library) == ["b1", "r1", "r2"]
    assert names(search(client, env, "iarna"), library) == ["x1", "x2"]
    assert names(search(client, env, "vara 2023"), library) == ["r2"]


def test_search_combines_place_and_date(client, env, library):
    r = search(client, env, "Roma 2024")
    assert names(r, library) == ["r1"]
    assert r["label"] == "Roma · 2024"


def test_search_by_album_name(client, env, library):
    client.post("/api/albums", json={"name": "Nunta Ioanei", "sha256": [library["x1"]]}, headers=headers(env))
    assert names(search(client, env, "nunta"), library) == ["x1"]


def test_search_unknown_text_finds_nothing(client, env, library):
    assert search(client, env, "zanzibar")["items"] == []


def test_search_empty_query_is_rejected(client, env):
    assert client.get("/api/search", params={"q": "  "}, headers=headers(env)).status_code == 422


def test_search_suggestions(client, env, library):
    s = client.get("/api/search/suggestions", headers=headers(env)).json()
    assert [p["name"] for p in s["places"]][:1] == ["Roma"]  # cele mai multe poze primele
    assert s["years"] == [2024, 2023]


# ---------- coș ----------
def test_trash_list_restore_and_purge(client, env, no_chown):
    shas = photos(env)
    h = headers(env)
    ids = ids_by_sha(client, h)
    client.delete(f"/api/assets/{ids[shas[0]]}", headers=h)
    client.delete(f"/api/assets/{ids[shas[1]]}", headers=h)
    t = client.get("/api/trash", headers=h).json()["items"]
    assert sorted(i["sha256"] for i in t) == sorted(shas[:2])
    assert all(i["days_left"] == 30 for i in t)
    assert client.get(f"/api/trash/{t[0]['id']}/thumb", headers=h).status_code == 200

    r = client.post("/api/trash/restore", json={"ids": [ids[shas[0]]]}, headers=h)
    assert r.json() == {"restored": 1}
    assert shas[0] in ids_by_sha(client, h)
    assert (photos_root("ana") / "ana0.jpg").is_file()  # înapoi la locul lui

    r = client.request("DELETE", "/api/trash", json={"ids": [ids[shas[1]]]}, headers=h)
    assert r.json() == {"deleted": 1}
    assert client.get("/api/trash", headers=h).json()["items"] == []
    assert not list((photos_root("ana") / ".cos").rglob("*.jpg"))


def test_restore_to_taken_name_gets_new_name(client, env, no_chown):
    shas = photos(env, n=1)
    h = headers(env)
    aid = ids_by_sha(client, h)[shas[0]]
    client.delete(f"/api/assets/{aid}", headers=h)
    make_jpeg(photos_root("ana") / "ana0.jpg", "2020:01:01 10:00:00", size=(10, 10))  # alt fișier pe același nume
    client.post("/api/trash/restore", json={"ids": [aid]}, headers=h)
    assert (photos_root("ana") / "ana0_2.jpg").is_file()
    restored = client.get(f"/api/assets/{aid}/info", headers=h).json()
    assert restored["filename"] == "ana0_2.jpg"


def test_trash_is_per_user(client, env, no_chown):
    shas = photos(env, "bogdan", n=1)
    hb = headers(env, "bogdan")
    bid = ids_by_sha(client, hb)[shas[0]]
    client.delete(f"/api/assets/{bid}", headers=hb)
    h = headers(env)
    assert client.get("/api/trash", headers=h).json()["items"] == []
    assert client.post("/api/trash/restore", json={"ids": [bid]}, headers=h).json() == {"restored": 0}
    assert client.get(f"/api/trash/{bid}/thumb", headers=h).status_code == 404


# ---------- link public de album ----------
def album_with_link(client, env):
    shas = photos(env)
    h = headers(env)
    aid = client.post("/api/albums", json={"name": "Vara", "sha256": shas[:2]}, headers=h).json()["album"]["id"]
    r = client.post(f"/api/albums/{aid}/link", headers=h)
    assert r.status_code == 200
    return shas, h, aid, r.json()["token"]


def test_link_is_stable_and_listed(client, env):
    shas, h, aid, token = album_with_link(client, env)
    assert len(token) >= 40
    assert client.post(f"/api/albums/{aid}/link", headers=h).json()["token"] == token
    assert client.get("/api/albums", headers=h).json()["albums"][0]["link"] == token


def test_public_album_without_login(client, env):
    shas, h, aid, token = album_with_link(client, env)
    info = client.get(f"/api/public/{token}").json()
    assert info == {"name": "Vara", "count": 2}
    items = client.get(f"/api/public/{token}/assets").json()["items"]
    assert sorted(i["sha256"] for i in items) == sorted(shas[:2])
    assert client.get(f"/api/public/{token}/thumb/{items[0]['id']}").status_code == 200
    assert client.get(f"/api/public/{token}/original/{items[0]['id']}").status_code == 200
    page = client.get(f"/a/{token}")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    assert page.headers["x-robots-tag"] == "noindex, nofollow"


def test_public_link_cannot_reach_photos_outside_album(client, env):
    shas, h, aid, token = album_with_link(client, env)
    outside = ids_by_sha(client, h)[shas[2]]
    assert client.get(f"/api/public/{token}/thumb/{outside}").status_code == 404
    assert client.get(f"/api/public/{token}/original/{outside}").status_code == 404


def test_stopping_link_and_bad_tokens(client, env):
    shas, h, aid, token = album_with_link(client, env)
    assert client.delete(f"/api/albums/{aid}/link", headers=h).status_code == 204
    assert client.get(f"/api/public/{token}").status_code == 404
    assert client.get("/api/public/x" * 3).status_code == 404
    assert client.get("/a/nu-exista").status_code == 404
    assert client.get("/api/albums", headers=h).json()["albums"][0]["link"] is None


def test_deleting_album_kills_link(client, env):
    shas, h, aid, token = album_with_link(client, env)
    client.delete(f"/api/albums/{aid}", headers=h)
    assert client.get(f"/api/public/{token}").status_code == 404


def test_only_owner_can_make_link(client, env):
    photos(env)
    aid = client.post("/api/albums", json={"name": "A"}, headers=headers(env)).json()["album"]["id"]
    assert client.post(f"/api/albums/{aid}/link", headers=headers(env, "bogdan")).status_code == 404
