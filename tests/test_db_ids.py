"""Numerele pozelor nu se refolosesc: altfel o poză nouă primea adresa (și miniatura din cache) celei șterse."""
import sqlite3

from poze import db


def _insert(conn, rel):
    return conn.execute("INSERT INTO assets(user, relpath, sha256) VALUES('ana', ?, ?)", (rel, rel)).lastrowid


def test_ids_not_reused_after_delete(tmp_path):
    conn = db.connect(tmp_path)
    a = _insert(conn, "a.jpg")
    b = _insert(conn, "b.jpg")
    conn.execute("DELETE FROM assets WHERE id=?", (b,))
    conn.commit()
    assert _insert(conn, "c.jpg") == b + 1 and a < b


def test_old_database_migrated_keeps_rows_and_continues_numbering(tmp_path):
    old = sqlite3.connect(tmp_path / "poze.db")
    old.executescript("""
        CREATE TABLE assets(id INTEGER PRIMARY KEY, user TEXT, relpath TEXT, sha256 TEXT, size INT,
          mtime REAL, taken_at TEXT, kind TEXT, width INT, height INT, duration_ms INT, source TEXT,
          deleted_at TEXT, UNIQUE(user, relpath));
        CREATE TABLE trash(id INTEGER PRIMARY KEY, user TEXT, asset_id INT, trash_relpath TEXT,
          orig_relpath TEXT, deleted_at TEXT);
        INSERT INTO assets(id, user, relpath, sha256) VALUES(5, 'ana', 'x.jpg', 'aa');
        INSERT INTO trash(user, asset_id) VALUES('ana', 9);
    """)
    old.commit()
    old.close()
    conn = db.connect(tmp_path)
    row = conn.execute("SELECT id, sha256, rotation, geo_done FROM assets").fetchone()
    assert tuple(row) == (5, "aa", 0, 0)
    assert _insert(conn, "y.jpg") == 10  # după cel mai mare număr din coș
    db.connect(tmp_path).close()  # a doua pornire nu mai face nimic
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='assets'").fetchone()[0]
    assert "AUTOINCREMENT" in sql
    assert {r[1] for r in conn.execute("PRAGMA index_list(assets)")} >= {"assets_taken", "assets_sha", "assets_place"}


def test_album_items_move_stopped_halfway_is_resumed(tmp_path):
    # oprit după RENAME, iar altă conexiune a făcut deja tabelul nou, gol: pozele din albume nu se pierd
    db.connect(tmp_path).close()
    raw = sqlite3.connect(tmp_path / "poze.db")
    raw.executescript("""
        INSERT INTO albums(id, user, name) VALUES(1, 'ana', 'Mare');
        CREATE TABLE album_items_vechi(album_id INT, sha256 TEXT, added_at TEXT, PRIMARY KEY(album_id, sha256));
        INSERT INTO album_items_vechi VALUES(1, 'aa', '2026-01-01');
    """)
    raw.commit()
    raw.close()
    conn = db.connect(tmp_path)
    assert [tuple(r) for r in conn.execute("SELECT album_id, sha256, user FROM album_items")] == [(1, "aa", "ana")]
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='album_items_vechi'").fetchone() is None
