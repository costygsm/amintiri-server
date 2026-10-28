"""Clipurile prin PyAV, care are FFmpeg-ul cu decodoarele în roată.

ffmpeg-ul din DSM (/bin/ffmpeg 4.1.9) n-are decodor H.264/HEVC și nici ffprobe, deci în pachetul
.spk clipurile ieșeau fără miniatură, dimensiuni sau GPS; în Docker mergea doar datorită ffmpeg-ului din apt.
"""
import math
import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path

import av
from PIL import Image

# un cadru 4K HEVC decodat ține ~130 MB: pe un NAS cu 1–2 GB nu lăsăm grila plină de clipuri să le
# decodeze pe toate deodată (după actualizarea la 0.6.5 lipsesc toate miniaturile clipurilor din pachet)
_decodari = threading.BoundedSemaphore(2)


@dataclass
class Probe:
    tags: dict = field(default_factory=dict)          # ale fișierului (creation_time, location…)
    stream_tags: list = field(default_factory=list)   # ale fiecărei piste
    width: int | None = None
    height: int | None = None
    rotation: int = 0                                 # din displaymatrix, ca ffprobe (ex. -90)
    duration: float | None = None                     # secunde


def _rotation(stream) -> int:
    """Rotirea din displaymatrix-ul pistei, ca av_display_rotation_get (fără să decodăm un cadru)."""
    raw = (stream.codec_context.coded_side_data or {}).get("display_matrix")
    if not raw or len(raw) < 36:
        return 0
    m = struct.unpack("<9i", bytes(raw[:36]))
    s0, s1 = math.hypot(m[0], m[3]), math.hypot(m[1], m[4])
    if not s0 or not s1:
        return 0
    return round(-math.degrees(math.atan2(m[1] / s1, m[0] / s0)))


def probe(path: Path) -> Probe:
    with av.open(str(path)) as c:
        p = Probe(tags=dict(c.metadata), stream_tags=[dict(s.metadata) for s in c.streams])
        if c.duration:
            p.duration = c.duration / av.time_base
        if c.streams.video:
            v = c.streams.video[0]
            p.width, p.height = v.codec_context.width or None, v.codec_context.height or None
            p.rotation = _rotation(v)
    return p


def tags(path: Path) -> dict:
    """Doar etichetele fișierului (GPS-ul), fără să citim pistele."""
    with av.open(str(path)) as c:
        return dict(c.metadata)


def _decode_at(path: Path, at: float | None):
    with av.open(str(path)) as c:
        if not c.streams.video:
            return None
        v = c.streams.video[0]
        v.thread_type = "SLICE"   # „AUTO” (pe cadre) e de 2× mai lent și ține ~100 MB în plus pentru un singur cadru
        if at:
            c.seek(int(at * av.time_base))   # cadrul-cheie de dinainte; decodăm până la secunda cerută
        first = None
        for i, f in enumerate(c.decode(v)):
            first = first or f
            if not at or f.time is None or f.time >= at or i >= 120:
                return f
        return first


def frame(path: Path, size: int | None = None) -> Image.Image:
    """Cadrul de la secunda 1 (sau primul, la clipuri mai scurte), micșorat la `size` și întors cum se vede
    pe telefon."""
    with _decodari:
        with av.open(str(path)) as c:
            dur = c.duration / av.time_base if c.duration else 0
        f = None
        if dur > 1:
            try:
                f = _decode_at(path, 1)
            except av.FFmpegError:
                f = None   # ca înainte cu „-ss 0”: unele fișiere nu se pot căuta
        f = f or _decode_at(path, None)
        if f is None:
            raise RuntimeError(f"niciun cadru din {path}")
        rot = f.rotation
        if size and max(f.width, f.height) > size:
            k = size / max(f.width, f.height)
            f = f.reformat(width=max(1, round(f.width * k)), height=max(1, round(f.height * k)))
        img = f.to_image()
        # ca la ffmpeg: displaymatrix -90 = se rotește 90° în sensul acelor (PIL: unghi pozitiv = invers)
        return img.rotate(rot, expand=True) if rot else img
