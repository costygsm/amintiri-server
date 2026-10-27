"""Drumul direct prin rețeaua de acasă: telefonul urcă pozele la NAS fără să treacă prin internet.

Telefonul află adresa locală (cu tokenul, prin adresa publică), apoi, pe Wi-Fi, întreabă adresa locală
„dovedește că ești NAS-ul meu" cu un nonce. Doar serverul adevărat știe cheia, deci un alt aparat
cu aceeași adresă dintr-o altă rețea nu primește niciodată tokenul.
"""
import hashlib
import hmac
import ipaddress
import os
import secrets
import socket
import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from .auth import ApiError, current_user, get_db
from .config import get_settings

router = APIRouter()


def _secret(conn: sqlite3.Connection) -> bytes:
    row = conn.execute("SELECT value FROM meta WHERE key='lan_secret'").fetchone()
    if row:
        return bytes.fromhex(row[0])
    key = secrets.token_bytes(32)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('lan_secret', ?)", (key.hex(),))
    conn.commit()
    return bytes.fromhex(conn.execute("SELECT value FROM meta WHERE key='lan_secret'").fetchone()[0])


def user_key(conn: sqlite3.Connection, user: str) -> str:
    return hmac.new(_secret(conn), user.encode(), hashlib.sha256).hexdigest()


def private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_private and not a.is_loopback


def lan_url() -> str | None:
    """`POZE_LAN_URL`, altfel adresa din rețeaua locală (dacă serverul ascultă pe toate interfețele)."""
    if url := os.environ.get("POZE_LAN_URL"):
        return url
    if os.environ.get("POZE_HOST") != "0.0.0.0":
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # nu trimite nimic: doar alege interfața spre internet
            ip = s.getsockname()[0]
    except OSError:
        return None
    return f"http://{ip}:{get_settings().port}" if private(ip) else None


def direct(scope) -> bool:
    """Cererea a venit direct pe adresa locală, nu prin proxy-ul DSM (care vine pe 127.0.0.1)."""
    host = (scope.get("server") or ("127.0.0.1", 0))[0]
    try:
        return not ipaddress.ip_address(host).is_loopback
    except ValueError:  # un socket Unix sau clientul de test
        return False


async def only_from_lan(request: Request, call_next):
    """Pe adresa locală răspundem doar aparatelor din rețea: DSM lasă tot din RO pe orice port,
    deci dacă routerul ar redirecționa vreodată portul, de pe internet nu se ajunge la server."""
    if direct(request.scope):
        client = request.client.host if request.client else ""
        if not private(client) or not request.url.path.startswith("/api/"):
            return JSONResponse({"error": "Nu există."}, status_code=404)
    return await call_next(request)


@router.get("/api/lan")
def lan_info(user: str = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return {"url": lan_url(), "key": user_key(conn, user)}


@router.get("/api/lan/proof")
def lan_proof(user: str = Query(max_length=64), nonce: str = Query(min_length=16, max_length=64),
              conn: sqlite3.Connection = Depends(get_db)):
    if not user.isprintable():
        raise ApiError(422, "Cerere invalidă.")
    proof = hmac.new(bytes.fromhex(user_key(conn, user)), nonce.encode(), hashlib.sha256).hexdigest()
    return {"proof": proof}
