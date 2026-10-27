import shutil
from datetime import datetime, timedelta

from poze import auth, db, indexer
from poze.config import get_settings
from poze.metadata import TZ
from poze.trash import move_to_trash, purge_trash
from poze.users import photos_root
from tests.fixtures import make_jpeg


def setup_two_copies(env):
    a = photos_root("ana") / "MobileBackup/Honor 90/a.jpg"
    b = photos_root("ana") / "Vechi/a.jpg"
    for p in (a, b):
        p.parent.mkdir(parents=True)
    make_jpeg(a, "2024:05:01 10:00:00")
    shutil.copy(a, b)
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "ana")
    return conn, a, b


def test_delete_moves_all_copies(client, env, no_chown):
    conn, a, b = setup_two_copies(env)
    h = {"Authorization": f"Bearer {auth.issue_token(conn, 'ana', 't')}"}
    aid = client.get("/api/assets", headers=h).json()["items"][0]["id"]
    assert client.delete(f"/api/assets/{aid}", headers=h).status_code == 204
    day = datetime.now(TZ).strftime("%Y-%m-%d")
    cos = photos_root("ana") / ".cos" / day
    assert (cos / "MobileBackup/Honor 90/a.jpg").is_file() and (cos / "Vechi/a.jpg").is_file()
    assert not a.exists() and not b.exists()
    assert client.get("/api/assets", headers=h).json()["items"] == []
    assert client.delete(f"/api/assets/{aid}", headers=h).status_code == 404


def test_delete_collision_in_cos(env, no_chown):
    conn, a, _ = setup_two_copies(env)
    day = datetime.now(TZ).strftime("%Y-%m-%d")
    taken = photos_root("ana") / ".cos" / day / "MobileBackup/Honor 90/a.jpg"
    taken.parent.mkdir(parents=True)
    taken.write_bytes(b"alt")
    move_to_trash(conn, "ana", conn.execute("select id from assets").fetchone()[0])
    assert taken.read_bytes() == b"alt"
    assert (taken.parent / "a_2.jpg").is_file()


def test_delete_not_reindexed(env, no_chown):
    conn, _, _ = setup_two_copies(env)
    move_to_trash(conn, "ana", conn.execute("select id from assets").fetchone()[0])
    indexer.scan_user(conn, "ana")
    rows = conn.execute("select deleted_at from assets").fetchall()
    assert len(rows) == 2 and all(r[0] for r in rows)


def test_purge_after_30_days(env, no_chown):
    conn, _, _ = setup_two_copies(env)
    move_to_trash(conn, "ana", conn.execute("select id from assets").fetchone()[0])
    cos = photos_root("ana") / ".cos"
    now = datetime.now(TZ)
    assert purge_trash(conn, get_settings(), now + timedelta(days=29)) == 0
    assert len([p for p in cos.rglob("*.jpg")]) == 2
    assert purge_trash(conn, get_settings(), now + timedelta(days=31)) == 2
    assert list(cos.rglob("*.jpg")) == []
    assert conn.execute("select count(*) from trash").fetchone()[0] == 0


def test_check_ignores_deleted(client, env, no_chown):
    conn, a, _ = setup_two_copies(env)
    sha = conn.execute("select sha256 from assets").fetchone()[0]
    h = {"Authorization": f"Bearer {auth.issue_token(conn, 'ana', 't')}"}
    assert client.post("/api/check", json={"sha256": [sha]}, headers=h).json() == {"present": [sha]}
    move_to_trash(conn, "ana", conn.execute("select id from assets").fetchone()[0])
    assert client.post("/api/check", json={"sha256": [sha]}, headers=h).json() == {"present": []}


def test_other_users_delete_404(client, env):
    make_jpeg(photos_root("bogdan") / "b.jpg", "2024:05:01 10:00:00")
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "bogdan")
    bid = conn.execute("select id from assets").fetchone()[0]
    h = {"Authorization": f"Bearer {auth.issue_token(conn, 'ana', 't')}"}
    assert client.delete(f"/api/assets/{bid}", headers=h).status_code == 404
    assert (photos_root("bogdan") / "b.jpg").is_file()
