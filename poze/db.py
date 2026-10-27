import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY, user TEXT, relpath TEXT, sha256 TEXT, size INT,
  mtime REAL, taken_at TEXT, kind TEXT, width INT, height INT,
  duration_ms INT, source TEXT, deleted_at TEXT,
  UNIQUE(user, relpath));
CREATE INDEX IF NOT EXISTS assets_taken ON assets(user, taken_at, id);
CREATE INDEX IF NOT EXISTS assets_sha ON assets(user, sha256);
CREATE TABLE IF NOT EXISTS tokens(
  hash TEXT PRIMARY KEY, user TEXT, device TEXT, created_at TEXT, last_used TEXT);
CREATE TABLE IF NOT EXISTS uploads(
  id TEXT PRIMARY KEY, user TEXT, sha256 TEXT, size INT, filename TEXT,
  source TEXT, hint_ms INT, offset INT, created_at TEXT);
CREATE TABLE IF NOT EXISTS places(
  id INTEGER PRIMARY KEY, name TEXT, region TEXT, country TEXT, lat REAL, lon REAL,
  UNIQUE(name, region, country));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS favorites(
  user TEXT, sha256 TEXT, added_at TEXT, PRIMARY KEY(user, sha256));
CREATE TABLE IF NOT EXISTS album_links(
  token TEXT PRIMARY KEY, album_id INT UNIQUE, created_at TEXT);
CREATE TABLE IF NOT EXISTS albums(
  id INTEGER PRIMARY KEY, user TEXT, name TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS album_items(
  album_id INT, sha256 TEXT, added_at TEXT, PRIMARY KEY(album_id, sha256));
CREATE TABLE IF NOT EXISTS trash(
  id INTEGER PRIMARY KEY, user TEXT, asset_id INT, trash_relpath TEXT,
  orig_relpath TEXT, deleted_at TEXT);
"""


def connect(data_dir: Path) -> sqlite3.Connection:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "poze.db", check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# coloane adăugate după prima versiune; o bază veche le primește la pornire
_COLUMNS = {"lat": "REAL", "lon": "REAL", "place_id": "INT", "geo_done": "INT NOT NULL DEFAULT 0"}


def _migrate(conn) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(assets)")}
    for name, decl in _COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE assets ADD COLUMN {name} {decl}")
    if "web" not in {r[1] for r in conn.execute("PRAGMA table_info(tokens)")}:
        conn.execute("ALTER TABLE tokens ADD COLUMN web INT NOT NULL DEFAULT 0")  # sesiune de browser
    conn.execute("CREATE INDEX IF NOT EXISTS assets_place ON assets(user, place_id)")
    conn.commit()


def asset_json(row) -> dict:
    """Forma `Asset` din contractul API."""
    return {k: row[k] for k in ("id", "sha256", "taken_at", "kind", "width", "height",
                                "duration_ms", "source")}
