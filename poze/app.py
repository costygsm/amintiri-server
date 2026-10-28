import hashlib
import json
import logging
import shutil
import sqlite3
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import API_LEVEL, __version__, auth, collections, db, extras, i18n, indexer, lan, library, share, updates, uploads, users
from .config import get_settings

WEB_DIR = Path(__file__).parent / "web"


def _error_log() -> logging.Logger:
    log = logging.getLogger("poze.erori")
    path = get_settings().data_dir / "erori.log"
    if log.handlers and log.handlers[0].baseFilename != str(path.absolute()):
        log.removeHandler(log.handlers[0])  # alt folder de date (în teste)
    if not log.handlers:
        from logging.handlers import RotatingFileHandler

        path.parent.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        log.addHandler(h)
    return log
# fără scripturi sau stiluri inline și fără nimic de pe alte domenii
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; "
                               "connect-src 'self'; style-src 'self'; script-src 'self'; object-src 'none'; "
                               "base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

BAD_CREDENTIALS = "Utilizator sau parolă greșită."


@lru_cache(maxsize=1)
def _versioned_index() -> str:
    """index.html cu `?v=<amprentă>` la app.js și style.css: Cloudflare ține fișierele .js/.css ore întregi,
    iar o adresă nouă la fiecare versiune ocolește orice cache vechi."""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for name in ("app.js", "style.css"):
        v = hashlib.sha256((WEB_DIR / name).read_bytes()).hexdigest()[:12]
        html = html.replace(f'"{name}"', f'"{name}?v={v}"')
    return html


class LoginBody(BaseModel):
    user: str
    password: str
    otp: str | None = None
    device: str = ""


def create_app(start_indexer: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        try:
            conn = db.connect(get_settings().data_dir)
            try:
                uploads.cleanup_stale(conn)
            finally:
                conn.close()
        except Exception:
            logging.getLogger(__name__).exception("curățarea uploadurilor vechi a eșuat")
        if start_indexer:
            indexer.start_background(get_settings())
        yield

    app = FastAPI(lifespan=lifespan)

    @app.exception_handler(auth.ApiError)
    async def _api_error(req: Request, exc: auth.ApiError):
        return JSONResponse(i18n.localize(exc.body, req), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(req: Request, exc: StarletteHTTPException):
        return JSONResponse(i18n.localize({"error": str(exc.detail)}, req), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(req: Request, exc: Exception):
        # jurnalul containerului nu se poate citi de pe NAS: erorile neprevăzute merg și în data/erori.log
        _error_log().error("%s %s", req.method, req.url.path, exc_info=exc)
        return JSONResponse(i18n.localize({"error": "Eroare pe server. Încearcă din nou peste un minut."}, req),
                            status_code=500)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(req: Request, _exc):
        return JSONResponse(i18n.localize({"error": "Cerere invalidă."}, req), status_code=422)

    @app.get("/api/health")
    def health():
        # "api" crește doar când aplicația are nevoie de ceva nou de la server; aplicația cere un minim
        return {"ok": True, "version": __version__, "api": API_LEVEL}

    def check_login(body: LoginBody, request: Request) -> None:
        ip = auth.client_ip(request)
        auth.check_rate(ip, body.user)
        if not auth.valid_user(body.user):
            body.user = users.canonical(body.user)
        if not auth.valid_user(body.user):
            auth.record_bad(ip, body.user)
            raise auth.ApiError(401, BAD_CREDENTIALS)
        result = auth.dsm_check(body.user, body.password, body.otp)
        if result == "need_otp":
            raise auth.ApiError(401, "Introdu codul din aplicația de autentificare.", need_otp=True)
        if result == "denied":
            _error_log().warning("logare refuzată de DSM: %s (fără drept la aplicația DSM)", body.user)
            raise auth.ApiError(403, "Contul n-are voie să folosească DSM. În DSM: Control Panel → User & Group → "
                                     "contul → Applications → DSM: Allow.")
        if result == "bad":
            _error_log().warning("logare refuzată de DSM: %s (%s)", body.user, auth.last_dsm_code())
            auth.record_bad(ip, body.user)
            raise auth.ApiError(401, "Cod greșit." if body.otp else BAD_CREDENTIALS)
        users.ensure_photos(body.user)

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, conn: sqlite3.Connection = Depends(auth.get_db)):
        check_login(body, request)
        return {"token": auth.issue_token(conn, body.user, body.device), "user": body.user, "api": API_LEVEL}

    @app.post("/api/web/login")
    def web_login(body: LoginBody, request: Request, conn: sqlite3.Connection = Depends(auth.get_db)):
        """Ca /api/login, dar tokenul stă într-un cookie HttpOnly, nu ajunge la JavaScript."""
        check_login(body, request)
        token = auth.issue_token(conn, body.user, auth.browser_label(request.headers.get("user-agent", "")), web=True)
        r = JSONResponse({"user": body.user})
        # prin proxy-ul DSM e HTTPS; direct acasă e http, unde un cookie Secure nu s-ar mai întoarce
        r.set_cookie(auth.COOKIE, token, max_age=auth.WEB_DAYS * 86400, path="/",
                     httponly=True, secure=not lan.direct(request.scope), samesite="strict")
        return r

    @app.post("/api/logout", status_code=204)
    def logout(request: Request, token: str = Depends(auth.bearer_token), _user: str = Depends(auth.current_user),
               conn: sqlite3.Connection = Depends(auth.get_db)):
        auth.revoke_token(conn, token)
        r = Response(status_code=204)
        r.delete_cookie(auth.COOKIE, path="/", httponly=True, secure=not lan.direct(request.scope), samesite="strict")
        return r

    @app.get("/api/me")
    def me(user: str = Depends(auth.current_user)):
        return {"user": user}

    @app.get("/api/stats")
    def stats(user: str = Depends(auth.current_user), conn: sqlite3.Connection = Depends(auth.get_db)):
        """Pentru „Despre” din aplicație: ce are omul pe NAS și cât loc mai e."""
        row = conn.execute("SELECT SUM(kind='photo'), SUM(kind='video'), COALESCE(SUM(size), 0) FROM assets "
                           "WHERE user=? AND deleted_at IS NULL", (user,)).fetchone()
        try:
            disk = shutil.disk_usage(users.photos_root(user).parent)
            free, total = disk.free, disk.total
        except OSError:
            free = total = None
        return {"photos": row[0] or 0, "videos": row[1] or 0, "bytes": row[2], "free_bytes": free, "total_bytes": total}

    @app.get("/api/app/latest")
    def app_latest():
        # publice: linkul e pe pagina de logare, pentru telefonul care încă n-are aplicația; APK-ul n-are
        # nimic secret, iar fără un cont pe NAS aplicația nu face nimic
        try:
            info = json.loads((get_settings().data_dir / "apk" / "latest.json").read_text())
            return {"version_code": int(info["version_code"]), "version_name": str(info["version_name"]),
                    "url": "/api/app/apk"}
        except (OSError, ValueError, KeyError, TypeError):
            raise auth.ApiError(404, "Nu există nicio versiune publicată.")

    @app.get("/api/app/apk")
    def app_apk():
        apk = get_settings().data_dir / "apk" / "amintiri.apk"
        if not apk.is_file():
            raise auth.ApiError(404, "Nu există nicio versiune publicată.")
        return FileResponse(apk, media_type="application/vnd.android.package-archive",
                            filename="amintiri.apk")

    app.include_router(uploads.router)
    app.include_router(library.router)
    app.include_router(collections.router)
    app.include_router(extras.router)
    app.include_router(share.router)
    app.include_router(lan.router)
    app.include_router(updates.router)

    # pagina web, după API, ca /api/* să nu ajungă niciodată la fișierele statice
    @app.get("/api/{rest:path}", include_in_schema=False)
    def _no_api(rest: str):
        raise auth.ApiError(404, "Nu există.")

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    def _index():
        return HTMLResponse(_versioned_index())

    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        r = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            r.headers.setdefault(k, v)
        if not request.url.path.startswith("/api/"):
            # pagina web: fără asta Cloudflare îi spune browserului s-o țină 4 ore, deci o actualizare nu se vede;
            # cu no-cache browserul întreabă la fiecare deschidere și primește 304 dacă nu s-a schimbat
            r.headers.setdefault("Cache-Control", "no-cache")
        return r

    app.middleware("http")(lan.only_from_lan)  # ultimul adăugat = primul care vede cererea
    return app


app = create_app()
