import io
import shutil

import pytest
from PIL import Image

from poze import auth, db, indexer, thumbs
from poze.users import photos_root
from tests.fixtures import make_jpeg


def headers(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        return {"Authorization": f"Bearer {auth.issue_token(conn, user, 'tel')}"}
    finally:
        conn.close()


def scan(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        indexer.scan_user(conn, user)
    finally:
        conn.close()


def asset_id(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        return conn.execute("select id from assets where user=? order by id limit 1", (user,)).fetchone()[0]
    finally:
        conn.close()


def test_timeline_one_row_per_sha(client, env):
    a = photos_root("ana") / "MobileBackup/Honor 90/a.jpg"
    b = photos_root("ana") / "Honor 90_2024_Conflict/a.jpg"
    for p in (a, b):
        p.parent.mkdir(parents=True)
    make_jpeg(a, "2024:05:01 10:00:00")
    shutil.copy(a, b)
    scan(env)
    items = client.get("/api/assets", headers=headers(env)).json()["items"]
    assert len(items) == 1
    assert set(items[0]) == {"id", "sha256", "taken_at", "kind", "width", "height", "duration_ms", "source", "rotation"}


def test_timeline_order_and_cursor(client, env):
    root = photos_root("ana") / "vechi"
    root.mkdir()
    for i in range(450):
        # dimensiuni diferite → amprente diferite; câte două pe minut, ca să existe date egale
        make_jpeg(root / f"p{i:03}.jpg", f"2020:01:01 10:{i // 2 // 60:02}:{i // 2 % 60:02}",
                  size=(16 + i % 50, 16 + i // 50))
    scan(env)
    h = headers(env)
    seen, sizes, cursor = [], [], None
    while True:
        params = {"limit": 200, **({"before": cursor} if cursor else {})}
        page = client.get("/api/assets", params=params, headers=h).json()
        sizes.append(len(page["items"]))
        seen += [(it["taken_at"], it["id"]) for it in page["items"]]
        cursor = page["next"]
        if cursor is None:
            break
    assert sizes == [200, 200, 50]
    assert len(set(seen)) == 450
    assert seen == sorted(seen, reverse=True)


def _seed(conn, rows):
    for i, (taken, sha, kind) in enumerate(rows):
        conn.execute("insert into assets(user, relpath, sha256, size, mtime, taken_at, kind) values(?,?,?,?,?,?,?)",
                     ("ana", f"f{i}.jpg", sha, 1, 0, taken, kind))
    conn.commit()


def test_after_walks_up_from_a_jump(client, env):
    # după un salt din bara cu anii: în jos cu before, în sus cu after, fără găuri sau dubluri
    conn = db.connect(env["data"])
    _seed(conn, [(f"2020-{1 + i // 28:02}-{1 + i % 28:02} 10:00:00", f"{i:064x}", "photo") for i in range(300)])
    h = headers(env)
    start = "2020-06-01 00:00:00|0"
    down = client.get("/api/assets", params={"before": start, "limit": 500}, headers=h).json()["items"]
    up, cursor = [], start
    while cursor:
        page = client.get("/api/assets", params={"after": cursor, "limit": 40}, headers=h).json()
        assert [it["taken_at"] for it in page["items"]] == sorted((it["taken_at"] for it in page["items"]), reverse=True)
        up = page["items"] + up
        cursor = page["prev"]
        if cursor is None:
            break
        cursor = f"{page['items'][0]['taken_at']}|{page['items'][0]['id']}"
    everything = up + down
    assert len(everything) == 300 == len({it["id"] for it in everything})
    assert [it["taken_at"] for it in everything] == sorted((it["taken_at"] for it in everything), reverse=True)


def test_months_counts_one_per_sha(client, env):
    conn = db.connect(env["data"])
    _seed(conn, [("2024-05-01 10:00:00", "a" * 64, "photo"), ("2024-05-02 10:00:00", "a" * 64, "photo"),
                 ("2024-05-03 10:00:00", "b" * 64, "video"), ("2023-12-31 23:00:00", "c" * 64, "photo")])
    h = headers(env)
    assert client.get("/api/assets/months", headers=h).json()["months"] == [
        {"month": "2024-05", "count": 2}, {"month": "2023-12", "count": 1}]
    assert client.get("/api/assets/months", params={"kind": "video"}, headers=h).json()["months"] == [
        {"month": "2024-05", "count": 1}]


def test_bad_cursor_422(client, env):
    r = client.get("/api/assets", params={"before": "nimic"}, headers=headers(env))
    assert r.status_code == 422


def test_thumb_is_jpeg_and_cached(client, env, monkeypatch):
    make_jpeg(photos_root("ana") / "a.jpg", "2024:05:01 10:00:00", size=(600, 300))
    scan(env)
    h = headers(env)
    aid = asset_id(env)
    r = client.get(f"/api/assets/{aid}/thumb", params={"size": 256}, headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, max-age=31536000"
    assert Image.open(io.BytesIO(r.content)).size == (256, 128)
    assert list((env["data"] / "thumbs").rglob("*_256.jpg"))

    def boom(*a, **k):
        raise AssertionError("Pillow nu trebuia chemat")

    monkeypatch.setattr(thumbs.Image, "open", boom)
    assert client.get(f"/api/assets/{aid}/thumb", params={"size": 256}, headers=h).content == r.content


def test_thumb_bad_size(client, env):
    make_jpeg(photos_root("ana") / "a.jpg", "2024:05:01 10:00:00")
    scan(env)
    r = client.get(f"/api/assets/{asset_id(env)}/thumb", params={"size": 999}, headers=headers(env))
    assert r.status_code == 422


def test_thumb_rotated_exif(client, env):
    img = Image.new("RGB", (400, 200), (10, 10, 200))
    exif = Image.Exif()
    exif[0x0112] = 6
    img.save(photos_root("ana") / "rot.jpg", "JPEG", exif=exif)
    scan(env)
    r = client.get(f"/api/assets/{asset_id(env)}/thumb", params={"size": 256}, headers=headers(env))
    w, h = Image.open(io.BytesIO(r.content)).size
    assert h > w


def test_original_range(client, env):
    p = make_jpeg(photos_root("ana") / "a.jpg", "2024:05:01 10:00:00")
    scan(env)
    h = {**headers(env), "Range": "bytes=0-99"}
    r = client.get(f"/api/assets/{asset_id(env)}/original", headers=h)
    assert r.status_code == 206
    assert r.content == p.read_bytes()[:100]
    full = client.get(f"/api/assets/{asset_id(env)}/original", headers=headers(env))
    assert full.status_code == 200 and full.content == p.read_bytes()


def test_other_users_asset_404(client, env):
    make_jpeg(photos_root("bogdan") / "b.jpg", "2024:05:01 10:00:00")
    scan(env, "bogdan")
    bid = asset_id(env, "bogdan")
    h = headers(env, "ana")
    assert client.get(f"/api/assets/{bid}/thumb", headers=h).status_code == 404
    assert client.get(f"/api/assets/{bid}/original", headers=h).status_code == 404
    assert client.get("/api/assets", headers=h).json() == {"items": [], "next": None}


def test_deleted_asset_hidden(client, env):
    make_jpeg(photos_root("ana") / "a.jpg", "2024:05:01 10:00:00")
    scan(env)
    conn = db.connect(env["data"])
    conn.execute("update assets set deleted_at='2026-10-26 10:00:00'")
    conn.commit()
    h = headers(env)
    assert client.get("/api/assets", headers=h).json()["items"] == []
    assert client.get(f"/api/assets/{asset_id(env)}/original", headers=h).status_code == 404


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg lipsește (rulează în container)")
def test_video_thumb(client, env):
    from tests.fixtures import make_mp4

    make_mp4(photos_root("ana") / "v.mp4")
    scan(env)
    r = client.get(f"/api/assets/{asset_id(env)}/thumb", headers=headers(env))
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).format == "JPEG"


def test_warm_makes_missing_thumbs_newest_first(env):
    make_jpeg(photos_root("ana") / "vechi.jpg", "2020:05:01 10:00:00", size=(2400, 1200))
    make_jpeg(photos_root("ana") / "nou.jpg", "2024:05:01 10:00:00", size=(2400, 1200))
    scan(env)
    conn = db.connect(env["data"])
    assert thumbs.warm(conn, limit=1) == 1
    nou = conn.execute("SELECT sha256 FROM assets WHERE taken_at LIKE '2024%'").fetchone()[0]
    made = list((env["data"] / "thumbs").rglob("*_256.jpg"))
    assert [p.name for p in made] == [f"{nou}_256.jpg"]
    assert Image.open(made[0]).size == (256, 128)
    assert thumbs.warm(conn) == 1
    assert thumbs.warm(conn) == 0
