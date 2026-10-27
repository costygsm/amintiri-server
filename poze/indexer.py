"""Indexarea pozelor din Photos. Fișierele sunt doar citite, niciodată modificate."""
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import backup, db, geo, metadata, trash
from .metadata import FMT, TZ
from .users import photos_root

log = logging.getLogger(__name__)

IGNORED = {"@eaDir", "#recycle", ".cos", ".incoming"}
EXTENSIONS = {"jpg", "jpeg", "png", "heic", "heif", "gif", "webp", "dng",
              "mp4", "mov", "3gp", "m4v", "mkv", "webm"}
INTERVAL = 15 * 60
COMMIT_EVERY = 500

_SKIP_DIR_RE = re.compile(r"^\d+(-[a-z]+)?$")
_NEW_NAME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_(?P<src>[A-Za-z0-9]+)(?:_\d+)?\.[a-z0-9]+$"
)


@dataclass(frozen=True)
class ScanStats:
    added: int = 0
    updated: int = 0
    removed: int = 0


def source_of(relpath: str) -> str:
    parts = relpath.split("/")
    m = _NEW_NAME_RE.match(parts[-1])
    if m:
        return m.group("src")
    folders = parts[:-1]
    for i in range(len(folders) - 1, -1, -1):
        name = folders[i]
        if _SKIP_DIR_RE.match(name) or name == "MobileBackup":
            continue
        if i >= 1 and folders[i - 1] == "MobileBackup":
            continue  # folderul dispozitivului
        return name
    return "Photos"


def _ignored(name: str) -> bool:
    return name in IGNORED or name.startswith(".")


def _now() -> str:
    return datetime.now(TZ).strftime(FMT)


def scan_user(conn, user: str) -> ScanStats:
    root = photos_root(user)
    if not root.is_dir():
        return ScanStats()
    existing = {
        r["relpath"]: r
        for r in conn.execute(
            "SELECT relpath, size, mtime, deleted_at FROM assets WHERE user=?", (user,)
        )
    }
    seen: set[str] = set()
    added = updated = pending = 0
    complete = True
    last_commit = time.monotonic()

    def onerror(err):
        nonlocal complete
        complete = False
        log.warning("indexare: %s", err)

    def flush():
        nonlocal pending, last_commit
        conn.commit()
        pending = 0
        last_commit = time.monotonic()

    for dirpath, dirnames, filenames in os.walk(root, onerror=onerror):
        dirnames[:] = sorted(d for d in dirnames if not _ignored(d))
        for fn in sorted(filenames):
            if _ignored(fn) or "." not in fn or fn.rsplit(".", 1)[-1].lower() not in EXTENSIONS:
                continue
            path = Path(dirpath) / fn
            if path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            seen.add(rel)
            try:
                st = path.stat()
                if not path.is_file():
                    seen.discard(rel)
                    continue
                row = existing.get(rel)
                if row and row["deleted_at"] is None and row["size"] == st.st_size \
                        and row["mtime"] == st.st_mtime:
                    continue
                if row and row["size"] == st.st_size and row["mtime"] == st.st_mtime:
                    # a reapărut neschimbat: nu recitim, doar reactivăm
                    conn.execute("UPDATE assets SET deleted_at=NULL WHERE user=? AND relpath=?",
                                 (user, rel))
                    updated += 1
                    pending += 1
                else:
                    # tranzacția scurtă: nu ținem blocarea cât calculăm amprenta
                    if pending and (time.monotonic() - last_commit >= 1 or st.st_size > 8 << 20):
                        flush()
                    info = metadata.read_media_info(path)
                    taken = metadata.resolve_taken_at(info, path, None)
                    sha = metadata.sha256_file(path)
                    vals = (sha, st.st_size, st.st_mtime, taken, info.kind, info.width,
                            info.height, info.duration_ms, source_of(rel))
                    conn.execute("SAVEPOINT f")
                    try:
                        if row:
                            conn.execute(
                                "UPDATE assets SET sha256=?, size=?, mtime=?, taken_at=?, kind=?,"
                                " width=?, height=?, duration_ms=?, source=?, deleted_at=NULL"
                                " WHERE user=? AND relpath=?", vals + (user, rel))
                        else:
                            conn.execute(
                                "INSERT INTO assets(sha256, size, mtime, taken_at, kind, width,"
                                " height, duration_ms, source, user, relpath)"
                                " VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals + (user, rel))
                    except Exception:
                        conn.execute("ROLLBACK TO f")
                        raise
                    finally:
                        conn.execute("RELEASE f")
                    if row:
                        updated += 1
                    else:
                        added += 1
                    pending += 1
            except Exception as e:  # fișier ilizibil sau nume nescriibil: îl sărim
                log.warning("indexare: %r: %s", rel, e)
                continue
            if pending >= COMMIT_EVERY or time.monotonic() - last_commit >= 1:
                flush()

    removed = 0
    live = [rel for rel, r in existing.items() if r["deleted_at"] is None]
    gone = [rel for rel in live if rel not in seen]
    if gone and complete:
        if not seen:
            log.warning("indexare %s: niciun fișier găsit, %d rânduri păstrate (montare lipsă?)",
                        user, len(live))
        elif len(gone) > 50 and len(gone) > 0.2 * len(live):
            log.warning("indexare %s: ar dispărea %d din %d rânduri, ștergerea sărită",
                        user, len(gone), len(live))
        else:
            now = _now()
            for rel in gone:
                conn.execute("UPDATE assets SET deleted_at=? WHERE user=? AND relpath=?",
                             (now, user, rel))
            removed = len(gone)
    conn.commit()
    return ScanStats(added, updated, removed)


def scan_all(conn, settings) -> None:
    root = Path(settings.homes_root)
    if not root.is_dir():
        return
    for home in sorted(root.iterdir()):
        if (home / "Photos").is_dir():
            try:
                stats = scan_user(conn, home.name)
                log.info("indexare %s: %s", home.name, stats)
                if n := geo.backfill(conn, home.name):
                    log.info("locuri %s: %d poze citite", home.name, n)
            except Exception:
                log.exception("indexare eșuată pentru %s", home.name)


def start_background(settings) -> threading.Thread:
    def loop():
        try:
            os.nice(10)
        except Exception:
            pass
        conn = db.connect(settings.data_dir)
        try:
            if n := geo.relocate(conn):
                log.info("locuri refăcute pentru %d poze", n)
        except Exception:
            log.exception("refacerea locurilor a eșuat")
        while True:
            try:
                scan_all(conn, settings)
            except Exception:
                log.exception("indexare: iterație eșuată")
            try:
                trash.purge_trash(conn, settings)
            except Exception:
                log.exception("golirea coșului a eșuat")
            try:
                backup.daily(conn, settings.data_dir)
            except Exception:
                log.exception("copia bazei de date a eșuat")
            time.sleep(INTERVAL)

    t = threading.Thread(target=loop, name="indexer", daemon=True)
    t.start()
    return t
