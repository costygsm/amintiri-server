"""„E o versiune nouă”: serverul întreabă GitHub, o dată la câteva ore, care e ultima versiune publicată.
O văd doar administratorii NAS-ului (doar ei pot instala), cu fișierul potrivit felului în care e instalat."""
import os
import platform
import re
import time

import httpx
from fastapi import APIRouter, Depends

from . import __version__, users
from .auth import current_user

router = APIRouter()

RELEASES = "https://api.github.com/repos/costygsm/amintiri-server/releases?per_page=20"
EVERY = 6 * 3600
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "armv8", "arm64": "armv8"}
_transport: httpx.BaseTransport | None = None  # injectat în teste
_cache: dict = {"at": None, "latest": None}


def _version(tag: str) -> tuple[int, ...] | None:
    m = TAG.fullmatch(tag or "")
    return tuple(map(int, m.groups())) if m else None


def _newest_release() -> dict | None:
    """Ultima versiune de server; tag-urile app-* sunt ale aplicației Android, cele prerelease sunt de test."""
    if _cache["at"] is not None and time.monotonic() - _cache["at"] < EVERY:
        return _cache["latest"]
    try:
        with httpx.Client(transport=_transport, timeout=5, follow_redirects=True) as c:
            r = c.get(RELEASES, headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            found = [rel for rel in r.json() if _version(rel.get("tag_name")) and not rel.get("draft")
                     and not rel.get("prerelease")]
        latest = max(found, key=lambda rel: _version(rel["tag_name"]), default=None)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError, KeyError):
        latest = _cache["latest"]  # GitHub căzut: rămâne ce știam, încercăm din nou peste câteva ore
    _cache.update(at=time.monotonic(), latest=latest)
    return latest


def check(user: str) -> dict:
    """Versiunea de acum, pentru toți; versiunea nouă doar pentru administratori (doar ei o pot instala)."""
    out = {"current": __version__, "admin": users.is_admin(user), "available": False}
    if not out["admin"]:
        return out
    rel = _newest_release()
    new, now = (_version(rel["tag_name"]) if rel else None), _version("v" + __version__)
    if not new or not now or new <= now:  # o versiune de probă („0.7.0-dev”) nu se compară
        return out
    version = rel["tag_name"][1:]
    how = "spk" if os.environ.get("POZE_INSTALL") == "spk" else "docker"
    url = rel.get("html_url", "")
    if how == "spk":
        name = f"amintiri-{version}-{ARCH.get(platform.machine(), '')}.spk"
        url = next((a.get("browser_download_url", "") for a in rel.get("assets", []) if a.get("name") == name), url)
    if not url.startswith("https://github.com/"):
        return out
    return out | {"available": True, "version": version, "how": how, "url": url}


@router.get("/api/update")
def update(user: str = Depends(current_user)):
    return check(user)
