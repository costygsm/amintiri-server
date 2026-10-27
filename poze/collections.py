"""Locuri (din GPS) și albume (ale fiecărui utilizator; pozele nu se mută, albumul ține amprentele)."""
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator

from . import i18n
from .auth import ApiError, current_user, get_db
from .library import paged

router = APIRouter()
ALBUM_NOT_FOUND = "Albumul nu există."

# o poză vie = un rând nesters al utilizatorului; numărăm amprente, nu copii
_LIVE = "SELECT DISTINCT sha256 FROM assets WHERE user=? AND deleted_at IS NULL"


@router.get("/api/places")
def places(req: Request, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("""
        WITH u AS (
          SELECT id, place_id, taken_at, ROW_NUMBER() OVER (PARTITION BY sha256 ORDER BY id) AS rn
          FROM assets WHERE user=? AND deleted_at IS NULL AND place_id IS NOT NULL),
        c AS (
          SELECT place_id, COUNT(*) AS n,
                 (SELECT id FROM u u2 WHERE u2.place_id=u.place_id AND rn=1
                  ORDER BY taken_at DESC, id DESC LIMIT 1) AS cover
          FROM u WHERE rn=1 GROUP BY place_id)
        SELECT p.*, c.n, c.cover FROM c JOIN places p ON p.id=c.place_id
        ORDER BY c.n DESC, p.name""", (user,)).fetchall()
    return {"places": [{"id": r["id"], **i18n.place(r, req),
                        "lat": r["lat"], "lon": r["lon"], "count": r["n"], "cover_id": r["cover"]} for r in rows]}


@router.get("/api/places/{place_id}/assets")
def place_assets(place_id: int, before: str | None = None, limit: int = Query(200, ge=1, le=500),
                 user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return paged(conn, user, before, limit, "AND place_id=?", (place_id,))


class NameBody(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v or len(v) > 100:
            raise ValueError("Numele albumului are între 1 și 100 de caractere.")
        return v


class NewAlbum(NameBody):
    sha256: list[str] = Field(default_factory=list, max_length=5000)


class Items(BaseModel):
    sha256: list[str] = Field(max_length=5000)


def _album_json(conn, user: str, album_id: int) -> dict:
    a = conn.execute("SELECT * FROM albums WHERE id=? AND user=?", (album_id, user)).fetchone()
    if a is None:
        raise ApiError(404, ALBUM_NOT_FOUND)
    n = conn.execute(f"SELECT COUNT(*) FROM album_items WHERE album_id=? AND sha256 IN ({_LIVE})",
                     (album_id, user)).fetchone()[0]
    cover = paged(conn, user, None, 1, "AND sha256 IN (SELECT sha256 FROM album_items WHERE album_id=?)",
                  (album_id,))["items"]
    link = conn.execute("SELECT token FROM album_links WHERE album_id=?", (album_id,)).fetchone()
    return {"id": a["id"], "name": a["name"], "count": n, "cover_id": cover[0]["id"] if cover else None,
            "link": link[0] if link else None}


def _add(conn, user: str, album_id: int, shas: list[str]) -> None:
    # doar amprentele pozelor lui: un album nu poate „vedea” pozele altcuiva
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i in range(0, len(shas), 500):
        chunk = shas[i:i + 500]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"INSERT OR IGNORE INTO album_items(album_id, sha256, added_at) "
                     f"SELECT ?, sha256, ? FROM ({_LIVE}) WHERE sha256 IN ({marks})",
                     (album_id, now, user, *chunk))


def _own(conn, user: str, album_id: int) -> None:
    if conn.execute("SELECT 1 FROM albums WHERE id=? AND user=?", (album_id, user)).fetchone() is None:
        raise ApiError(404, ALBUM_NOT_FOUND)


@router.get("/api/albums")
def albums(user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    ids = [r[0] for r in conn.execute("SELECT id FROM albums WHERE user=? ORDER BY created_at DESC, id DESC", (user,))]
    return {"albums": [_album_json(conn, user, i) for i in ids]}


@router.post("/api/albums")
def create_album(body: NewAlbum, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    aid = conn.execute("INSERT INTO albums(user, name, created_at) VALUES(?,?,?)", (user, body.name, now)).lastrowid
    _add(conn, user, aid, body.sha256)
    conn.commit()
    return {"album": _album_json(conn, user, aid)}


@router.patch("/api/albums/{album_id}")
def rename_album(album_id: int, body: NameBody, user: str = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    conn.execute("UPDATE albums SET name=? WHERE id=?", (body.name, album_id))
    conn.commit()
    return {"album": _album_json(conn, user, album_id)}


@router.delete("/api/albums/{album_id}")
def delete_album(album_id: int, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    conn.execute("DELETE FROM album_items WHERE album_id=?", (album_id,))
    conn.execute("DELETE FROM album_links WHERE album_id=?", (album_id,))
    conn.execute("DELETE FROM albums WHERE id=?", (album_id,))
    conn.commit()
    return {"ok": True}


@router.post("/api/albums/{album_id}/items")
def add_items(album_id: int, body: Items, user: str = Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    _add(conn, user, album_id, body.sha256)
    conn.commit()
    return {"album": _album_json(conn, user, album_id)}


@router.delete("/api/albums/{album_id}/items")
def remove_items(album_id: int, body: Items, user: str = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    for i in range(0, len(body.sha256), 500):
        chunk = body.sha256[i:i + 500]
        conn.execute(f"DELETE FROM album_items WHERE album_id=? AND sha256 IN ({','.join('?' * len(chunk))})",
                     (album_id, *chunk))
    conn.commit()
    return {"album": _album_json(conn, user, album_id)}


@router.get("/api/albums/{album_id}/assets")
def album_assets(album_id: int, before: str | None = None, limit: int = Query(200, ge=1, le=500),
                 user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    return paged(conn, user, before, limit, "AND sha256 IN (SELECT sha256 FROM album_items WHERE album_id=?)",
                 (album_id,))
