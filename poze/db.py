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
  album_id INT, sha256 TEXT, added_at TEXT, user TEXT, PRIMARY KEY(album_id, user, sha256));
CREATE TABLE IF NOT EXISTS archive(
  user TEXT, sha256 TEXT, added_at TEXT, PRIMARY KEY(user, sha256));
CREATE TABLE IF NOT EXISTS album_members(
  album_id INT, user TEXT, added_at TEXT, PRIMARY KEY(album_id, user));
CREATE TABLE IF NOT EXISTS imported(
  user TEXT, sha256 TEXT, PRIMARY KEY(user, sha256));
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
_COLUMNS = {"lat": "REAL", "lon": "REAL", "place_id": "INT", "geo_done": "INT NOT NULL DEFAULT 0",
            # rotirea cerută din aplicație (0/90/180/270, în sensul acelor); fișierul de pe NAS rămâne neatins
            "rotation": "INT NOT NULL DEFAULT 0"}


def _migrate(conn) -> None:
    have = {r[1] for r in conn.execute("PRAGMA table_info(assets)")}
    for name, decl in _COLUMNS.items():
        if name not in have:
            conn.execute(f"ALTER TABLE assets ADD COLUMN {name} {decl}")
    if "web" not in {r[1] for r in conn.execute("PRAGMA table_info(tokens)")}:
        conn.execute("ALTER TABLE tokens ADD COLUMN web INT NOT NULL DEFAULT 0")  # sesiune de browser
    if "user" not in {r[1] for r in conn.execute("PRAGMA table_info(album_items)")}:
        # albume comune: fiecare poză din album e a cuiva (cele vechi, ale proprietarului albumului),
        # iar aceeași poză poate fi pusă de doi oameni: cheia cuprinde și contul
        conn.executescript("""
            ALTER TABLE album_items RENAME TO album_items_vechi;
            CREATE TABLE album_items(
              album_id INT, sha256 TEXT, added_at TEXT, user TEXT, PRIMARY KEY(album_id, user, sha256));
            INSERT INTO album_items SELECT i.album_id, i.sha256, i.added_at, a.user
              FROM album_items_vechi i JOIN albums a ON a.id=i.album_id;
            DROP TABLE album_items_vechi;
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS assets_place ON assets(user, place_id)")
    conn.commit()


def upsert_asset(conn, user: str, rel: str, sha: str, taken: str, info, source: str):
    """Rândul unui fișier tocmai pus în Photos (upload sau import). Dacă indexerul l-a prins între timp,
    rândul lui e suprascris: data de aici (EXIF, telefon, Google) e mai bună decât a lui."""
    from .users import photos_root

    st = (photos_root(user) / rel).stat()
    conn.execute(
        "INSERT INTO assets(user, relpath, sha256, size, mtime, taken_at, kind, width, height,"
        " duration_ms, source) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(user, relpath) DO UPDATE SET sha256=excluded.sha256, size=excluded.size,"
        " mtime=excluded.mtime, taken_at=excluded.taken_at, kind=excluded.kind,"
        " width=excluded.width, height=excluded.height, duration_ms=excluded.duration_ms,"
        " source=excluded.source, deleted_at=NULL",
        (user, rel, sha, st.st_size, st.st_mtime, taken, info.kind, info.width,
         info.height, info.duration_ms, source))
    return conn.execute("SELECT * FROM assets WHERE user=? AND relpath=?", (user, rel)).fetchone()


def asset_json(row) -> dict:
    """Forma `Asset` din contractul API."""
    a = {k: row[k] for k in ("id", "sha256", "taken_at", "kind", "width", "height", "duration_ms", "source")}
    # rotită cu un sfert: grila o așază deja în picioare / culcată
    a["rotation"] = row["rotation"]
    if row["rotation"] in (90, 270):
        a["width"], a["height"] = a["height"], a["width"]
    return a
