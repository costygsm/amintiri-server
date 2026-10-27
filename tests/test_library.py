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
    assert set(items[0]) == {"id", "sha256", "taken_at", "kind", "width", "height", "duration_ms", "source"}


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
