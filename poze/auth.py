import hashlib
import logging
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Literal

import httpx
from fastapi import Depends, Header, Request

from . import db, users
from .config import get_settings

log = logging.getLogger("poze.auth")

_transport: httpx.BaseTransport | None = None  # injectat în teste
_last_code: int | str | None = None  # ultimul refuz DSM, pentru jurnal
# un cont obișnuit (nu administrator) primește 402 la o sesiune care nu e a unei aplicații DSM;
# „webui” e aplicația DSM însăși, pe care contul trebuie s-o aibă la Application Privileges
DSM_SESSION = "webui"
_USER_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
MAX_BAD = 5
WINDOW = 15 * 60
_attempts: dict[tuple[str, str], list[float]] = {}  # (ip, user) -> momente ale răspunsurilor „bad”
COOKIE = "poze_sesiune"
WEB_DAYS = 30  # o sesiune de browser nefolosită atâtea zile expiră; tokenurile aplicației nu
CSRF_HEADER = "x-poze"  # cerut la scrierile cu cookie: un alt site nu-l poate pune fără preflight


class ApiError(Exception):
    def __init__(self, status: int, error: str, **extra):
        self.status, self.body = status, {"error": error, **extra}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def valid_user(user: str) -> bool:
    if not _USER_RE.match(user) or user in (".", ".."):
        return False
    try:
        users.uid_of(user)
    except KeyError:
        return False
    return True


def last_dsm_code():
    return _last_code


def dsm_check(user: str, password: str, otp: str | None) -> Literal["ok", "need_otp", "denied", "bad"]:
    """Verifică contul la DSM. Credențialele merg ca parametri GET (cerința API-ului DSM); nu se loghează."""
    global _last_code
    url = get_settings().dsm_url.rstrip("/") + "/webapi/entry.cgi"
    params = {
        "api": "SYNO.API.Auth", "version": "6", "method": "login",
        "account": user, "passwd": password, "session": DSM_SESSION, "format": "sid",
    }
    if otp:
        params["otp_code"] = otp
    try:
        with httpx.Client(transport=_transport, timeout=10) as c:
            data = c.get(url, params=params).json()
            if data.get("success"):
                sid = data["data"]["sid"]
                try:
                    c.get(url, params={"api": "SYNO.API.Auth", "version": "6", "method": "logout",
                                       "session": DSM_SESSION, "_sid": sid})
                except httpx.HTTPError:
                    log.warning("DSM: logout eșuat")
                return "ok"
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("DSM: cerere eșuată (%s)", type(e).__name__)
        _last_code = type(e).__name__
        return "bad"
    code = _last_code = (data.get("error") or {}).get("code")
    if code == 403:
        return "need_otp"
    if code == 402:
        return "denied"
    if code not in (400, 404):
        log.warning("DSM: cod de eroare necunoscut %s", code)
    return "bad"


def issue_token(conn: sqlite3.Connection, user: str, device: str, web: bool = False) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute("insert into tokens(hash,user,device,created_at,last_used,web) values(?,?,?,?,?,?)",
                 (_hash(token), user, device, now, now, int(web)))
    conn.commit()
    return token


def revoke_token(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("delete from tokens where hash=?", (_hash(token),))
    conn.commit()


def get_db():
    conn = db.connect(get_settings().data_dir)
    try:
        yield conn
    finally:
        conn.close()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _recent(key) -> list[float]:
    cutoff = time.monotonic() - WINDOW
    lst = [t for t in _attempts.get(key, []) if t > cutoff]
    if lst:
        _attempts[key] = lst
    else:
        _attempts.pop(key, None)
    return lst


def check_rate(ip: str, user: str) -> None:
    if len(_recent((ip, user))) >= MAX_BAD:
        raise ApiError(429, "Prea multe încercări. Încearcă din nou peste 15 minute.")


def record_bad(ip: str, user: str) -> None:
    _recent((ip, user))
    _attempts.setdefault((ip, user), []).append(time.monotonic())


def browser_label(ua: str) -> str:
    """„Browser: Firefox pe Linux”, ca să se recunoască sesiunea în lista de dispozitive."""
    name = next((n for k, n in (("Edg/", "Edge"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"),
                                ("Safari/", "Safari")) if k in ua), None)
    system = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"),
                                  ("Windows", "Windows"), ("Mac OS X", "Mac"), ("Linux", "Linux")) if k in ua), None)
    if not name:
        return "Browser"
    return f"Browser: {name}" + (f" pe {system}" if system else "")


def bearer_token(request: Request, authorization: str | None = Header(default=None)) -> str:
    if authorization and authorization.lower().startswith("bearer ") and authorization[7:].strip():
        return authorization[7:].strip()
    cookie = request.cookies.get(COOKIE)
    if cookie:
        if request.method not in ("GET", "HEAD") and request.headers.get(CSRF_HEADER) != "1":
            raise ApiError(403, "Cerere respinsă.")
        return cookie
    raise ApiError(401, "Autentificare necesară.")


def current_user(token: str = Depends(bearer_token), conn: sqlite3.Connection = Depends(get_db)) -> str:
    row = conn.execute("select user, web, last_used from tokens where hash=?", (_hash(token),)).fetchone()
    if row is not None and row["web"]:
        idle_limit = (datetime.now() - timedelta(days=WEB_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
        if row["last_used"] < idle_limit:
            revoke_token(conn, token)
            row = None
    if row is None:
        raise ApiError(401, "Autentificare necesară.")
    conn.execute("update tokens set last_used=? where hash=?", (_now(), _hash(token)))
    conn.commit()
    return row["user"]
