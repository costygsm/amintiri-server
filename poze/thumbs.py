"""Miniaturile JPEG, ținute în cache în `data_dir/thumbs`."""
import logging
import os
import tempfile
from pathlib import Path

import av
from PIL import Image, ImageOps

from . import metadata, video  # noqa: F401  (metadata înregistrează deschiderea HEIC)
from .config import get_settings
from .users import safe_path

log = logging.getLogger(__name__)

SIZES = (256, 1024)
QUALITY = 82


def _video_frame(src: Path, size: int) -> Image.Image:
    try:
        return video.frame(src, size)
    except av.FFmpegError as e:
        raise RuntimeError(f"niciun cadru din {src}: {e}") from e


def _open(asset, src: Path, size: int) -> Image.Image:
    if asset["kind"] == "video":
        return _video_frame(src, size)
    return Image.open(src)


def cache_path(asset, size: int) -> Path:
    """Aceeași amprentă poate fi rotită altfel la alt cont: rotirea face parte din nume."""
    sha, rot = asset["sha256"], asset["rotation"]
    return get_settings().data_dir / "thumbs" / sha[:2] / (f"{sha}_{size}_r{rot}.jpg" if rot else f"{sha}_{size}.jpg")


def thumbnail(asset, size: int) -> Path:
    cache = cache_path(asset, size)
    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    src = safe_path(asset["user"], asset["relpath"])
    fd, tmp = tempfile.mkstemp(suffix=".jpg", dir=cache.parent)
    os.close(fd)
    try:
        with _open(asset, src, size) as img:
            img = ImageOps.exif_transpose(img)
            if asset["rotation"]:
                img = img.rotate(-asset["rotation"], expand=True)  # PIL rotește invers acelor
            img.thumbnail((size, size))
            img.convert("RGB").save(tmp, "JPEG", quality=QUALITY)
        os.replace(tmp, cache)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return cache


def warm(conn, size: int = 256, limit: int = 3000) -> int:
    """Face miniaturile care lipsesc, cele mai noi poze întâi, ca derularea să nu le aștepte.
    Cel mult `limit` pe tură, ca indexarea pozelor noi să nu aștepte ore la prima pornire.
    Întoarce câte a făcut."""
    made = tried = 0
    rows = conn.execute("SELECT * FROM assets WHERE deleted_at IS NULL ORDER BY taken_at DESC").fetchall()
    for asset in rows:
        if tried >= limit:  # și cele care nu se pot face consumă din tură
            break
        if cache_path(asset, size).exists():
            continue
        tried += 1
        try:
            thumbnail(asset, size)
            made += 1
        except Exception as e:
            log.warning("miniatură %s: %s", asset["id"], e)
    return made
