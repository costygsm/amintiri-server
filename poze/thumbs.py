"""Miniaturile JPEG, ținute în cache în `data_dir/thumbs`."""
import os
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from . import metadata  # noqa: F401  (înregistrează deschiderea HEIC)
from .config import get_settings
from .users import safe_path

SIZES = (256, 1024)
QUALITY = 82


def _video_frame(src: Path, out: Path) -> None:
    for ss in ("1", "0"):
        subprocess.run(["ffmpeg", "-v", "quiet", "-y", "-ss", ss, "-i", str(src), "-frames:v", "1",
                        str(out)], capture_output=True, timeout=120)
        if out.exists() and out.stat().st_size:
            return
    raise RuntimeError(f"niciun cadru din {src}")


def thumbnail(asset, size: int) -> Path:
    sha = asset["sha256"]
    cache = get_settings().data_dir / "thumbs" / sha[:2] / f"{sha}_{size}.jpg"
    if cache.exists():
        return cache
    cache.parent.mkdir(parents=True, exist_ok=True)
    src = safe_path(asset["user"], asset["relpath"])
    fd, tmp = tempfile.mkstemp(suffix=".jpg", dir=cache.parent)
    os.close(fd)
    frame = Path(tmp + ".frame.jpg")
    try:
        if asset["kind"] == "video":
            _video_frame(src, frame)
            src = frame
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((size, size))
            img.convert("RGB").save(tmp, "JPEG", quality=QUALITY)
        os.replace(tmp, cache)
    finally:
        for p in (tmp, frame):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
    return cache
