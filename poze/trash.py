"""Coșul de pe NAS: `Photos/.cos/<AAAA-LL-ZZ>/<calea veche>`, golit după 30 de zile."""
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from . import naming, users
from .metadata import FMT, TZ

log = logging.getLogger(__name__)
KEEP_DAYS = 30


def _free_rel(user: str, rel: str) -> str:
    p = Path(rel)
    n = 1
    while users.safe_path(user, rel).exists():
        n += 1
        rel = str(p.with_name(f"{p.stem}_{n}{p.suffix}"))
    return rel


def move_to_trash(conn, user: str, asset_id: int) -> None:
    """Mută în coș toate copiile cu aceeași amprentă, ca poza să nu reapară dintr-o copie veche."""
    row = conn.execute("SELECT sha256 FROM assets WHERE id=? AND user=? AND deleted_at IS NULL",
                       (asset_id, user)).fetchone()
    if row is None:
        raise KeyError(asset_id)
    now = datetime.now(TZ)
    stamp, day = now.strftime(FMT), now.strftime("%Y-%m-%d")
    uid = users.uid_of(user)
    copies = conn.execute("SELECT id, relpath FROM assets WHERE user=? AND sha256=? AND deleted_at IS NULL",
                          (user, row["sha256"])).fetchall()
    for c in copies:
        src = users.safe_path(user, c["relpath"])
        dest_rel = None
        if src.is_file():
            dest_rel = _free_rel(user, f".cos/{day}/{c['relpath']}")
            naming._make_dirs(user, str(Path(dest_rel).parent), uid)
            os.rename(src, users.safe_path(user, dest_rel))
        else:
            log.warning("coș: %s lipsește deja de pe disc", c["relpath"])
        conn.execute("UPDATE assets SET deleted_at=? WHERE id=?", (stamp, c["id"]))
        conn.execute("INSERT INTO trash(user, asset_id, trash_relpath, orig_relpath, deleted_at)"
                     " VALUES(?,?,?,?,?)", (user, c["id"], dest_rel, c["relpath"], stamp))
        conn.commit()


def _prune_dirs(user: str, path: Path) -> None:
    stop = users.safe_path(user, ".cos")
    d = path.parent
    while d != stop and d.is_relative_to(stop):
        try:
            d.rmdir()
        except OSError:
            return
        d = d.parent


def purge_trash(conn, settings, now: datetime | None = None) -> int:
    """Șterge definitiv ce stă în coș de peste 30 de zile. Întoarce numărul de fișiere șterse."""
    now = now or datetime.now(TZ)
    cutoff = (now - timedelta(days=KEEP_DAYS)).strftime(FMT)
    removed = 0
    for t in conn.execute("SELECT * FROM trash WHERE deleted_at < ?", (cutoff,)).fetchall():
        if t["trash_relpath"]:
            try:
                path = users.safe_path(t["user"], t["trash_relpath"])
                path.unlink()
                removed += 1
                _prune_dirs(t["user"], path)
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as e:
                log.warning("golire coș %s: %s", t["trash_relpath"], e)
                continue
        conn.execute("DELETE FROM trash WHERE id=?", (t["id"],))
        # rândul rămâne dacă omul a scos poza din coș și indexerul a reactivat-o
        conn.execute("DELETE FROM assets WHERE id=? AND deleted_at IS NOT NULL", (t["asset_id"],))
        conn.commit()
    return removed
