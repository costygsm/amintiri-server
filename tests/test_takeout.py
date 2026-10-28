import hashlib
import io
import json
import tarfile
import time
import zipfile
from datetime import datetime, timezone

from PIL import Image

from poze import db, indexer, takeout
from poze.metadata import FMT, TZ
from poze.users import photos_root

from tests.fixtures import make_jpeg
from tests.test_uploads import headers

GP = "Takeout/Google Photos"


def jpeg(color, exif_taken=None) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (40, 30), color)
    exif = Image.Exif()
    if exif_taken:
        exif.get_ifd(0x8769)[36867] = exif_taken
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def side(title, when_utc, **extra) -> bytes:
    ts = int(datetime.strptime(when_utc, FMT).replace(tzinfo=timezone.utc).timestamp())
    return json.dumps({"title": title, "photoTakenTime": {"timestamp": str(ts)}, "url": "https://photos.google.com/x",
                       "geoData": {"latitude": 0.0, "longitude": 0.0}, **extra}).encode()


def local(when_utc) -> str:
    return datetime.strptime(when_utc, FMT).replace(tzinfo=timezone.utc).astimezone(TZ).strftime(FMT)


def write_zip(path, files: dict):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)


def run(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        return conn, takeout.run_import(conn, user, {})
    except Exception:
        conn.close()
        raise


def test_import_takeout_in_two_parts(env, no_chown):
    d = env["homes"] / "ana" / takeout.FOLDER
    d.mkdir()
    beach, beach2, edited, trashed = jpeg((0, 0, 200)), jpeg((0, 200, 0)), jpeg((200, 200, 0)), jpeg((9, 9, 9))
    long_name = "Screenshot_20190707-101010_Some_Very_Long_Applicat"  # trunchiat de Google
    # bucata 1: pozele; bucata 2: json-urile lor și albumul
    write_zip(d / "takeout-20261028T1000Z-001.zip", {
        f"{GP}/Photos from 2019/IMG_0001.jpg": beach,
        f"{GP}/Photos from 2019/IMG_0002.jpg": beach2,
        f"{GP}/Photos from 2019/IMG_0002(1).jpg": jpeg((1, 2, 3)),
        f"{GP}/Photos from 2019/IMG_0003-edited.jpg": edited,
        f"{GP}/Photos from 2019/{long_name}.jpg": jpeg((50, 60, 70)),
        f"{GP}/Photos from 2019/IMG_0009.jpg": trashed,
        f"{GP}/Photos from 2018/fara_nimic.png": jpeg((90, 0, 90)),
        f"{GP}/Vacanta Grecia/IMG_0001.jpg": beach,
    })
    write_zip(d / "takeout-20261028T1000Z-002.zip", {
        f"{GP}/Photos from 2019/IMG_0001.jpg.supplemental-metadata.json":
            side("IMG_0001.jpg", "2019-05-04 10:00:00", favorited=True,
                 geoData={"latitude": 44.4268, "longitude": 26.1025}),
        f"{GP}/Photos from 2019/IMG_0002.jpg.json": side("IMG_0002.jpg", "2019-06-02 08:00:00"),
        f"{GP}/Photos from 2019/IMG_0002.jpg(1).json": side("IMG_0002.jpg", "2019-06-01 08:00:00"),
        f"{GP}/Photos from 2019/IMG_0003.jpg.supplemental-metad.json": side("IMG_0003.jpg", "2019-07-01 08:00:00", archived=True),
        f"{GP}/Photos from 2019/{long_name[:40]}.json": side(long_name + "ion_Name.jpg", "2019-07-07 07:10:10"),
        f"{GP}/Photos from 2019/IMG_0009.jpg.json": side("IMG_0009.jpg", "2019-08-01 08:00:00", trashed=True),
        f"{GP}/Vacanta Grecia/IMG_0001.jpg.json": side("IMG_0001.jpg", "2019-05-04 10:00:00"),
        f"{GP}/Vacanta Grecia/metadata.json": json.dumps({"title": "Vacanță Grecia", "description": ""}),
    })
    # o poză care era deja pe NAS din backupul telefonului
    (photos_root("ana") / "vechi").mkdir()
    (photos_root("ana") / "vechi" / "a.jpg").write_bytes(beach2)
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "ana")
    conn.close()

    conn, rep = run(env)
    try:
        assert rep == {"added": 5, "duplicates": 2, "originals": 0, "no_date": 1, "trashed": 1, "errors": 0, "albums": 1,
                       "skipped": 0, "skipped_examples": [], "bad_archives": [], "disk_full": False}
        rows = {r["taken_at"]: r for r in conn.execute("SELECT * FROM assets WHERE source='Google'")}
        assert set(rows) == {local("2019-05-04 10:00:00"), local("2019-06-01 08:00:00"),
                             local("2019-07-01 08:00:00"), local("2019-07-07 07:10:10"), "2018-07-01 12:00:00"}
        beach_row = rows[local("2019-05-04 10:00:00")]
        assert (beach_row["lat"], beach_row["lon"], beach_row["geo_done"]) == (44.4268, 26.1025, 1)
        assert beach_row["place_id"] is not None
        assert (photos_root("ana") / beach_row["relpath"]).read_bytes() == beach
        assert beach_row["relpath"].startswith("2019/05-mai/2019-05-04_")
        album = conn.execute("SELECT id FROM albums WHERE user='ana' AND name='Vacanță Grecia'").fetchone()
        assert [r[0] for r in conn.execute("SELECT sha256 FROM album_items WHERE album_id=?", (album[0],))] \
            == [beach_row["sha256"]]
        assert conn.execute("SELECT COUNT(*) FROM favorites WHERE user='ana'").fetchone()[0] == 1
        edited_sha = conn.execute("SELECT sha256 FROM assets WHERE taken_at=?", (local("2019-07-01 08:00:00"),)).fetchone()[0]
        assert conn.execute("SELECT sha256 FROM archive WHERE user='ana'").fetchone()[0] == edited_sha
        assert not list((photos_root("ana") / ".incoming").iterdir())
        # a doua rulare (de pildă după o repornire) nu dublează nimic
        rep2 = takeout.run_import(conn, "ana", {})
        assert (rep2["added"], rep2["duplicates"]) == (0, 7)
        assert conn.execute("SELECT COUNT(*) FROM albums WHERE user='ana'").fetchone()[0] == 1
    finally:
        conn.close()


def test_import_tgz_and_unpacked_folder(env, no_chown):
    d = env["homes"] / "ana" / takeout.FOLDER
    d.mkdir()
    data, js = jpeg((10, 20, 30)), side("IMG_5.jpg", "2020-01-02 03:04:05")
    with tarfile.open(d / "takeout-001.tgz", "w:gz") as t:
        for name, b in ((f"{GP}/Photos from 2020/IMG_5.jpg", data), (f"{GP}/Photos from 2020/IMG_5.jpg.json", js)):
            info = tarfile.TarInfo(name)
            info.size = len(b)
            t.addfile(info, io.BytesIO(b))
    unpacked = d / "Takeout" / "Google Photos" / "Photos from 2021"
    unpacked.mkdir(parents=True)
    make_jpeg(unpacked / "IMG_6.jpg", "2021:03:04 05:06:07")
    conn, rep = run(env)
    try:
        assert (rep["added"], rep["errors"]) == (2, 0)
        got = {r[0] for r in conn.execute("SELECT taken_at FROM assets WHERE user='ana'")}
        assert got == {local("2020-01-02 03:04:05"), "2021-03-04 05:06:07"}  # EXIF are prioritate, ora locală
    finally:
        conn.close()


def test_api_creates_folder_and_runs_import(env, client, no_chown):
    h = headers(env)
    r = client.get("/api/import/google", headers=h).json()
    assert (env["homes"] / "ana" / takeout.FOLDER).is_dir()
    assert r == {"found": [], "job": None, "last": None}
    assert client.post("/api/import/google", headers=h).status_code == 404
    write_zip(env["homes"] / "ana" / takeout.FOLDER / "takeout-001.zip",
              {f"{GP}/Photos from 2019/IMG_1.jpg": jpeg((1, 1, 1), "2019:01:01 10:00:00")})
    assert client.get("/api/import/google", headers=h).json()["found"] == [{"name": "takeout-001.zip", "size": (
        env["homes"] / "ana" / takeout.FOLDER / "takeout-001.zip").stat().st_size}]
    assert client.post("/api/import/google", headers=h).status_code == 200
    for _ in range(100):
        r = client.get("/api/import/google", headers=h).json()
        if r["job"] is None and r["last"]:
            break
        time.sleep(0.05)
    assert r["last"]["added"] == 1 and r["last"]["finished_at"]
    # bogdan nu vede importul anei
    assert client.get("/api/import/google", headers=headers(env, "bogdan")).json()["last"] is None


def test_other_files_bad_archive_and_disk_full_are_reported(env, no_chown, monkeypatch):
    d = env["homes"] / "ana" / takeout.FOLDER
    d.mkdir()
    write_zip(d / "takeout-001.zip", {
        f"{GP}/Photos from 2009/MVI_0001.AVI": b"film vechi",            # tip pe care nu-l știm: raportat
        f"{GP}/Photos from 2009/IMG_1.jpg": jpeg((1, 1, 1)),
        f"{GP}/Photos from 2009/IMG_2.jpg": jpeg((2, 2, 2)),
        "Takeout/archive_browser.html": b"<html>",                      # pagina Takeout: ignorată
    })
    good = (d / "takeout-001.zip").read_bytes()
    (d / "takeout-002.zip").write_bytes(good[: len(good) // 2])         # descărcată pe jumătate
    conn, rep = run(env)
    try:
        assert (rep["added"], rep["skipped"], rep["skipped_examples"]) == (2, 1, ["MVI_0001.AVI"])
        assert rep["bad_archives"] == ["takeout-002.zip"] and not rep["disk_full"]
    finally:
        conn.close()
    # discul plin: importul se oprește la prima poză, nu numără restul ca „stricate”
    write_zip(d / "takeout-001.zip", {f"{GP}/Photos from 2010/A{i}.jpg": jpeg((i, 9, 9)) for i in range(5)})
    (d / "takeout-002.zip").unlink()

    def full(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(takeout.naming, "place_file", full)
    conn, rep = run(env)
    try:
        assert (rep["disk_full"], rep["errors"], rep["added"]) == (True, 0, 0)
        assert not list((photos_root("ana") / ".incoming").iterdir())
    finally:
        conn.close()


def test_deleted_photo_is_not_imported_again(env, no_chown):
    d = env["homes"] / "ana" / takeout.FOLDER
    d.mkdir()
    write_zip(d / "takeout-001.zip", {f"{GP}/Photos from 2019/IMG_1.jpg": jpeg((5, 5, 5), "2019:01:01 10:00:00")})
    conn, rep = run(env)
    try:
        assert rep["added"] == 1
        conn.execute("DELETE FROM assets WHERE user='ana'")  # coșul golit
        conn.commit()
        assert takeout.run_import(conn, "ana", {})["added"] == 0
    finally:
        conn.close()


def test_sidecars_keep_little_and_find_by_index():
    side = takeout.Sidecars()
    for i in range(20000):
        side.add(f"{GP}/Photos from 2019/IMG_{i}.jpg.json", json.loads(side_json(f"IMG_{i}.jpg")))
    side.done()
    assert side.find(f"{GP}/Photos from 2019/IMG_19999.jpg")[0] is not None
    assert all(isinstance(v[0][1], tuple) and len(v[0][1]) == 5 for v in side.exact.values())


def side_json(title):
    return side(title, "2019-01-01 10:00:00", description="x" * 200, imageViews="3")


def test_symlinked_folder_is_not_followed(env, no_chown):
    other = env["homes"] / "bogdan" / "secret"
    other.mkdir()
    write_zip(other / "takeout-001.zip", {f"{GP}/Photos from 2019/IMG_1.jpg": jpeg((7, 7, 7))})
    (env["homes"] / "ana" / takeout.FOLDER).symlink_to(other)
    assert takeout._sources("ana") == []


def test_interrupted_and_one_import_at_a_time(env, client, no_chown):
    h = headers(env)
    conn = db.connect(env["data"])
    takeout._save_report(conn, "ana", {"running": True, "started_at": "2026-10-28 10:00:00"})
    conn.close()
    assert client.get("/api/import/google", headers=h).json()["last"] == {
        "interrupted": True, "finished_at": "2026-10-28 10:00:00"}
    write_zip(env["homes"] / "ana" / takeout.FOLDER / "t.zip", {f"{GP}/x/IMG_1.jpg": jpeg((3, 3, 3))})
    takeout._jobs["bogdan"] = {"done": 0, "total": None, "started_at": ""}
    try:
        r = client.post("/api/import/google", headers=h)
        assert r.status_code == 409 and r.json()["error"] == takeout.BUSY
    finally:
        takeout._jobs.pop("bogdan", None)


def scene(seed, size=(1600, 1200)) -> Image.Image:
    """O imagine cu forme (nu o culoare plină), ca amprenta după aspect să aibă ce deosebi."""
    import random

    from PIL import ImageDraw

    rnd = random.Random(seed)
    img = Image.new("RGB", size, (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x, y = rnd.randint(0, size[0]), rnd.randint(0, size[1])
        d.rectangle([x, y, x + size[0] // 3, y + size[1] // 3], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return img


def exif_bytes(img: Image.Image, taken: str, model: str, scale=1.0, quality=92) -> bytes:
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    exif = Image.Exif()
    exif[0x0110] = model
    exif.get_ifd(0x8769)[36867] = taken
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif, quality=quality)
    return buf.getvalue()


def test_google_storage_saver_copy_keeps_phone_original(env, no_chown):
    T = "2024:08:15 18:30:05"
    # pe NAS, de pe telefon: originalul mare
    (photos_root("ana") / "telefon").mkdir()
    orig = exif_bytes(scene(1), T, "Pixel 7")
    (photos_root("ana") / "telefon" / "IMG_1.jpg").write_bytes(orig)
    conn = db.connect(env["data"])
    indexer.scan_user(conn, "ana")
    conn.close()
    d = env["homes"] / "ana" / takeout.FOLDER
    d.mkdir()
    write_zip(d / "takeout-001.zip", {
        # varianta Google: micșorată și recomprimată, același EXIF, într-un album
        f"{GP}/Mare/IMG_1.jpg": exif_bytes(scene(1), T, "Pixel 7", scale=0.5, quality=60),
        f"{GP}/Mare/metadata.json": json.dumps({"title": "Mare"}),
        # alt cadru din aceeași secundă (rafală), același telefon: rămâne
        f"{GP}/Photos from 2024/IMG_2.jpg": exif_bytes(scene(2), T, "Pixel 7", scale=0.5),
        # aceeași secundă, alt telefon (poza unui prieten), chiar dacă seamănă: rămâne
        f"{GP}/Photos from 2024/IMG_3.jpg": exif_bytes(scene(1), T, "iPhone 15", scale=0.5),
    })
    conn, rep = run(env)
    try:
        assert (rep["originals"], rep["added"], rep["duplicates"]) == (1, 2, 0)
        orig_sha = hashlib.sha256(orig).hexdigest()
        album = conn.execute("SELECT id FROM albums WHERE name='Mare'").fetchone()[0]
        assert [r[0] for r in conn.execute("SELECT sha256 FROM album_items WHERE album_id=?", (album,))] == [orig_sha]
        # a doua rulare nu mai reface nimic
        rep2 = takeout.run_import(conn, "ana", {})
        assert (rep2["added"], rep2["originals"], rep2["duplicates"]) == (0, 0, 3)
    finally:
        conn.close()
