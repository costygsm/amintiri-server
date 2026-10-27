import shutil
import subprocess
from pathlib import Path

from PIL import Image

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _dms(x: float):
    x = abs(x)
    d = int(x)
    m = int((x - d) * 60)
    s = round(((x - d) * 60 - m) * 60, 4)
    return (float(d), float(m), s)


def make_jpeg(path: Path, taken: str | None = None, size=(64, 48), tag306: str | None = None,
              gps: tuple[float, float] | None = None) -> Path:
    """JPEG cu EXIF DateTimeOriginal (format EXIF `AAAA:LL:ZZ HH:MM:SS`) și, opțional, GPS."""
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    if gps:
        g = exif.get_ifd(0x8825)
        g[1] = "N" if gps[0] >= 0 else "S"
        g[2] = _dms(gps[0])
        g[3] = "E" if gps[1] >= 0 else "W"
        g[4] = _dms(gps[1])
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    if tag306:
        exif[306] = tag306
    img.save(path, "JPEG", exif=exif)
    return path


def make_heic(path: Path, size=(80, 60)) -> Path:
    import pillow_heif

    pillow_heif.register_heif_opener()
    Image.new("RGB", size, (30, 200, 30)).save(path, "HEIF")
    return path


def make_mp4(path: Path, creation_time: str = "2025-07-01T09:00:00Z", location: str | None = None) -> Path | None:
    if not HAS_FFMPEG:
        return None
    loc = ["-metadata", f"location={location}"] if location else []
    subprocess.run(
        ["ffmpeg", "-v", "quiet", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x48:d=1",
         "-metadata", f"creation_time={creation_time}", *loc, "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )
    return path
