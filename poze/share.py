"""Linkul public al unui album: oricine are linkul vede doar pozele din albumul acela, fără cont."""
import re
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response

from . import thumbs
from .auth import ApiError, current_user, get_db
from .collections import ALBUM_NOT_FOUND, _album_json, _own
from .library import NOT_FOUND, own_asset, paged
from .users import safe_path

router = APIRouter()
WEB_DIR = Path(__file__).parent / "web"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{40,64}$")
_IN_ALBUM = "AND sha256 IN (SELECT sha256 FROM album_items WHERE album_id=?)"
GONE = "Linkul nu mai e valabil."


@router.post("/api/albums/{album_id}/link")
def make_link(album_id: int, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    row = conn.execute("SELECT token FROM album_links WHERE album_id=?", (album_id,)).fetchone()
    if row:
        return {"token": row[0]}
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO album_links(token, album_id, created_at) VALUES(?,?,?)",
                 (token, album_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    return {"token": token}


@router.delete("/api/albums/{album_id}/link", status_code=204)
def stop_link(album_id: int, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    conn.execute("DELETE FROM album_links WHERE album_id=?", (album_id,))
    conn.commit()
    return Response(status_code=204)


def _album(conn, token: str):
    """(user, album_id) pentru un link valabil; 404 la orice altceva, fără să spună de ce."""
    row = None
    if _TOKEN_RE.match(token):
        row = conn.execute("SELECT a.user, a.id FROM album_links l JOIN albums a ON a.id=l.album_id"
                           " WHERE l.token=?", (token,)).fetchone()
    if row is None:
        raise ApiError(404, GONE)
    return row["user"], row["id"]


def _member(conn, token: str, asset_id: int):
    user, aid = _album(conn, token)
    row = own_asset(conn, user, asset_id)
    if conn.execute("SELECT 1 FROM album_items WHERE album_id=? AND sha256=?", (aid, row["sha256"])).fetchone() is None:
        raise ApiError(404, NOT_FOUND)
    return user, row


@router.get("/api/public/{token}")
def public_album(token: str, conn: sqlite3.Connection = Depends(get_db)):
    user, aid = _album(conn, token)
    a = _album_json(conn, user, aid)
    return {"name": a["name"], "count": a["count"]}


@router.get("/api/public/{token}/assets")
def public_assets(token: str, before: str | None = None, limit: int = Query(200, ge=1, le=500),
                  conn: sqlite3.Connection = Depends(get_db)):
    user, aid = _album(conn, token)
    page = paged(conn, user, before, limit, _IN_ALBUM, (aid,))
    # sursa (folderul de pe telefon) nu privește pe nimeni din afară
    return {"items": [{k: v for k, v in i.items() if k != "source"} for i in page["items"]], "next": page["next"]}


@router.get("/api/public/{token}/thumb/{asset_id}")
async def public_thumb(token: str, asset_id: int, size: int = 256, conn: sqlite3.Connection = Depends(get_db)):
    if size not in thumbs.SIZES:
        raise ApiError(422, "Cerere invalidă.")
    _user, row = await run_in_threadpool(_member, conn, token, asset_id)
    try:
        path = await run_in_threadpool(thumbs.thumbnail, row, size)
    except Exception:
        raise ApiError(404, "Miniatura nu se poate face.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/api/public/{token}/original/{asset_id}")
def public_original(token: str, asset_id: int, conn: sqlite3.Connection = Depends(get_db)):
    user, row = _member(conn, token, asset_id)
    try:
        path = safe_path(user, row["relpath"])
    except ValueError:
        raise ApiError(404, NOT_FOUND)
    if not path.is_file():
        raise ApiError(404, NOT_FOUND)
    # numele original ar spune data și telefonul: la descărcare primește doar id-ul
    return FileResponse(path, filename=f"amintiri-{row['id']}{path.suffix.lower()}",
                        content_disposition_type="inline")


@router.get("/a/{token}", include_in_schema=False)
def public_page(token: str, conn: sqlite3.Connection = Depends(get_db)):
    try:
        _album(conn, token)
        status = 200
    except ApiError:
        status = 404  # tot pagina, care spune omenește că linkul nu mai merge
    return FileResponse(WEB_DIR / "album.html", status_code=status, media_type="text/html",
                        headers={"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"})
