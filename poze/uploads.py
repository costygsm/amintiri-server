"""Uploadul în bucăți: pornire, reluare, bucăți de maxim 8 MiB, verificarea amprentei."""
import logging
import os
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import metadata, naming, users
from .auth import ApiError, current_user, get_db
from .config import get_settings
from .db import asset_json
from .metadata import FMT, TZ
from .users import photos_root

log = logging.getLogger(__name__)
router = APIRouter()

CHUNK_MAX = 8 * 1024 * 1024
STALE_AFTER = 7 * 86400
_SHA_RE = r"^[0-9a-f]{64}$"
_ID_RE = re.compile(r"^[0-9a-f]{32}$")

NOT_FOUND = "Uploadul nu există."
INCOMPLETE = "Fișierul a ajuns incomplet. Se trimite din nou."
TOO_BIG = "Bucata depășește 8 MiB sau dimensiunea anunțată."

# un singur proces (uvicorn cu un worker): blocările din memorie ajung
_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(user: str, sha: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault((user, sha), threading.Lock())


class StartBody(BaseModel):
    sha256: str = Field(pattern=_SHA_RE)
    size: int = Field(gt=0)
    filename: str = Field(min_length=1, max_length=255)
    source: str = Field(default="", max_length=100)
    taken_at_hint_ms: int | None = Field(default=None, ge=0, le=4_102_444_800_000)  # până în 2100


class CheckBody(BaseModel):
    sha256: list[str] = Field(max_length=500)


def _ext(filename: str) -> str | None:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext if metadata.kind_of(Path(filename)) else None


def _incoming(user: str) -> Path:
    return photos_root(user) / ".incoming"


def _part(user: str, row) -> Path:
    # extensia la final, ca read_media_info să recunoască tipul
    return _incoming(user) / f"{row['id']}.part.{_ext(row['filename'])}"


def _live_asset(conn, user: str, sha: str):
    return conn.execute(
        "SELECT * FROM assets WHERE user=? AND sha256=? AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (user, sha)).fetchone()


def _upload(conn, user: str, upload_id: str):
    row = None
    if _ID_RE.match(upload_id):
        row = conn.execute("SELECT * FROM uploads WHERE id=? AND user=?", (upload_id, user)).fetchone()
    if row is None:
        raise ApiError(404, NOT_FOUND)
    return row


def _drop(conn, user: str, row) -> None:
    conn.execute("DELETE FROM uploads WHERE id=?", (row["id"],))
    conn.commit()
    try:
        _part(user, row).unlink()
    except FileNotFoundError:
        pass


NO_HOME = ("Contul n-are folder personal pe NAS, deci n-am unde pune pozele. În DSM: Control Panel → "
           "User & Group → Advanced → User Home → Enable user home service.")

@router.post("/api/check")
def check(body: CheckBody, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    wanted = list(dict.fromkeys(body.sha256))
    if not wanted:
        return {"present": []}
    marks = ",".join("?" * len(wanted))
    found = {r[0] for r in conn.execute(
        f"SELECT DISTINCT sha256 FROM assets WHERE user=? AND deleted_at IS NULL AND sha256 IN ({marks})",
        (user, *wanted))}
    return {"present": [s for s in wanted if s in found]}


@router.post("/api/uploads")
def start(body: StartBody, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    if _ext(body.filename) is None:
        raise ApiError(415, "Tip de fișier neacceptat.")
    with _lock(user, body.sha256):
        asset = _live_asset(conn, user, body.sha256)
        if asset:
            return {"exists": True, "asset": asset_json(asset)}
        row = conn.execute("SELECT * FROM uploads WHERE user=? AND sha256=?",
                           (user, body.sha256)).fetchone()
        if row and row["size"] == body.size:
            return {"exists": False, "upload_id": row["id"], "offset": row["offset"]}
        if row:  # aceeași amprentă cu altă dimensiune: clientul greșește, o luăm de la capăt
            _drop(conn, user, row)
        users.ensure_photos(user)  # un cont care n-a intrat niciodată: Photos se face acum, al lui
        if not photos_root(user).is_dir():
            raise ApiError(409, NO_HOME)
        upload_id = secrets.token_hex(16)
        conn.execute(
            "INSERT INTO uploads(id,user,sha256,size,filename,source,hint_ms,offset,created_at)"
            " VALUES(?,?,?,?,?,?,?,0,?)",
            (upload_id, user, body.sha256, body.size, body.filename, body.source,
             body.taken_at_hint_ms, datetime.now(TZ).strftime(FMT)))
        conn.commit()
        return {"exists": False, "upload_id": upload_id, "offset": 0}


@router.get("/api/uploads/{upload_id}")
def status(upload_id: str, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return {"offset": _upload(conn, user, upload_id)["offset"]}


def _write(conn, user: str, upload_id: str, offset: int, data: bytes) -> int:
    row = _upload(conn, user, upload_id)
    with _lock(user, row["sha256"]):
        row = _upload(conn, user, upload_id)
        if offset != row["offset"]:
            raise ApiError(409, "Bucata nu continuă de unde a rămas uploadul.", offset=row["offset"])
        if offset + len(data) > row["size"]:
            raise ApiError(413, TOO_BIG)
        part = _part(user, row)
        part.parent.mkdir(exist_ok=True)
        with open(part, "r+b" if part.exists() else "wb") as f:
            f.seek(offset)
            f.write(data)
            f.truncate()  # resturi dintr-o scriere neconfirmată înainte de o cădere
            f.flush()
            os.fsync(f.fileno())
        new = offset + len(data)
        conn.execute("UPDATE uploads SET offset=? WHERE id=?", (new, upload_id))
        conn.commit()
        return new


@router.put("/api/uploads/{upload_id}")
async def put_chunk(upload_id: str, offset: int, request: Request, user: str = Depends(current_user),
                    conn: sqlite3.Connection = Depends(get_db)):
    if int(request.headers.get("content-length") or 0) > CHUNK_MAX:
        raise ApiError(413, TOO_BIG)
    buf = bytearray()
    async for piece in request.stream():
        buf += piece
        if len(buf) > CHUNK_MAX:
            raise ApiError(413, TOO_BIG)
    return {"offset": await run_in_threadpool(_write, conn, user, upload_id, offset, bytes(buf))}


@router.post("/api/uploads/{upload_id}/finish")
def finish(upload_id: str, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    row = _upload(conn, user, upload_id)
    with _lock(user, row["sha256"]):
        row = _upload(conn, user, upload_id)
        part = _part(user, row)
        ok = (row["offset"] == row["size"] and part.is_file() and part.stat().st_size == row["size"]
              and metadata.sha256_file(part) == row["sha256"])
        if not ok:
            _drop(conn, user, row)
            raise ApiError(422, INCOMPLETE)
        asset = _live_asset(conn, user, row["sha256"])
        if asset is None:
            asset = _place(conn, user, row, part)
        else:
            part.unlink()
        conn.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
        conn.commit()
        return {"asset": asset_json(asset)}


def _place(conn, user: str, row, part: Path):
    info = metadata.read_media_info(part)
    hint = row["hint_ms"]
    if info.taken_at or hint is not None:
        taken = metadata.resolve_taken_at(info, part, hint, name=row["filename"])
    else:  # partea n-are numele original: data din nume (WhatsApp) se ia din filename
        taken = metadata.taken_at_from_name(row["filename"]) or metadata.resolve_taken_at(info, part, None)
    source = naming.clean_source(row["source"])
    rel = naming.place_file(user, part, taken, source, _ext(row["filename"]))
    st = (photos_root(user) / rel).stat()
    conn.execute(
        "INSERT INTO assets(user, relpath, sha256, size, mtime, taken_at, kind, width, height,"
        " duration_ms, source) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(user, relpath) DO UPDATE SET sha256=excluded.sha256, size=excluded.size,"
        " mtime=excluded.mtime, taken_at=excluded.taken_at, kind=excluded.kind,"
        " width=excluded.width, height=excluded.height, duration_ms=excluded.duration_ms,"
        " source=excluded.source, deleted_at=NULL",
        (user, rel, row["sha256"], st.st_size, st.st_mtime, taken, info.kind, info.width,
         info.height, info.duration_ms, source))
    return conn.execute("SELECT * FROM assets WHERE user=? AND relpath=?", (user, rel)).fetchone()


def cleanup_stale(conn, now: float | None = None) -> int:
    """Șterge uploadurile începute de peste 7 zile și părțile orfane din `.incoming`."""
    now = time.time() if now is None else now
    cutoff = datetime.fromtimestamp(now - STALE_AFTER, TZ).strftime(FMT)
    removed = 0
    for row in conn.execute("SELECT * FROM uploads WHERE created_at < ?", (cutoff,)).fetchall():
        _drop(conn, row["user"], row)
        removed += 1
    live = {r[0] for r in conn.execute("SELECT id FROM uploads")}
    for incoming in get_settings().homes_root.glob("*/Photos/.incoming"):
        for f in incoming.iterdir():
            try:
                if f.name.split(".")[0] not in live and f.stat().st_mtime < now - STALE_AFTER:
                    f.unlink()
                    removed += 1
            except OSError as e:
                log.warning("curățare %s: %s", f, e)
    return removed
