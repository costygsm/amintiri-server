"""Proiectarea pe televizor (Google Cast): adresa pe care o deschide televizorul, fără cont.

Telefonul trimite televizorului doar o adresă; televizorul n-are tokenul aplicației. Telefonul cere
deci, cu tokenul, o adresă semnată pentru o singură poză, valabilă câteva ore. Semnătura leagă
contul, poza și ora de expirare: altă poză sau o adresă expirată nu se deschid.

Pozele pleacă la televizor ca JPEG de 1920 px (Chromecast nu afișează HEIC, iar originalul de
12–50 MP ar veni greu prin internet); clipurile pleacă așa cum sunt, cu derulare (Range).
"""
import hashlib
import hmac
import mimetypes
import sqlite3
import time

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from . import thumbs
from .auth import ApiError, current_user, get_db
from .lan import _secret
from .library import NOT_FOUND, visible_asset
from .users import safe_path

router = APIRouter()
VALID_SECONDS = 3 * 3600  # telefonul cere o adresă nouă la fiecare poză; ajunge și pentru un film lung
TV_SIZE = 1920
EXPIRED = "Adresa pentru televizor a expirat."
# televizorul e alt „site” decât al nostru: fără antetul ăsta, receptorul Cast refuză unele clipuri
CORS = {"Access-Control-Allow-Origin": "*"}


def _mime(name: str) -> str:
    # .mov de pe iPhone e de obicei H.264: ca „video/quicktime” receptorul Google îl poate refuza
    mime = mimetypes.guess_type(name)[0] or "video/mp4"
    return "video/mp4" if mime == "video/quicktime" else mime


def _sign(conn: sqlite3.Connection, user: str, asset_id: int, exp: int) -> str:
    msg = f"cast:{user}:{asset_id}:{exp}".encode()
    return hmac.new(_secret(conn), msg, hashlib.sha256).hexdigest()


@router.post("/api/cast/{asset_id}")
def cast_link(asset_id: int, user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Adresa (relativă la server) pe care telefonul o dă televizorului, cu tipul ei."""
    row = visible_asset(conn, user, asset_id)
    exp = int(time.time()) + VALID_SECONDS
    sig = _sign(conn, user, asset_id, exp)
    mime = _mime(row["relpath"]) if row["kind"] == "video" else "image/jpeg"
    return {"path": f"api/cast/{asset_id}/media?u={user}&e={exp}&s={sig}", "mime": mime, "kind": row["kind"]}


@router.get("/api/cast/{asset_id}/media")
def cast_media(asset_id: int, u: str, e: int, s: str, conn: sqlite3.Connection = Depends(get_db)):
    # funcție obișnuită: FastAPI o rulează pe un fir separat, cu tot cu SQLite și miniatura (nu blochează serverul)
    if not hmac.compare_digest(s, _sign(conn, u, asset_id, e)):
        raise ApiError(404, NOT_FOUND)
    if e < time.time():
        raise ApiError(410, EXPIRED)
    row = visible_asset(conn, u, asset_id)
    if row["kind"] == "video":
        try:
            path = safe_path(row["user"], row["relpath"])
        except ValueError:
            raise ApiError(404, NOT_FOUND)
        if not path.is_file():
            raise ApiError(404, NOT_FOUND)
        return FileResponse(path, media_type=_mime(path.name), headers=CORS)
    try:
        path = thumbs.thumbnail(row, TV_SIZE)
    except Exception:
        raise ApiError(404, "Poza nu se poate pregăti pentru televizor.")
    return FileResponse(path, media_type="image/jpeg", headers={**CORS, "Cache-Control": "private, max-age=3600"})
