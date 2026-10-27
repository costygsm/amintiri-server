"""Copia zilnică a bazei de date (albume, favorite, coș), cu API-ul de backup al SQLite:
sigur și cât serverul scrie. Pozele nu intră aici: sunt fișiere în Photos și se reindexează singure."""
import logging
import sqlite3
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)
KEEP = 7


def daily(conn: sqlite3.Connection, data_dir: Path, today: date | None = None, keep: int = KEEP) -> Path | None:
    """Scrie data/backup/poze-AAAA-LL-ZZ.db o dată pe zi și păstrează ultimele [keep]. Întoarce fișierul nou."""
    folder = Path(data_dir) / "backup"
    folder.mkdir(exist_ok=True)
    target = folder / f"poze-{(today or date.today()).isoformat()}.db"
    if target.exists():
        return None
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    out = sqlite3.connect(tmp)
    try:
        conn.backup(out)
    finally:
        out.close()
    tmp.rename(target)  # o copie pe jumătate nu apare niciodată cu nume bun
    for old in sorted(folder.glob("poze-*.db"))[:-keep]:
        old.unlink()
    log.info("copia bazei de date: %s", target.name)
    return target
