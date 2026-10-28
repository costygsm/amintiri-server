from pathlib import Path

from PIL import Image


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


def make_mp4(path: Path, creation_time: str = "2025-07-01T09:00:00Z", location: str | None = None,
             rotation: int = 0, seconds: float = 1.5) -> Path:
    """Clip MPEG-4 de 64×48: jumătatea stângă roșie, dreapta albastră (pentru sensul rotirii)."""
    import av
    with av.open(str(path), "w") as c:
        s = c.add_stream("mpeg4", rate=10)
        s.width, s.height, s.pix_fmt = 64, 48, "yuv420p"
        if rotation:
            s.set_display_rotation(rotation)
        c.metadata["creation_time"] = creation_time
        if location:
            c.metadata["location"] = location
        img = Image.new("RGB", (64, 48), (0, 0, 255))
        img.paste((255, 0, 0), (0, 0, 32, 48))
        for i in range(int(seconds * 10)):
            f = av.VideoFrame.from_image(img)
            f.pts = i
            for pk in s.encode(f):
                c.mux(pk)
        for pk in s.encode():
            c.mux(pk)
    return path
