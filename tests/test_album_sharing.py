"""Albume comune: proprietarul le împarte cu alte conturi; membrii văd și adaugă pozele lor."""
from tests.test_albums import headers, photos


def shared(client, env, n_ana=2):
    """Ana face un album cu pozele ei și îl împarte cu Bogdan (care s-a logat deja o dată)."""
    ha, hb = headers(env), headers(env, "bogdan")
    shas = photos(env, n=n_ana)
    aid = client.post("/api/albums", json={"name": "Familie", "sha256": shas}, headers=ha).json()["album"]["id"]
    r = client.post(f"/api/albums/{aid}/members", json={"user": "bogdan"}, headers=ha)
    assert r.status_code == 200
    return aid, ha, hb, shas


def test_people_lists_other_accounts_that_signed_in(client, env):
    ha = headers(env)
    headers(env, "bogdan")
    assert client.get("/api/people", headers=ha).json() == {"people": ["bogdan"]}


def test_member_sees_album_and_photos(client, env):
    aid, ha, hb, shas = shared(client, env)
    albums = client.get("/api/albums", headers=hb).json()["albums"]
    assert [(a["id"], a["owner"], a["mine"], a["count"]) for a in albums] == [(aid, "ana", False, 2)]
    owner_view = client.get("/api/albums", headers=ha).json()["albums"][0]
    assert owner_view["mine"] and owner_view["members"] == ["bogdan"]
    items = client.get(f"/api/albums/{aid}/assets", headers=hb).json()["items"]
    assert {i["sha256"] for i in items} == set(shas)
    # miniatura și originalul pozei Anei, cerute de Bogdan prin album
    assert client.get(f"/api/assets/{items[0]['id']}/thumb", headers=hb).status_code == 200
    assert client.get(f"/api/assets/{items[0]['id']}/original", headers=hb).status_code == 200


def test_member_adds_own_photos_everyone_sees_them(client, env):
    aid, ha, hb, shas = shared(client, env)
    mine = photos(env, "bogdan", n=1)
    r = client.post(f"/api/albums/{aid}/items", json={"sha256": mine}, headers=hb)
    assert r.json()["album"]["count"] == 3
    ana_sees = {i["sha256"] for i in client.get(f"/api/albums/{aid}/assets", headers=ha).json()["items"]}
    assert ana_sees == set(shas) | set(mine)
    # dar nu în cronologia Anei: pozele lui Bogdan rămân ale lui
    assert {i["sha256"] for i in client.get("/api/assets", headers=ha).json()["items"]} == set(shas)


def test_member_removes_only_own_photos(client, env):
    aid, ha, hb, shas = shared(client, env)
    mine = photos(env, "bogdan", n=1)
    client.post(f"/api/albums/{aid}/items", json={"sha256": mine}, headers=hb)
    # a ales și o poză a Anei: nu se scoate nimic și i se spune de ce
    r = client.request("DELETE", f"/api/albums/{aid}/items", json={"sha256": [shas[0], mine[0]]}, headers=hb)
    assert r.status_code == 403
    r = client.request("DELETE", f"/api/albums/{aid}/items", json={"sha256": [mine[0]]}, headers=hb)
    assert r.json()["album"]["count"] == 2
    # proprietarul poate scoate orice
    r = client.request("DELETE", f"/api/albums/{aid}/items", json={"sha256": [shas[0]]}, headers=ha)
    assert r.json()["album"]["count"] == 1


def test_member_cannot_manage(client, env):
    aid, ha, hb, _ = shared(client, env)
    assert client.patch(f"/api/albums/{aid}", json={"name": "X"}, headers=hb).status_code == 404
    assert client.delete(f"/api/albums/{aid}", headers=hb).status_code == 404
    assert client.post(f"/api/albums/{aid}/link", headers=hb).status_code == 404
    assert client.post(f"/api/albums/{aid}/members", json={"user": "ana"}, headers=hb).status_code == 404


def test_member_leaves_and_owner_removes(client, env):
    aid, ha, hb, _ = shared(client, env)
    assert client.delete(f"/api/albums/{aid}/members/bogdan", headers=hb).status_code == 200
    assert client.get("/api/albums", headers=hb).json()["albums"] == []
    assert client.get(f"/api/albums/{aid}/assets", headers=hb).status_code == 404
    client.post(f"/api/albums/{aid}/members", json={"user": "bogdan"}, headers=ha)
    assert client.delete(f"/api/albums/{aid}/members/bogdan", headers=ha).status_code == 200
    assert client.get(f"/api/albums/{aid}/assets", headers=hb).status_code == 404


def test_after_leaving_photos_are_private_again(client, env):
    aid, ha, hb, _ = shared(client, env)
    item = client.get(f"/api/albums/{aid}/assets", headers=hb).json()["items"][0]
    client.delete(f"/api/albums/{aid}/members/bogdan", headers=ha)
    assert client.get(f"/api/assets/{item['id']}/thumb", headers=hb).status_code == 404
    assert client.get(f"/api/assets/{item['id']}/original", headers=hb).status_code == 404


def test_cannot_add_unknown_or_self(client, env):
    ha = headers(env)
    aid = client.post("/api/albums", json={"name": "A"}, headers=ha).json()["album"]["id"]
    assert client.post(f"/api/albums/{aid}/members", json={"user": "nimeni"}, headers=ha).status_code == 422
    assert client.post(f"/api/albums/{aid}/members", json={"user": "ana"}, headers=ha).status_code == 422


def test_stranger_sees_nothing(client, env):
    aid, ha, hb, _ = shared(client, env)
    item = client.get(f"/api/albums/{aid}/assets", headers=ha).json()["items"][0]
    # al treilea cont, care n-a fost invitat
    (env["homes"] / "cora" / "Photos").mkdir(parents=True)
    env["passwd"].write_text(env["passwd"].read_text() + "cora:x:1032:100::/x:/sbin/nologin\n")
    hc = headers(env, "cora")
    assert client.get(f"/api/albums/{aid}/assets", headers=hc).status_code == 404
    assert client.get(f"/api/assets/{item['id']}/thumb", headers=hc).status_code == 404


def test_public_link_shows_everyones_photos(client, env):
    aid, ha, hb, shas = shared(client, env)
    mine = photos(env, "bogdan", n=1)
    client.post(f"/api/albums/{aid}/items", json={"sha256": mine}, headers=hb)
    token = client.post(f"/api/albums/{aid}/link", headers=ha).json()["token"]
    items = client.get(f"/api/public/{token}/assets").json()["items"]
    assert {i["sha256"] for i in items} == set(shas) | set(mine)
    bogdans = next(i for i in items if i["sha256"] == mine[0])
    assert client.get(f"/api/public/{token}/thumb/{bogdans['id']}").status_code == 200


def test_old_database_keeps_albums_of_their_owner(env):
    """Baza de dinainte de albumele comune: pozele din album devin ale proprietarului albumului."""
    import sqlite3

    from poze import db
    env["data"].mkdir(parents=True, exist_ok=True)
    old = sqlite3.connect(env["data"] / "poze.db")
    old.executescript("""
        CREATE TABLE albums(id INTEGER PRIMARY KEY, user TEXT, name TEXT, created_at TEXT);
        CREATE TABLE album_items(album_id INT, sha256 TEXT, added_at TEXT, PRIMARY KEY(album_id, sha256));
        INSERT INTO albums VALUES(1, 'ana', 'Vechi', '2026-01-01 10:00:00');
        INSERT INTO album_items VALUES(1, 'abc', '2026-01-01 10:00:00');
    """)
    old.commit()
    old.close()
    conn = db.connect(env["data"])
    assert conn.execute("SELECT user FROM album_items").fetchone()[0] == "ana"


def test_same_photo_from_two_people_stays_when_one_leaves(client, env):
    """O poză pe care o au amândoi (trimisă pe WhatsApp) rămâne în album cât o are încă cineva acolo."""
    aid, ha, hb, shas = shared(client, env, n_ana=0)
    common = photos(env, "bogdan", n=1)
    # aceeași poză și la Ana: aceeași amprentă
    from poze import db, indexer
    from poze.users import photos_root
    (photos_root("ana") / "copie.jpg").write_bytes((photos_root("bogdan") / "bogdan0.jpg").read_bytes())
    indexer.scan_user(db.connect(env["data"]), "ana")
    client.post(f"/api/albums/{aid}/items", json={"sha256": common}, headers=hb)
    client.post(f"/api/albums/{aid}/items", json={"sha256": common}, headers=ha)
    client.delete(f"/api/albums/{aid}/members/bogdan", headers=hb)
    items = client.get(f"/api/albums/{aid}/assets", headers=ha).json()["items"]
    assert [i["sha256"] for i in items] == common


def test_owner_cannot_remove_himself(client, env):
    aid, ha, hb, shas = shared(client, env)
    assert client.delete(f"/api/albums/{aid}/members/ana", headers=ha).status_code == 422
    assert client.get("/api/albums", headers=ha).json()["albums"][0]["count"] == 2


def test_member_told_when_removing_others_photos(client, env):
    aid, ha, hb, shas = shared(client, env)
    r = client.request("DELETE", f"/api/albums/{aid}/items", json={"sha256": [shas[0]]}, headers=hb)
    assert r.status_code == 403
    assert "puse de tine" in r.json()["error"]
    assert client.get("/api/albums", headers=ha).json()["albums"][0]["count"] == 2
