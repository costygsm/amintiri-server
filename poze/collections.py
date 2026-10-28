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
          SELECT id, sha256, place_id, taken_at, ROW_NUMBER() OVER (PARTITION BY sha256 ORDER BY id) AS rn
          FROM assets WHERE user=? AND deleted_at IS NULL AND place_id IS NOT NULL),
        c AS (
          SELECT place_id, COUNT(*) AS n,
                 (SELECT id FROM u u2 WHERE u2.place_id=u.place_id AND rn=1
                  ORDER BY taken_at DESC, id DESC LIMIT 1) AS cover,
                 (SELECT sha256 FROM u u2 WHERE u2.place_id=u.place_id AND rn=1
                  ORDER BY taken_at DESC, id DESC LIMIT 1) AS cover_sha
          FROM u WHERE rn=1 GROUP BY place_id)
        SELECT p.*, c.n, c.cover, c.cover_sha FROM c JOIN places p ON p.id=c.place_id
        ORDER BY c.n DESC, p.name""", (user,)).fetchall()
    return {"places": [{"id": r["id"], **i18n.place(r, req),
                        "lat": r["lat"], "lon": r["lon"], "count": r["n"], "cover_id": r["cover"],
                        "cover_sha": r["cover_sha"]} for r in rows]}


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


# pozele din album, ale oricui le-a pus acolo (albumele comune au pozele mai multor conturi)
def in_album(album_id: int) -> tuple[str, tuple]:
    return "(user, sha256) IN (SELECT user, sha256 FROM album_items WHERE album_id=?)", (album_id,)


def _album_json(conn, user: str, album_id: int) -> dict:
    a = conn.execute("SELECT * FROM albums WHERE id=?", (album_id,)).fetchone()
    if a is None:
        raise ApiError(404, ALBUM_NOT_FOUND)
    n = conn.execute("SELECT COUNT(DISTINCT i.sha256) FROM album_items i JOIN assets s"
                     " ON s.user=i.user AND s.sha256=i.sha256 AND s.deleted_at IS NULL WHERE i.album_id=?",
                     (album_id,)).fetchone()[0]
    cover = paged(conn, user, None, 1, scope=in_album(album_id))["items"]
    link = conn.execute("SELECT token FROM album_links WHERE album_id=?", (album_id,)).fetchone()
    members = [r[0] for r in conn.execute("SELECT user FROM album_members WHERE album_id=? ORDER BY user", (album_id,))]
    return {"id": a["id"], "name": a["name"], "count": n, "cover_id": cover[0]["id"] if cover else None,
            "cover_sha": cover[0]["sha256"] if cover else None,
            "link": link[0] if link else None, "owner": a["user"], "mine": a["user"] == user, "members": members}


def _add(conn, user: str, album_id: int, shas: list[str]) -> None:
    # doar amprentele pozelor lui: fiecare pune în album numai ce e al lui
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for i in range(0, len(shas), 500):
        chunk = shas[i:i + 500]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"INSERT OR IGNORE INTO album_items(album_id, sha256, added_at, user) "
                     f"SELECT ?, sha256, ?, ? FROM ({_LIVE}) WHERE sha256 IN ({marks})",
                     (album_id, now, user, user, *chunk))


def _own(conn, user: str, album_id: int) -> None:
    """Doar proprietarul: redenumire, ștergere, membri, link public."""
    if conn.execute("SELECT 1 FROM albums WHERE id=? AND user=?", (album_id, user)).fetchone() is None:
        raise ApiError(404, ALBUM_NOT_FOUND)


def _role(conn, user: str, album_id: int) -> str:
    """„owner” sau „member”; 404 pentru oricine altcineva (nici nu aflăm că albumul există)."""
    a = conn.execute("SELECT user FROM albums WHERE id=?", (album_id,)).fetchone()
    if a is not None and a["user"] == user:
        return "owner"
    if a is not None and conn.execute("SELECT 1 FROM album_members WHERE album_id=? AND user=?",
                                      (album_id, user)).fetchone():
        return "member"
    raise ApiError(404, ALBUM_NOT_FOUND)


@router.get("/api/albums")
def albums(user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM albums WHERE user=? OR id IN (SELECT album_id FROM album_members WHERE user=?)"
        " ORDER BY created_at DESC, id DESC", (user, user))]
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
    conn.execute("DELETE FROM album_members WHERE album_id=?", (album_id,))
    conn.execute("DELETE FROM albums WHERE id=?", (album_id,))
    conn.commit()
    return {"ok": True}


@router.post("/api/albums/{album_id}/items")
def add_items(album_id: int, body: Items, user: str = Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    _role(conn, user, album_id)
    _add(conn, user, album_id, body.sha256)
    conn.commit()
    return {"album": _album_json(conn, user, album_id)}


@router.delete("/api/albums/{album_id}/items")
def remove_items(album_id: int, body: Items, user: str = Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    # proprietarul scoate orice; un membru doar ce a pus el, și i se spune dacă a ales și altceva
    only_mine = "" if _role(conn, user, album_id) == "owner" else " AND user=?"
    if only_mine:
        theirs = {r[0] for r in conn.execute("SELECT sha256 FROM album_items WHERE album_id=? AND user<>?", (album_id, user))}
        mine = {r[0] for r in conn.execute("SELECT sha256 FROM album_items WHERE album_id=? AND user=?", (album_id, user))}
        if any(s in theirs and s not in mine for s in body.sha256):
            raise ApiError(403, "Poți scoate doar pozele puse de tine.")
    for i in range(0, len(body.sha256), 500):
        chunk = body.sha256[i:i + 500]
        conn.execute(f"DELETE FROM album_items WHERE album_id=? AND sha256 IN ({','.join('?' * len(chunk))}){only_mine}",
                     (album_id, *chunk, *((user,) if only_mine else ())))
    conn.commit()
    return {"album": _album_json(conn, user, album_id)}


class Member(BaseModel):
    user: str = Field(max_length=64)


@router.get("/api/people")
def people(user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Cu cine poate împărți un album: conturile care au intrat măcar o dată în Amintiri."""
    rows = conn.execute("SELECT DISTINCT user FROM tokens WHERE user<>? ORDER BY user", (user,))
    return {"people": [r[0] for r in rows]}


@router.post("/api/albums/{album_id}/members")
def add_member(album_id: int, body: Member, user: str = Depends(current_user),
               conn: sqlite3.Connection = Depends(get_db)):
    _own(conn, user, album_id)
    known = conn.execute("SELECT 1 FROM tokens WHERE user=?", (body.user,)).fetchone()
    if body.user == user or known is None:
        raise ApiError(422, "Contul nu există sau n-a intrat încă în Amintiri.")
    conn.execute("INSERT OR IGNORE INTO album_members(album_id, user, added_at) VALUES(?,?,?)",
                 (album_id, body.user, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    return {"album": _album_json(conn, user, album_id)}


@router.delete("/api/albums/{album_id}/members/{member}")
def remove_member(album_id: int, member: str, user: str = Depends(current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    """Proprietarul scoate pe cineva, sau membrul pleacă singur. Pozele puse de el ies odată cu el."""
    if _role(conn, user, album_id) == "member" and member != user:
        raise ApiError(404, ALBUM_NOT_FOUND)
    if conn.execute("SELECT 1 FROM albums WHERE id=? AND user=?", (album_id, member)).fetchone():
        raise ApiError(422, "Proprietarul nu poate pleca din album; îl poate șterge.")
    conn.execute("DELETE FROM album_members WHERE album_id=? AND user=?", (album_id, member))
    conn.execute("DELETE FROM album_items WHERE album_id=? AND user=?", (album_id, member))
    conn.commit()
    return {"ok": True}


@router.get("/api/albums/{album_id}/assets")
def album_assets(album_id: int, before: str | None = None, limit: int = Query(200, ge=1, le=500),
                 user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _role(conn, user, album_id)
    return paged(conn, user, before, limit, scope=in_album(album_id))
