"""Favorite, detaliile unei poze, căutarea și coșul (listare, recuperare, ștergere definitivă)."""
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from . import i18n, naming, thumbs, trash, users
from .geo import english
from .auth import ApiError, current_user, get_db
from .library import NOT_FOUND, own_asset, paged
from .metadata import FMT, TZ

log = logging.getLogger(__name__)
router = APIRouter()

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_LIVE = "SELECT DISTINCT sha256 FROM assets WHERE user=? AND deleted_at IS NULL"


def _now() -> str:
    return datetime.now(TZ).strftime(FMT)


# ---------- favorite ----------
def _own_sha(conn, user: str, sha: str) -> None:
    if not _SHA_RE.match(sha) or conn.execute(
            "SELECT 1 FROM assets WHERE user=? AND sha256=? AND deleted_at IS NULL", (user, sha)).fetchone() is None:
        raise ApiError(404, NOT_FOUND)


@router.get("/api/favorites")
def favorites(user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(f"SELECT sha256 FROM favorites WHERE user=? AND sha256 IN ({_LIVE}) ORDER BY added_at",
                        (user, user))
    return {"sha256": [r[0] for r in rows]}


@router.get("/api/favorites/assets")
def favorite_assets(before: str | None = None, limit: int = Query(200, ge=1, le=500),
                    user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return paged(conn, user, before, limit, "AND sha256 IN (SELECT sha256 FROM favorites WHERE user=?)", (user,))


@router.put("/api/favorites/{sha}", status_code=204)
def add_favorite(sha: str, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _own_sha(conn, user, sha)
    conn.execute("INSERT OR IGNORE INTO favorites(user, sha256, added_at) VALUES(?,?,?)", (user, sha, _now()))
    conn.commit()
    return Response(status_code=204)


@router.delete("/api/favorites/{sha}", status_code=204)
def remove_favorite(sha: str, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM favorites WHERE user=? AND sha256=?", (user, sha))
    conn.commit()
    return Response(status_code=204)


# ---------- detalii ----------
def camera_of(path: Path) -> str | None:
    """„Samsung SM-S918B” din EXIF; None la clipuri sau fără EXIF."""
    try:
        with Image.open(path) as im:
            ex = im.getexif()
    except Exception:
        return None
    make = str(ex.get(0x010F) or "").strip(" \x00")
    model = str(ex.get(0x0110) or "").strip(" \x00")
    if not model:
        return make.title() or None
    if not make or model.lower().startswith(make.lower()):
        return model
    return f"{make.title() if make.islower() else make} {model}"


@router.get("/api/assets/{asset_id}/info")
async def info(asset_id: int, req: Request, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    row = await run_in_threadpool(own_asset, conn, user, asset_id)
    rel = Path(row["relpath"])
    camera = None
    if row["kind"] == "photo":
        try:
            camera = await run_in_threadpool(camera_of, users.safe_path(user, row["relpath"]))
        except ValueError:
            pass
    place = None
    if row["place_id"]:
        p = conn.execute("SELECT * FROM places WHERE id=?", (row["place_id"],)).fetchone()
        if p:
            place = {"id": p["id"], **i18n.place(p, req)}
    fav = conn.execute("SELECT 1 FROM favorites WHERE user=? AND sha256=?", (user, row["sha256"])).fetchone()
    albums = conn.execute("SELECT a.id, a.name FROM albums a JOIN album_items i ON i.album_id=a.id"
                          " WHERE a.user=? AND i.sha256=? ORDER BY a.name", (user, row["sha256"])).fetchall()
    return {
        "id": row["id"], "filename": rel.name, "folder": "" if str(rel.parent) == "." else str(rel.parent),
        "size": row["size"], "width": row["width"], "height": row["height"], "duration_ms": row["duration_ms"],
        "taken_at": row["taken_at"], "kind": row["kind"], "source": row["source"], "camera": camera,
        "place": place, "lat": row["lat"], "lon": row["lon"], "favorite": fav is not None,
        "albums": [{"id": a["id"], "name": a["name"]} for a in albums],
    }


# ---------- căutare ----------
MONTHS = ["ianuarie", "februarie", "martie", "aprilie", "mai", "iunie", "iulie", "august",
          "septembrie", "octombrie", "noiembrie", "decembrie"]
MONTHS_EN = ["january", "february", "march", "april", "may", "june", "july", "august",
             "september", "october", "november", "december"]
SEASONS = {"primavara": [3, 4, 5], "vara": [6, 7, 8], "toamna": [9, 10, 11], "iarna": [12, 1, 2],
           "spring": [3, 4, 5], "summer": [6, 7, 8], "autumn": [9, 10, 11], "fall": [9, 10, 11], "winter": [12, 1, 2]}
_STOP = {"din", "in", "la", "de", "si", "pe", "poze", "pozele", "of", "from", "at", "the", "on", "photos", "pictures"}


def plain(s: str) -> str:
    """Fără diacritice și cu litere mici: „Constanța” → „constanta”."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c)).lower()


def _month(w: str) -> int | None:
    """Luna după început de nume, în română sau în engleză („mar” = martie, „feb”, „june”)."""
    for names in (MONTHS, MONTHS_EN):
        hits = [i + 1 for i, name in enumerate(names) if name.startswith(w)]
        if len(hits) == 1:
            return hits[0]
    return None


def parse_query(q: str) -> dict:
    """Desparte căutarea în an, luni (sau anotimp) și text liber (loc sau album)."""
    year, months, words, said = None, [], [], []
    for raw in q.split():
        w = plain(raw).strip(".,;")
        if re.fullmatch(r"(19|20)\d\d", w):
            year = int(w)
        elif w in SEASONS:
            months, said = SEASONS[w], said + [raw.lower()]
        elif len(w) >= 3 and (m := _month(w)):
            months, said = [m], said + [MONTHS[m - 1]]
        elif w not in _STOP:
            words.append(raw)
    return {"year": year, "months": months, "text": " ".join(words), "when": said}


def best(needle: str, rows, fields) -> list:
    """Potrivirile cele mai bune: numele exact, altfel începutul unui cuvânt, altfel orice bucată.
    Așa „roma” găsește Roma, nu și România."""
    rows = list(rows)
    texts = [[plain(f or "") for f in fields(r)] for r in rows]
    tests = (lambda t: t == needle,
             lambda t: re.search(rf"(^|[\s-]){re.escape(needle)}", t) is not None,
             lambda t: needle in t)
    for test in tests:
        hit = [r for r, ts in zip(rows, texts) if any(test(t) for t in ts)]
        if hit:
            return hit
    return []


@router.get("/api/search")
def search(req: Request, q: str = Query(max_length=100), before: str | None = None, limit: int = Query(200, ge=1, le=500),
           user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    if not q.strip():
        raise ApiError(422, "Scrie ce cauți.")
    p = parse_query(q)
    extra, params, label = "", [], []
    if p["text"]:
        needle = plain(p["text"])
        rows = conn.execute("SELECT DISTINCT p.* FROM places p JOIN assets a ON a.place_id=p.id"
                            " WHERE a.user=? AND a.deleted_at IS NULL", (user,)).fetchall()
        # și pe românește, și pe englezește: „Roma” și „Rome”, „Grecia” și „Greece”
        places = best(needle, rows, lambda r: [r["name"], r["region"], r["country"],
                                              english(r["name"]), english(r["country"] or "")])
        albums = [r["id"] for r in best(needle, conn.execute("SELECT id, name FROM albums WHERE user=?", (user,)),
                                        lambda r: [r["name"]])]
        if not places and not albums:
            return {"items": [], "next": None, "label": p["text"]}
        pids, marks_p = [r["id"] for r in places], ",".join("?" * len(places)) or "NULL"
        marks_a = ",".join("?" * len(albums)) or "NULL"
        extra += (f" AND (place_id IN ({marks_p})"
                  f" OR sha256 IN (SELECT sha256 FROM album_items WHERE album_id IN ({marks_a})))")
        params += pids + albums
        names = {i18n.place(r, req, ("name",))["name"] for r in places}
        label.append(names.pop() if len(names) == 1 and not albums else p["text"])
    if p["months"]:
        extra += f" AND CAST(substr(taken_at, 6, 2) AS INTEGER) IN ({','.join('?' * len(p['months']))})"
        params += p["months"]
    if p["year"]:
        extra += " AND substr(taken_at, 1, 4)=?"
        params.append(f"{p['year']:04}")
    when = " ".join(p["when"] + ([str(p["year"])] if p["year"] else []))
    if when:
        label.append(when)
    if not extra:
        return {"items": [], "next": None, "label": q.strip()}
    return {**paged(conn, user, before, limit, extra, tuple(params)), "label": " · ".join(label)}


@router.get("/api/search/suggestions")
def suggestions(req: Request, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    places = conn.execute(
        "SELECT p.id, p.name, p.country, COUNT(DISTINCT a.sha256) n FROM places p JOIN assets a ON a.place_id=p.id"
        " WHERE a.user=? AND a.deleted_at IS NULL GROUP BY p.id ORDER BY n DESC, p.name LIMIT 12", (user,)).fetchall()
    years = conn.execute("SELECT DISTINCT CAST(substr(taken_at, 1, 4) AS INTEGER) y FROM assets"
                         " WHERE user=? AND deleted_at IS NULL ORDER BY y DESC", (user,)).fetchall()
    return {"places": [{"id": r["id"], **i18n.place(r, req, ("name", "country")), "count": r["n"]} for r in places],
            "years": [r["y"] for r in years]}


# ---------- coș ----------
class Ids(BaseModel):
    ids: list[int] = Field(max_length=5000)


def _trash_rows(conn, user: str):
    return conn.execute(
        "SELECT t.*, a.sha256, a.taken_at, a.kind, a.width, a.height, a.duration_ms, a.source"
        " FROM trash t JOIN assets a ON a.id=t.asset_id"
        " WHERE t.user=? AND a.deleted_at IS NOT NULL ORDER BY t.deleted_at DESC, t.id DESC", (user,)).fetchall()


@router.get("/api/trash")
def trash_list(user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    today = datetime.now(TZ).date()
    seen, items = set(), []
    for r in _trash_rows(conn, user):
        if r["sha256"] in seen:
            continue
        seen.add(r["sha256"])
        gone = (today - datetime.strptime(r["deleted_at"], FMT).date()).days
        items.append({"id": r["asset_id"], "sha256": r["sha256"], "taken_at": r["taken_at"], "kind": r["kind"],
                      "width": r["width"], "height": r["height"], "duration_ms": r["duration_ms"],
                      "source": r["source"], "deleted_at": r["deleted_at"],
                      "days_left": max(0, trash.KEEP_DAYS - gone)})
    return {"items": items}


@router.get("/api/trash/{asset_id}/thumb")
async def trash_thumb(asset_id: int, size: int = 256, user: str = Depends(current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    if size not in thumbs.SIZES:
        raise ApiError(422, "Cerere invalidă.")
    r = conn.execute("SELECT t.trash_relpath, a.sha256, a.kind FROM trash t JOIN assets a ON a.id=t.asset_id"
                     " WHERE t.user=? AND t.asset_id=? AND a.deleted_at IS NOT NULL", (user, asset_id)).fetchone()
    if r is None or not r["trash_relpath"]:
        raise ApiError(404, NOT_FOUND)
    fake = {"sha256": r["sha256"], "user": user, "relpath": r["trash_relpath"], "kind": r["kind"]}
    try:
        path = await run_in_threadpool(thumbs.thumbnail, fake, size)
    except Exception as e:
        log.warning("miniatură din coș %s: %s", asset_id, e)
        raise ApiError(404, "Miniatura nu se poate face.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


def _copies(conn, user: str, ids: list[int]):
    """Toate rândurile din coș cu aceeași amprentă ca pozele alese (o poză are și copii vechi)."""
    shas = set()
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        shas |= {r[0] for r in conn.execute(
            f"SELECT a.sha256 FROM trash t JOIN assets a ON a.id=t.asset_id WHERE t.user=?"
            f" AND a.deleted_at IS NOT NULL AND t.asset_id IN ({','.join('?' * len(chunk))})", (user, *chunk))}
    return shas, [r for r in _trash_rows(conn, user) if r["sha256"] in shas]


@router.post("/api/trash/restore")
def trash_restore(body: Ids, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    shas, rows = _copies(conn, user, body.ids)
    uid = users.uid_of(user)
    for r in rows:
        rel = r["orig_relpath"]
        if r["trash_relpath"]:
            src = users.safe_path(user, r["trash_relpath"])
            if src.is_file():
                rel = trash._free_rel(user, r["orig_relpath"])
                naming._make_dirs(user, str(Path(rel).parent), uid)
                os.rename(src, users.safe_path(user, rel))
                trash._prune_dirs(user, src)
        conn.execute("UPDATE assets SET relpath=?, deleted_at=NULL WHERE id=?", (rel, r["asset_id"]))
        conn.execute("DELETE FROM trash WHERE id=?", (r["id"],))
    conn.commit()
    return {"restored": len(shas)}


@router.delete("/api/trash")
def trash_delete(body: Ids, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    shas, rows = _copies(conn, user, body.ids)
    for r in rows:
        if r["trash_relpath"]:
            try:
                path = users.safe_path(user, r["trash_relpath"])
                path.unlink(missing_ok=True)
                trash._prune_dirs(user, path)
            except (OSError, ValueError) as e:
                log.warning("ștergere definitivă %s: %s", r["trash_relpath"], e)
                continue
        conn.execute("DELETE FROM trash WHERE id=?", (r["id"],))
        conn.execute("DELETE FROM assets WHERE id=? AND deleted_at IS NOT NULL", (r["asset_id"],))
    conn.commit()
    return {"deleted": len(shas)}
