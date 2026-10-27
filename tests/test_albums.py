import hashlib

from poze import auth, db, indexer
from poze.users import photos_root
from tests.fixtures import make_jpeg


def headers(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        return {"Authorization": f"Bearer {auth.issue_token(conn, user, 'tel')}"}
    finally:
        conn.close()


def photos(env, user="ana", n=3):
    shas = []
    for i in range(n):
        p = make_jpeg(photos_root(user) / f"{user}{i}.jpg", f"2024:05:0{i + 1} 10:00:00", size=(60 + i, 40 + len(user)))
        shas.append(hashlib.sha256(p.read_bytes()).hexdigest())
    indexer.scan_user(db.connect(env["data"]), user)
    return shas


def test_create_list_and_assets(client, env):
    shas = photos(env)
    h = headers(env)
    r = client.post("/api/albums", json={"name": "  Vacanța 2024 ", "sha256": shas[:2]}, headers=h)
    assert r.status_code == 200
    album = r.json()["album"]
    assert album["name"] == "Vacanța 2024" and album["count"] == 2
    listed = client.get("/api/albums", headers=h).json()["albums"]
    assert [(a["name"], a["count"]) for a in listed] == [("Vacanța 2024", 2)]
    items = client.get(f"/api/albums/{album['id']}/assets", headers=h).json()["items"]
    # cea mai nouă prima; coperta e cea mai nouă poză
    assert [i["sha256"] for i in items] == [shas[1], shas[0]]
    assert listed[0]["cover_id"] == items[0]["id"]


def test_add_is_idempotent_and_remove(client, env):
    shas = photos(env)
    h = headers(env)
    aid = client.post("/api/albums", json={"name": "A", "sha256": [shas[0]]}, headers=h).json()["album"]["id"]
    r = client.post(f"/api/albums/{aid}/items", json={"sha256": shas}, headers=h)
    assert r.json()["album"]["count"] == 3
    client.post(f"/api/albums/{aid}/items", json={"sha256": shas}, headers=h)
    r = client.request("DELETE", f"/api/albums/{aid}/items", json={"sha256": [shas[0]]}, headers=h)
    assert r.json()["album"]["count"] == 2


def test_rename_and_delete_keep_photos(client, env):
    shas = photos(env)
    h = headers(env)
    aid = client.post("/api/albums", json={"name": "A", "sha256": shas}, headers=h).json()["album"]["id"]
    assert client.patch(f"/api/albums/{aid}", json={"name": "B"}, headers=h).json()["album"]["name"] == "B"
    assert client.delete(f"/api/albums/{aid}", headers=h).status_code == 200
    assert client.get("/api/albums", headers=h).json()["albums"] == []
    assert len(client.get("/api/assets", headers=h).json()["items"]) == 3


def test_others_cannot_touch(client, env):
    shas = photos(env)
    aid = client.post("/api/albums", json={"name": "A", "sha256": shas}, headers=headers(env)).json()["album"]["id"]
    hb = headers(env, "bogdan")
    assert client.get(f"/api/albums/{aid}/assets", headers=hb).status_code == 404
    assert client.patch(f"/api/albums/{aid}", json={"name": "X"}, headers=hb).status_code == 404
    assert client.delete(f"/api/albums/{aid}", headers=hb).status_code == 404
    assert client.post(f"/api/albums/{aid}/items", json={"sha256": shas}, headers=hb).status_code == 404
    assert client.get("/api/albums", headers=hb).json()["albums"] == []


def test_foreign_and_unknown_shas_ignored(client, env):
    mine = photos(env)
    theirs = photos(env, "bogdan", n=1)
    h = headers(env)
    r = client.post("/api/albums", json={"name": "A", "sha256": [mine[0], theirs[0], "0" * 64]}, headers=h)
    assert r.json()["album"]["count"] == 1


def test_name_validation(client, env):
    h = headers(env)
    assert client.post("/api/albums", json={"name": "   ", "sha256": []}, headers=h).status_code == 422
    assert client.post("/api/albums", json={"name": "x" * 101, "sha256": []}, headers=h).status_code == 422
    assert client.post("/api/albums", json={"name": "Gol", "sha256": []}, headers=h).json()["album"]["count"] == 0


def test_deleted_photo_leaves_album_count(client, env, no_chown):
    shas = photos(env)
    h = headers(env)
    aid = client.post("/api/albums", json={"name": "A", "sha256": shas}, headers=h).json()["album"]["id"]
    first = client.get(f"/api/albums/{aid}/assets", headers=h).json()["items"][0]["id"]
    assert client.delete(f"/api/assets/{first}", headers=h).status_code == 204
    assert client.get("/api/albums", headers=h).json()["albums"][0]["count"] == 2
    assert len(client.get(f"/api/albums/{aid}/assets", headers=h).json()["items"]) == 2
