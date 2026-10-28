"""Data pozei, amprenta și tipul fișierului."""
import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pillow_heif
from PIL import Image

from . import video

pillow_heif.register_heif_opener()

TZ = ZoneInfo(os.environ.get("TZ") or "Europe/Bucharest")  # ora locală a pozelor fără fus în EXIF
FMT = "%Y-%m-%d %H:%M:%S"
PHOTO_EXT = {"jpg", "jpeg", "png", "heic", "heif", "gif", "webp", "dng"}
VIDEO_EXT = {"mp4", "mov", "3gp", "m4v", "mkv", "webm"}

_CAMERA_RE = re.compile(r"(?:IMG|VID|PXL|Screenshot)?[_-]?(?<!\d)(\d{8})[_-](\d{6})(?:\d{3})?(?!\d)")
_WA_RE = re.compile(r"(?:IMG|VID)-(\d{8})-WA\d+")


@dataclass
class MediaInfo:
    kind: str
    taken_at: str | None
    width: int | None
    height: int | None
    duration_ms: int | None


def kind_of(path: Path) -> str | None:
    ext = Path(path).suffix.lower().lstrip(".")
    if ext in PHOTO_EXT:
        return "photo"
    if ext in VIDEO_EXT:
        return "video"
    return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def _exif_date(raw) -> str | None:
    try:
        return datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S").strftime(FMT)
    except ValueError:
        return None


def _image_info(path: Path, kind: str) -> MediaInfo:
    try:
        with Image.open(path) as img:
            width, height = img.size
            exif = img.getexif()
            if exif.get(0x0112) in (5, 6, 7, 8):  # salvată culcată, afișată în picioare
                width, height = height, width
            taken = None
            try:
                taken = _exif_date(exif.get_ifd(0x8769).get(36867))
            except Exception:
                pass
            if taken is None:
                taken = _exif_date(exif.get(306))
            return MediaInfo(kind, taken, width, height, None)
    except Exception:
        return MediaInfo(kind, None, None, None, None)


def _utc_to_local(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime(FMT)


def _video_info(path: Path) -> MediaInfo:
    empty = MediaInfo("video", None, None, None, None)
    try:
        p = video.probe(path)
    except Exception:
        return empty
    width, height = p.width, p.height
    if p.rotation % 180:  # telefonul filmează culcat și notează rotirea
        width, height = height, width
    duration_ms = round(p.duration * 1000) if p.duration else None
    taken = None
    for t in [p.tags] + p.stream_tags:
        raw = t.get("creation_time")
        if raw:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.year < 1990:
                    continue
                taken = _utc_to_local(dt)
                break
            except ValueError:
                continue
    return MediaInfo("video", taken, width, height, duration_ms)


def read_media_info(path: Path) -> MediaInfo:
    path = Path(path)
    kind = kind_of(path)
    if kind == "video":
        return _video_info(path)
    return _image_info(path, kind or "photo")


def _camera_time(name: str) -> str | None:
    m = _CAMERA_RE.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").strftime(FMT)
    except ValueError:
        return None


def taken_at_from_name(name: str) -> str | None:
    m = _WA_RE.search(name)
    if m:
        try:
            return datetime.strptime(m.group(1) + "120000", "%Y%m%d%H%M%S").strftime(FMT)
        except ValueError:
            return None
    return _camera_time(name)


def resolve_taken_at(info: MediaInfo, path: Path, hint_ms: int | None, name: str | None = None) -> str:
    name = name or Path(path).name
    if info.kind == "video" and not _WA_RE.search(name):
        # telefoanele Honor scriu creation_time decalat cu o oră; numele camerei are ora locală
        from_camera = _camera_time(name)
        if from_camera:
            return from_camera
    if info.taken_at:
        return info.taken_at
    if hint_ms is not None:
        return _utc_to_local(datetime.fromtimestamp(hint_ms / 1000, timezone.utc))
    from_name = taken_at_from_name(name)
    if from_name:
        return from_name
    return datetime.fromtimestamp(Path(path).stat().st_mtime, TZ).strftime(FMT)
