import hashlib
import os
import threading
import time

import pytest
from fastapi.testclient import TestClient

from poze import auth, db, indexer, uploads
from poze.app import create_app
from poze.users import photos_root

from tests.fixtures import make_jpeg

CHUNK = 8 * 1024 * 1024


def headers(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        return {"Authorization": f"Bearer {auth.issue_token(conn, user, 'tel')}"}
    finally:
        conn.close()


def photo_bytes(tmp_path, size, taken="2025:04:05 20:12:26"):
    """Un JPEG valid cu EXIF, umplut la `size` octeți (Pillow ignoră coada)."""
    p = make_jpeg(tmp_path / "src.jpg", taken)
    data = p.read_bytes()
    return data + b"\0" * (size - len(data))


def start(client, h, data, filename="IMG_1.jpg", source="Camera", **extra):
    body = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "filename": filename, "source": source, **extra}
    return client.post("/api/uploads", json=body, headers=h)


def send_all(client, h, upload_id, data, offset=0):
    while offset < len(data):
        r = client.put(f"/api/uploads/{upload_id}?offset={offset}",
                       content=data[offset:offset + CHUNK], headers=h)
        assert r.status_code == 200, r.text
        offset = r.json()["offset"]
    return offset


def asset_count(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        return conn.execute("select count(*) from assets where user=?", (user,)).fetchone()[0]
    finally:
        conn.close()


def test_full_upload_places_file(client, env, no_chown, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, 20 * 1024 * 1024)
    r = start(client, h, data)
    assert r.json()["exists"] is False and r.json()["offset"] == 0
    uid = r.json()["upload_id"]
    assert send_all(client, h, uid, data) == len(data)
    r = client.post(f"/api/uploads/{uid}/finish", headers=h)
    assert r.status_code == 200, r.text
    asset = r.json()["asset"]
    assert asset["taken_at"] == "2025-04-05 20:12:26"
    assert asset["kind"] == "photo" and asset["source"] == "Camera"
    final = photos_root("ana") / "2025/04-aprilie/2025-04-05_20-12-26_Camera.jpg"
    assert hashlib.sha256(final.read_bytes()).hexdigest() == asset["sha256"]
    assert list((photos_root("ana") / ".incoming").iterdir()) == []
    # indexerul găsește același fișier și nu-l dublează
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "ana")
    assert asset_count(env) == 1


def test_existing_sha_skips_upload(client, env, tmp_path):
    old = photos_root("ana") / "MobileBackup/Honor 90/IMG_1.jpg"
    old.parent.mkdir(parents=True)
    make_jpeg(old, "2021:08:13 10:00:00")
    indexer.scan_user(db.connect(env["data"]), "ana")
    data = old.read_bytes()
    r = start(client, headers(env), data)
    assert r.status_code == 200
    assert r.json()["exists"] is True
    assert r.json()["asset"]["taken_at"] == "2021-08-13 10:00:00"


def test_wrong_offset_409(client, env, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, CHUNK + 100)
    uid = start(client, h, data).json()["upload_id"]
    assert client.put(f"/api/uploads/{uid}?offset=0", content=data[:CHUNK], headers=h).json() == {"offset": CHUNK}
    r = client.put(f"/api/uploads/{uid}?offset=0", content=data[:CHUNK], headers=h)
    assert r.status_code == 409
    assert r.json()["offset"] == 8388608 and r.json()["error"]


def test_resume_after_restart(client, env, no_chown, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, CHUNK + 12345)
    uid = start(client, h, data).json()["upload_id"]
    client.put(f"/api/uploads/{uid}?offset=0", content=data[:CHUNK], headers=h)
    fresh = TestClient(create_app(start_indexer=False))
    assert fresh.get(f"/api/uploads/{uid}", headers=h).json() == {"offset": 8388608}
    send_all(fresh, h, uid, data, CHUNK)
    r = fresh.post(f"/api/uploads/{uid}/finish", headers=h)
    assert r.status_code == 200
    final = photos_root("ana") / "2025/04-aprilie/2025-04-05_20-12-26_Camera.jpg"
    assert final.read_bytes() == data


def test_parallel_start_same_sha_one_file(client, env, no_chown, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, 1000)
    results = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        results.append(start(TestClient(create_app(start_indexer=False)), h, data).json())

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results[0]["upload_id"] == results[1]["upload_id"]
    uid = results[0]["upload_id"]
    send_all(client, h, uid, data)
    assert client.post(f"/api/uploads/{uid}/finish", headers=h).status_code == 200
    assert client.post(f"/api/uploads/{uid}/finish", headers=h).status_code == 404
    assert asset_count(env) == 1
    assert start(client, h, data).json()["exists"] is True


def test_corrupt_upload_rejected(client, env, no_chown, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, 5000)
    uid = start(client, h, data).json()["upload_id"]
    bad = bytearray(data)
    bad[4000] ^= 0xFF
    send_all(client, h, uid, bytes(bad))
    r = client.post(f"/api/uploads/{uid}/finish", headers=h)
    assert r.status_code == 422
    assert r.json() == {"error": "Fișierul a ajuns incomplet. Se trimite din nou."}
    assert not (photos_root("ana") / "2025").exists()
    assert list((photos_root("ana") / ".incoming").iterdir()) == []
    assert client.get(f"/api/uploads/{uid}", headers=h).status_code == 404


def test_finish_incomplete_rejected(client, env, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, 5000)
    uid = start(client, h, data).json()["upload_id"]
    client.put(f"/api/uploads/{uid}?offset=0", content=data[:100], headers=h)
    assert client.post(f"/api/uploads/{uid}/finish", headers=h).status_code == 422


def test_chunk_too_big(client, env, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, CHUNK + 1)
    uid = start(client, h, data).json()["upload_id"]
    r = client.put(f"/api/uploads/{uid}?offset=0", content=data, headers=h)
    assert r.status_code == 413
    assert r.json()["error"]
    assert client.get(f"/api/uploads/{uid}", headers=h).json() == {"offset": 0}


def test_chunk_past_declared_size(client, env, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, 5000)
    uid = start(client, h, data).json()["upload_id"]
    r = client.put(f"/api/uploads/{uid}?offset=0", content=data + b"x", headers=h)
    assert r.status_code == 413


def test_unsupported_type_415(client, env, tmp_path):
    r = start(client, headers(env), b"abc", filename="notite.txt")
    assert r.status_code == 415
    assert r.json() == {"error": "Tip de fișier neacceptat."}


def test_other_users_upload_404(client, env, tmp_path):
    data = photo_bytes(tmp_path, 5000)
    uid = start(client, headers(env, "ana"), data).json()["upload_id"]
    hb = headers(env, "bogdan")
    assert client.get(f"/api/uploads/{uid}", headers=hb).status_code == 404
    assert client.put(f"/api/uploads/{uid}?offset=0", content=b"x", headers=hb).status_code == 404
    assert client.post(f"/api/uploads/{uid}/finish", headers=hb).status_code == 404


def test_whatsapp_name_date_when_no_exif(client, env, no_chown, tmp_path):
    from PIL import Image

    p = tmp_path / "wa.jpg"
    Image.new("RGB", (40, 30)).save(p, "JPEG")
    data = p.read_bytes()
    h = headers(env)
    uid = start(client, h, data, filename="IMG-20210813-WA0040.jpg", source="WhatsApp Images").json()["upload_id"]
    send_all(client, h, uid, data)
    asset = client.post(f"/api/uploads/{uid}/finish", headers=h).json()["asset"]
    assert asset["taken_at"] == "2021-08-13 12:00:00"
    assert (photos_root("ana") / "2021/08-august/2021-08-13_12-00-00_WhatsAppImages.jpg").is_file()


def test_check_only_own(client, env, tmp_path):
    for user in ("ana", "bogdan"):
        p = photos_root(user) / f"{user}.jpg"
        make_jpeg(p, "2020:01:01 10:00:00", size=(64 if user == "ana" else 65, 48))
        indexer.scan_user(db.connect(env["data"]), user)
    sha_ana = hashlib.sha256((photos_root("ana") / "ana.jpg").read_bytes()).hexdigest()
    sha_bogdan = hashlib.sha256((photos_root("bogdan") / "bogdan.jpg").read_bytes()).hexdigest()
    r = client.post("/api/check", json={"sha256": [sha_ana, sha_bogdan, "0" * 64]}, headers=headers(env))
    assert r.json() == {"present": [sha_ana]}
    assert client.post("/api/check", json={"sha256": ["0" * 64] * 501}, headers=headers(env)).status_code == 422


def test_requires_token(client):
    assert client.post("/api/check", json={"sha256": []}).status_code == 401
    assert client.post("/api/uploads", json={}).status_code == 401


def test_stale_uploads_cleaned(client, env, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, 5000)
    uid = start(client, h, data).json()["upload_id"]
    client.put(f"/api/uploads/{uid}?offset=0", content=data[:100], headers=h)
    incoming = photos_root("ana") / ".incoming"
    orphan = incoming / "orfan.part.jpg"
    orphan.write_bytes(b"x")
    old = time.time() - 8 * 86400
    os.utime(orphan, (old, old))
    conn = db.connect(env["data"])
    uploads.cleanup_stale(conn, now=time.time() + 8 * 86400)
    assert not orphan.exists()
    assert list(incoming.iterdir()) == []
    assert conn.execute("select count(*) from uploads").fetchone()[0] == 0


def test_fresh_uploads_kept(client, env, tmp_path):
    h = headers(env)
    data = photo_bytes(tmp_path, 5000)
    uid = start(client, h, data).json()["upload_id"]
    client.put(f"/api/uploads/{uid}?offset=0", content=data[:100], headers=h)
    uploads.cleanup_stale(db.connect(env["data"]), now=time.time() + 6 * 86400)
    assert client.get(f"/api/uploads/{uid}", headers=h).json() == {"offset": 100}


def test_absurd_hint_rejected(client, env):
    data = b"\xff\xd8" + b"x" * 10
    r = start(client, headers(env), data, taken_at_hint_ms=10**18)
    assert r.status_code == 422


def test_upload_makes_missing_photos_folder(client, env, no_chown, tmp_path):
    import shutil
    shutil.rmtree(photos_root("ana"))  # cont care n-a deschis niciodată Synology Photos
    r = start(client, headers(env), photo_bytes(tmp_path, 1000))
    assert r.status_code == 200, r.text
    assert photos_root("ana").is_dir()


def test_upload_without_home_explains(client, env, no_chown, tmp_path):
    import shutil
    shutil.rmtree(photos_root("ana").parent)  # serviciul User Home oprit
    r = start(client, headers(env), photo_bytes(tmp_path, 1000))
    assert r.status_code == 409 and "User Home" in r.json()["error"]
