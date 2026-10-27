import hashlib
import os
from pathlib import Path

import pytest

from poze import db, indexer, metadata
from poze.indexer import ScanStats, source_of
from tests.fixtures import make_jpeg


def _tree(root: Path):
    cam = root / "MobileBackup/HONOR 90/DCIM/Camera/2025/04"
    cam.mkdir(parents=True)
    make_jpeg(cam / "IMG_20250405_201226.jpg")
    (root / "Fotografii nunta").mkdir()
    make_jpeg(root / "Fotografii nunta/a.jpg")
    (root / "@eaDir").mkdir()
    make_jpeg(root / "@eaDir/x.jpg")
    (root / ".cos").mkdir()
    make_jpeg(root / ".cos/y.jpg")


@pytest.fixture
def conn(env):
    c = db.connect(env["data"])
    yield c
    c.close()


def _rows(conn, user="ana"):
    return conn.execute("SELECT * FROM assets WHERE user=? ORDER BY relpath", (user,)).fetchall()


def test_indexes_old_layout(env, conn):
    _tree(env["homes"] / "ana/Photos")
    stats = indexer.scan_user(conn, "ana")
    assert stats == ScanStats(2, 0, 0)
    rows = _rows(conn)
    assert len(rows) == 2
    by = {r["relpath"]: r for r in rows}
    cam = by["MobileBackup/HONOR 90/DCIM/Camera/2025/04/IMG_20250405_201226.jpg"]
    assert cam["source"] == "Camera"
    assert cam["taken_at"] == "2025-04-05 20:12:26"
    assert cam["kind"] == "photo" and cam["width"] == 64 and cam["height"] == 48
    assert len(cam["sha256"]) == 64 and cam["deleted_at"] is None
    assert by["Fotografii nunta/a.jpg"]["source"] == "Fotografii nunta"


def test_source_rules():
    assert source_of("MobileBackup/HONOR 90/DCIM/Camera/2025/04/IMG_20250405_201226.jpg") == "Camera"
    assert source_of("MobileBackup/HONOR 90/WhatsApp Images/2025/05/x.jpg") == "WhatsApp Images"
    assert source_of("Fotografii nunta/a.jpg") == "Fotografii nunta"
    assert source_of("a.jpg") == "Photos"
    assert source_of("2025/04-aprilie/2025-04-05_20-12-26_Camera_2.jpg") == "Camera"
    assert source_of("2025/04-aprilie/2025-04-05_20-12-26_Camera.jpg") == "Camera"


def _snapshot(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p)] = (hashlib.sha256(p.read_bytes()).hexdigest(), st.st_mtime_ns, st.st_size)
    return out


def test_never_touches_files(env, conn):
    root = env["homes"] / "ana/Photos"
    _tree(root)
    old = root / "Fotografii nunta/a.jpg"
    os.utime(old, (1_000_000_000, 1_000_000_000))
    before = _snapshot(root)
    names = sorted(str(p) for p in root.rglob("*"))
    indexer.scan_user(conn, "ana")
    indexer.scan_user(conn, "ana")
    assert _snapshot(root) == before
    assert sorted(str(p) for p in root.rglob("*")) == names


def test_incremental(env, conn, monkeypatch):
    _tree(env["homes"] / "ana/Photos")
    indexer.scan_user(conn, "ana")

    def boom(*a, **k):
        raise AssertionError("read_media_info chemat")

    monkeypatch.setattr(metadata, "read_media_info", boom)
    assert indexer.scan_user(conn, "ana") == ScanStats(0, 0, 0)


def test_removed_marked_and_reappears(env, conn):
    root = env["homes"] / "ana/Photos"
    _tree(root)
    indexer.scan_user(conn, "ana")
    f = root / "Fotografii nunta/a.jpg"
    data = f.read_bytes()
    f.unlink()
    assert indexer.scan_user(conn, "ana") == ScanStats(0, 0, 1)
    row = [r for r in _rows(conn) if r["relpath"].startswith("Fotografii")][0]
    assert row["deleted_at"] is not None
    assert indexer.scan_user(conn, "ana") == ScanStats(0, 0, 0)
    f.write_bytes(data)
    assert indexer.scan_user(conn, "ana").updated == 1
    row = [r for r in _rows(conn) if r["relpath"].startswith("Fotografii")][0]
    assert row["deleted_at"] is None


def test_changed_file_updated(env, conn):
    root = env["homes"] / "ana/Photos"
    _tree(root)
    indexer.scan_user(conn, "ana")
    f = root / "Fotografii nunta/a.jpg"
    old_sha = [r for r in _rows(conn) if r["relpath"].startswith("Fotografii")][0]["sha256"]
    make_jpeg(f, size=(10, 10))
    assert indexer.scan_user(conn, "ana") == ScanStats(0, 1, 0)
    new = [r for r in _rows(conn) if r["relpath"].startswith("Fotografii")][0]
    assert new["sha256"] != old_sha and new["width"] == 10


def test_users_isolated(env, conn):
    _tree(env["homes"] / "ana/Photos")
    make_jpeg(env["homes"] / "bogdan/Photos/b.jpg")
    make_jpeg(env["homes"] / "bogdan/Photos/c.jpg")
    indexer.scan_user(conn, "ana")
    indexer.scan_user(conn, "bogdan")
    assert {r["user"] for r in _rows(conn, "bogdan")} == {"bogdan"}
    assert len(_rows(conn, "ana")) == 2
    # dispariția la bogdan nu atinge rândurile lui ana
    (env["homes"] / "bogdan/Photos/b.jpg").unlink()
    assert indexer.scan_user(conn, "bogdan").removed == 1
    assert all(r["deleted_at"] is None for r in _rows(conn, "ana"))


def test_scan_all(env, conn):
    make_jpeg(env["homes"] / "ana/Photos/a.jpg")
    make_jpeg(env["homes"] / "bogdan/Photos/b.jpg")
    (env["homes"] / "fara_poze").mkdir()
    from poze.config import get_settings

    indexer.scan_all(conn, get_settings())
    assert len(_rows(conn, "ana")) == 1 and len(_rows(conn, "bogdan")) == 1


def test_empty_tree_does_not_mass_delete(env, conn):
    root = env["homes"] / "ana/Photos"
    for n in "abc":
        make_jpeg(root / f"{n}.jpg")
    indexer.scan_user(conn, "ana")
    for n in "abc":
        (root / f"{n}.jpg").unlink()
    assert indexer.scan_user(conn, "ana").removed == 0
    assert all(r["deleted_at"] is None for r in _rows(conn))


def test_big_partial_loss_skipped(env, conn, monkeypatch):
    root = env["homes"] / "ana/Photos"
    root.mkdir(exist_ok=True)
    for i in range(60):
        make_jpeg(root / f"f{i}.jpg")
    make_jpeg(root / "keep.jpg")
    indexer.scan_user(conn, "ana")
    for i in range(60):
        (root / f"f{i}.jpg").unlink()
    assert indexer.scan_user(conn, "ana").removed == 0


def test_reappear_same_stat_not_reread(env, conn, monkeypatch):
    root = env["homes"] / "ana/Photos"
    _tree(root)
    indexer.scan_user(conn, "ana")
    f = root / "Fotografii nunta/a.jpg"
    data, st = f.read_bytes(), f.stat()
    f.unlink()
    assert indexer.scan_user(conn, "ana").removed == 1
    f.write_bytes(data)
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))

    def boom(*a, **k):
        raise AssertionError("recitit")

    monkeypatch.setattr(metadata, "read_media_info", boom)
    monkeypatch.setattr(metadata, "sha256_file", boom)
    indexer.scan_user(conn, "ana")
    row = [r for r in _rows(conn) if r["relpath"].startswith("Fotografii")][0]
    assert row["deleted_at"] is None


def test_bad_filename_does_not_abort(env, conn):
    root = env["homes"] / "ana/Photos"
    make_jpeg(root / os.fsdecode(b"bad\xff.jpg"))
    make_jpeg(root / "good.jpg")
    stats = indexer.scan_user(conn, "ana")
    assert stats.added == 1
    assert [r["relpath"] for r in _rows(conn)] == ["good.jpg"]


def test_symlinks_not_indexed(env, conn):
    make_jpeg(env["homes"] / "bogdan/Photos/b.jpg")
    (env["homes"] / "ana/Photos/link.jpg").symlink_to(env["homes"] / "bogdan/Photos/b.jpg")
    assert indexer.scan_user(conn, "ana") == ScanStats(0, 0, 0)
    assert _rows(conn) == []


def test_recycle_and_incoming_ignored(env, conn):
    root = env["homes"] / "ana/Photos"
    for d in ("#recycle", ".incoming"):
        (root / d).mkdir()
        make_jpeg(root / d / "z.jpg")
    make_jpeg(root / ".hidden.jpg")
    assert indexer.scan_user(conn, "ana") == ScanStats(0, 0, 0)
