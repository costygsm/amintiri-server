"""Cronologia, miniaturile și originalele."""
import logging
import re
import sqlite3
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from . import memories, thumbs, trash
from .auth import ApiError, current_user, get_db
from .db import asset_json
from .users import safe_path

log = logging.getLogger(__name__)
router = APIRouter()

_CURSOR_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\|(\d+)$")
NOT_FOUND = "Poza nu există."

# un rând pe amprentă: copiile vechi (MobileBackup, …_Conflict) apar o singură dată
_TIMELINE = """
WITH u AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY sha256 ORDER BY id) AS rn
  FROM assets WHERE {scope} AND deleted_at IS NULL)
SELECT * FROM u WHERE rn=1 AND (? IS NULL OR (taken_at, id) < (?, ?)) {extra}
ORDER BY taken_at DESC, id DESC LIMIT ?
"""
# aceeași listă, în sus: pozele mai noi decât cursorul, după un salt din bara cu anii
_NEWER = """
WITH u AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY sha256 ORDER BY id) AS rn
  FROM assets WHERE {scope} AND deleted_at IS NULL)
SELECT * FROM u WHERE rn=1 AND (taken_at, id) > (?, ?) {extra}
ORDER BY taken_at, id LIMIT ?
"""


def _cursor(c: str) -> tuple[str, int]:
    m = _CURSOR_RE.match(c)
    if not m:
        raise ApiError(422, "Cerere invalidă.")
    return m.group(1), int(m.group(2))


def paged(conn, user: str, before: str | None, limit: int, extra: str = "", params: tuple = (),
          after: str | None = None, scope: tuple[str, tuple] | None = None) -> dict:
    """O pagină din cronologie, cea mai nouă prima; [extra] filtrează (loc, album).
    Cu [after]: pozele imediat mai noi decât cursorul (tot cea mai nouă prima), iar „prev” continuă în sus.
    [scope] înlocuiește „pozele lui [user]” (albumele comune au pozele mai multor oameni)."""
    where, owner = scope or ("user=?", (user,))
    if after is not None:
        taken, aid = _cursor(after)
        rows = conn.execute(_NEWER.format(scope=where, extra=extra), (*owner, taken, aid, *params, limit)).fetchall()
        prev = f"{rows[-1]['taken_at']}|{rows[-1]['id']}" if len(rows) == limit else None
        return {"items": [asset_json(r) for r in reversed(rows)], "prev": prev}
    taken = aid = None
    if before is not None:
        taken, aid = _cursor(before)
    rows = conn.execute(_TIMELINE.format(scope=where, extra=extra), (*owner, taken, taken, aid, *params, limit)).fetchall()
    nxt = f"{rows[-1]['taken_at']}|{rows[-1]['id']}" if len(rows) == limit else None
    return {"items": [asset_json(r) for r in rows], "next": nxt}


def own_asset(conn, user: str, asset_id: int):
    row = conn.execute("SELECT * FROM assets WHERE id=? AND user=? AND deleted_at IS NULL",
                       (asset_id, user)).fetchone()
    if row is None:
        raise ApiError(404, NOT_FOUND)
    return row


# albumele în care [user] e proprietar sau membru
VISIBLE_ALBUMS = "SELECT id FROM albums WHERE user=? UNION SELECT album_id FROM album_members WHERE user=?"


def visible_asset(conn, user: str, asset_id: int):
    """Poza lui sau a altcuiva, pusă într-un album comun în care e și el (doar de văzut, nu de șters)."""
    row = conn.execute(
        "SELECT * FROM assets WHERE id=? AND deleted_at IS NULL AND (user=? OR EXISTS ("
        " SELECT 1 FROM album_items i WHERE i.user=assets.user AND i.sha256=assets.sha256"
        f" AND i.album_id IN ({VISIBLE_ALBUMS})))", (asset_id, user, user, user)).fetchone()
    if row is None:
        raise ApiError(404, NOT_FOUND)
    return row


@router.get("/api/assets")
def timeline(before: str | None = None, after: str | None = None, limit: int = Query(200, ge=1, le=500),
             kind: Literal["photo", "video"] | None = None,
             user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """[kind] = doar poze sau doar clipuri, ca filtrul „Clipuri” din Google Photos."""
    # arhivate = scoase din cronologie (rămân în albume, favorite, căutare și în Arhivă)
    extra, params = NOT_ARCHIVED, (user,)
    if kind:
        extra, params = extra + " AND kind=?", (user, kind)
    return paged(conn, user, before, limit, extra, params, after=after)


NOT_ARCHIVED = "AND sha256 NOT IN (SELECT sha256 FROM archive WHERE user=?)"


class Rotate(BaseModel):
    degrees: Literal[90, -90, 180]


@router.post("/api/assets/{asset_id}/rotate")
def rotate(asset_id: int, body: Rotate, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Doar a lui; toate copiile cu aceeași amprentă, ca în cronologie să apară la fel."""
    row = own_asset(conn, user, asset_id)
    if row["kind"] != "photo":
        raise ApiError(422, "Doar pozele se pot roti.")
    conn.execute("UPDATE assets SET rotation=? WHERE user=? AND sha256=?",
                 ((row["rotation"] + body.degrees) % 360, user, row["sha256"]))
    conn.commit()
    return asset_json(own_asset(conn, user, asset_id))


@router.get("/api/assets/months")
def months(kind: Literal["photo", "video"] | None = None,
           user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Câte poze are fiecare lună, cea mai nouă prima: din asta se desenează bara cu anii de pe web."""
    rows = conn.execute(
        "WITH u AS (SELECT taken_at, kind, ROW_NUMBER() OVER (PARTITION BY sha256 ORDER BY id) AS rn"
        " FROM assets WHERE user=? AND deleted_at IS NULL"
        " AND sha256 NOT IN (SELECT sha256 FROM archive WHERE user=?))"
        " SELECT substr(taken_at, 1, 7) AS m, count(*) AS n FROM u WHERE rn=1 AND (? IS NULL OR kind=?)"
        " GROUP BY m ORDER BY m DESC", (user, user, kind, kind)).fetchall()
    return {"months": [{"month": r["m"], "count": r["n"]} for r in rows]}


@router.get("/api/assets/{asset_id}/thumb")
async def thumb(asset_id: int, size: int = 256, user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    if size not in thumbs.SIZES:
        raise ApiError(422, "Cerere invalidă.")
    row = await run_in_threadpool(visible_asset, conn, user, asset_id)
    try:
        path = await run_in_threadpool(thumbs.thumbnail, row, size)
    except Exception as e:
        log.warning("miniatură %s: %s", asset_id, e)
        raise ApiError(404, "Miniatura nu se poate face.")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=31536000"})


@router.get("/api/assets/{asset_id}/original")
def original(asset_id: int, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    row = visible_asset(conn, user, asset_id)
    try:
        path = safe_path(row["user"], row["relpath"])
    except ValueError:
        raise ApiError(404, NOT_FOUND)
    if not path.is_file():
        raise ApiError(404, NOT_FOUND)
    return FileResponse(path)


@router.get("/api/memories")
def on_this_day(day: date = Query(alias="date"), user: str = Depends(current_user),
                conn: sqlite3.Connection = Depends(get_db)):
    return {"years": memories.on_this_day(conn, user, day)}


@router.delete("/api/assets/{asset_id}", status_code=204)
def delete(asset_id: int, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    try:
        trash.move_to_trash(conn, user, asset_id)
    except KeyError:
        raise ApiError(404, NOT_FOUND)
    return Response(status_code=204)
