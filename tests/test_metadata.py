import hashlib
import os
from datetime import datetime
from pathlib import Path

import pytest

from fixtures import HAS_FFMPEG, make_heic, make_jpeg, make_mp4
from poze.metadata import (kind_of, read_media_info, resolve_taken_at,
                           sha256_file, taken_at_from_name, MediaInfo)

needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg lipsește")


def test_exif_date(tmp_path):
    p = make_jpeg(tmp_path / "a.jpg", "2025:04:05 20:12:26")
    info = read_media_info(p)
    assert info.taken_at == "2025-04-05 20:12:26"
    assert info.kind == "photo" and (info.width, info.height) == (64, 48)


def test_exif_fallback_tag_306(tmp_path):
    p = make_jpeg(tmp_path / "a.jpg", None, tag306="2024:01:02 03:04:05")
    assert read_media_info(p).taken_at == "2024-01-02 03:04:05"


def test_heic_reads(tmp_path):
    info = read_media_info(make_heic(tmp_path / "a.heic"))
    assert info.kind == "photo" and (info.width, info.height) == (80, 60)


def test_corrupt_image_does_not_raise(tmp_path):
    p = tmp_path / "x.jpg"
    p.write_bytes(b"not an image")
    info = read_media_info(p)
    assert info.taken_at is None and info.width is None and info.height is None


def test_whatsapp_name_date():
    assert taken_at_from_name("IMG-20210813-WA0040.jpg") == "2021-08-13 12:00:00"


def test_camera_name_date():
    assert taken_at_from_name("IMG_20250405_201226.jpg") == "2025-04-05 20:12:26"
    assert taken_at_from_name("20200919_162204.jpg") == "2020-09-19 16:22:04"
    assert taken_at_from_name("VID_20240101_000501.mp4") == "2024-01-01 00:05:01"
    assert taken_at_from_name("poza.jpg") is None
    assert taken_at_from_name("IMG_20251399_999999.jpg") is None


def test_kind_of():
    assert kind_of(Path("a.JPG")) == "photo"
    assert kind_of(Path("a.dng")) == "photo"
    assert kind_of(Path("a.MOV")) == "video"
    assert kind_of(Path("a.txt")) is None


@needs_ffmpeg
def test_video_creation_time_utc_to_local(tmp_path):
    info = read_media_info(make_mp4(tmp_path / "v.mp4"))
    assert info.kind == "video"
    assert info.taken_at == "2025-07-01 12:00:00"
    assert info.duration_ms and info.duration_ms > 0


def test_resolve_order(tmp_path):
    p = make_jpeg(tmp_path / "IMG-20210813-WA0040.jpg")
    no_exif = read_media_info(p)
    assert no_exif.taken_at is None
    hint = int(datetime(2024, 3, 10, 8, 0, tzinfo=__import__("datetime").timezone.utc).timestamp() * 1000)
    assert resolve_taken_at(no_exif, p, hint) == "2024-03-10 10:00:00"
    assert resolve_taken_at(no_exif, p, None) == "2021-08-13 12:00:00"
    q = make_jpeg(tmp_path / "poza.jpg")
    mt = datetime(2023, 1, 1, 12, 0, 0).timestamp()
    os.utime(q, (mt, mt))
    assert resolve_taken_at(read_media_info(q), q, None) == resolve_taken_at(MediaInfo("photo", None, None, None, None), q, None)
    got = datetime.strptime(resolve_taken_at(read_media_info(q), q, None), "%Y-%m-%d %H:%M:%S")
    from zoneinfo import ZoneInfo
    assert got == datetime.fromtimestamp(mt, ZoneInfo("Europe/Bucharest")).replace(tzinfo=None)


def test_exif_wins_over_hint(tmp_path):
    p = make_jpeg(tmp_path / "a.jpg", "2025:04:05 20:12:26")
    assert resolve_taken_at(read_media_info(p), p, 0) == "2025-04-05 20:12:26"


def test_sha256_matches_hashlib(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(os.urandom(3 * 1024 * 1024 + 17))
    assert sha256_file(p) == hashlib.sha256(p.read_bytes()).hexdigest()


def test_pixel_name_with_millis():
    assert taken_at_from_name("PXL_20240101_101010123.jpg") == "2024-01-01 10:10:10"


def _fake_ffprobe(monkeypatch, payload):
    import json
    import subprocess
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(payload).encode()),
    )


def test_video_placeholder_creation_time_ignored(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {"format": {"duration": "1.5", "tags": {"creation_time": "1970-01-01T00:00:00.000000Z"}},
                                "streams": [{"codec_type": "video", "width": 64, "height": 48}]})
    assert read_media_info(tmp_path / "v.mp4").taken_at is None


def test_video_creation_time_from_stream_tags(tmp_path, monkeypatch):
    _fake_ffprobe(monkeypatch, {"format": {"duration": "1.5"},
                                "streams": [{"codec_type": "video", "width": 64, "height": 48,
                                             "tags": {"creation_time": "2025-07-01T09:00:00.000000Z"}}]})
    info = read_media_info(tmp_path / "v.mp4")
    assert (info.taken_at, info.width, info.height, info.duration_ms) == ("2025-07-01 12:00:00", 64, 48, 1500)


def test_video_camera_name_beats_creation_time(tmp_path):
    # Honor scrie creation_time cu o oră decalat; ora din numele camerei e ora locală reală
    p = tmp_path / "VID_20231202_132313.mp4"
    p.write_bytes(b"x")
    info = MediaInfo("video", "2023-12-02 14:23:13", 1920, 1080, 1000)
    assert resolve_taken_at(info, p, None) == "2023-12-02 13:23:13"
    assert resolve_taken_at(info, tmp_path / "x.part.mp4", None, name="VID_20231202_132313.mp4") \
        == "2023-12-02 13:23:13"
    wa = MediaInfo("video", "2023-12-02 14:23:13", 1, 1, 1)
    assert resolve_taken_at(wa, tmp_path / "VID-20231202-WA0001.mp4", None) == "2023-12-02 14:23:13"
    photo = MediaInfo("photo", "2023-12-02 14:23:13", 1, 1, None)
    assert resolve_taken_at(photo, tmp_path / "IMG_20231202_132313.jpg", None) == "2023-12-02 14:23:13"
