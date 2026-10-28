import hashlib
import os

import pytest

from poze import naming, users


def test_clean_source():
    assert naming.clean_source("WhatsApp Images") == "WhatsAppImages"
    assert naming.clean_source("Cameră") == "Camera"
    assert naming.clean_source("") == "Telefon"
    assert naming.clean_source("♥ ?!") == "Telefon"


def test_target_relpath():
    assert (
        naming.target_relpath("2025-04-05 20:12:26", "Camera", "JPG")
        == "2025/04-aprilie/2025-04-05_20-12-26_Camera.jpg"
    )


def test_ext_forms():
    for ext in (".JPG", "jpg", "Jpg"):
        assert naming.target_relpath("2025-04-05 20:12:26", "Camera", ext).endswith("_Camera.jpg")


def test_suffix():
    assert (
        naming.target_relpath("2025-04-05 20:12:26", "Camera", "JPG", n=3)
        == "2025/04-aprilie/2025-04-05_20-12-26_Camera_3.jpg"
    )


def test_all_months():
    names = "ianuarie februarie martie aprilie mai iunie iulie august septembrie octombrie noiembrie decembrie".split()
    for m in range(1, 13):
        rel = naming.target_relpath(f"2024-{m:02d}-10 10:00:00", "Camera", "jpg")
        assert rel.split("/")[1] == f"{m:02d}-{names[m - 1]}"


def _part(tmp_path, name, content):
    p = tmp_path / name
    p.write_bytes(content)
    return p


def test_place_never_overwrites(env, no_chown, tmp_path):
    a = _part(tmp_path, "a.part", b"primul")
    b = _part(tmp_path, "b.part", b"al doilea")
    r1 = naming.place_file("ana", a, "2025-04-05 20:12:26", "Camera", "jpg")
    r2 = naming.place_file("ana", b, "2025-04-05 20:12:26", "Camera", "jpg")
    assert r1.endswith("_Camera.jpg") and r2.endswith("_Camera_2.jpg")
    f1, f2 = users.safe_path("ana", r1), users.safe_path("ana", r2)
    assert hashlib.sha256(f1.read_bytes()).hexdigest() == hashlib.sha256(b"primul").hexdigest()
    assert f2.read_bytes() == b"al doilea"
    assert not a.exists() and not b.exists()
    assert oct(f1.stat().st_mode & 0o777) == "0o644"


def test_place_sets_owner(env, no_chown, tmp_path):
    p = _part(tmp_path, "a.part", b"x")
    rel = naming.place_file("ana", p, "2025-04-05 20:12:26", "Camera", "jpg")
    final = str(users.safe_path("ana", rel))
    assert (final, 1030, 100) in no_chown
    photos = str(users.photos_root("ana").resolve())
    chowned = {c[0] for c in no_chown}
    assert photos not in chowned  # Photos exista deja
    assert str(users.safe_path("ana", "2025")) in chowned
    assert str(users.safe_path("ana", "2025/04-aprilie")) in chowned


def test_existing_dirs_not_chowned(env, no_chown, tmp_path):
    naming.place_file("ana", _part(tmp_path, "a", b"1"), "2025-04-05 20:12:26", "Camera", "jpg")
    no_chown.clear()
    naming.place_file("ana", _part(tmp_path, "b", b"2"), "2025-04-06 20:12:26", "Camera", "jpg")
    assert [c[0] for c in no_chown] == [str(users.safe_path("ana", "2025/04-aprilie/2025-04-06_20-12-26_Camera.jpg"))]


def test_attempt_limit(env, no_chown, tmp_path, monkeypatch):
    monkeypatch.setattr(naming, "MAX_ATTEMPTS", 3)
    for i in range(3):
        naming.place_file("ana", _part(tmp_path, f"p{i}", b"x"), "2025-04-05 20:12:26", "Camera", "jpg")
    with pytest.raises(RuntimeError):
        naming.place_file("ana", _part(tmp_path, "pz", b"x"), "2025-04-05 20:12:26", "Camera", "jpg")


def test_chown_failure_keeps_part(env, tmp_path, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    p = _part(tmp_path, "a.part", b"x")

    def boom(path, uid, gid):
        if str(path).endswith(".jpg"):
            raise PermissionError("nu")

    monkeypatch.setattr(os, "chown", boom)
    with pytest.raises(PermissionError):
        naming.place_file("ana", p, "2025-04-05 20:12:26", "Camera", "jpg")
    assert p.exists()
    assert list(users.safe_path("ana", "2025/04-aprilie").iterdir()) == []


def test_dir_chown_failure_keeps_part(env, tmp_path, monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    p = _part(tmp_path, "a.part", b"x")

    def boom(path, uid, gid):
        raise PermissionError("nu")

    monkeypatch.setattr(os, "chown", boom)
    with pytest.raises(PermissionError):
        naming.place_file("ana", p, "2025-04-05 20:12:26", "Camera", "jpg")
    assert p.exists()


def test_unlink_failure_still_returns(env, no_chown, tmp_path, monkeypatch):
    p = _part(tmp_path, "a.part", b"x")

    def boom(path):
        raise OSError("nu")

    monkeypatch.setattr(os, "unlink", boom)
    rel = naming.place_file("ana", p, "2025-04-05 20:12:26", "Camera", "jpg")
    assert users.safe_path("ana", rel).exists()


@pytest.mark.parametrize("taken", ["2025-00-05 20:12:26", "2025-13-05 20:12:26", "x"])
def test_bad_taken_at(taken):
    with pytest.raises(ValueError):
        naming.target_relpath(taken, "Camera", "jpg")


@pytest.mark.parametrize("ext", ["../x", "jpĝ", "a" * 11, ""])
def test_bad_ext(ext):
    with pytest.raises(ValueError):
        naming.target_relpath("2025-04-05 20:12:26", "Camera", ext)


def test_long_source():
    assert len(naming.clean_source("a" * 300)) == 40
    assert len(naming.target_relpath("2025-04-05 20:12:26", "a" * 300, "jpg", 9999).split("/")[-1]) < 255
