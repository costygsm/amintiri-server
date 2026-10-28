"""Importul din Google Photos. Omul cere arhiva în Google Takeout și o pune (zip, tgz sau dezarhivată) în
folderul „Import Google” din folderul lui personal; de aici o citim și punem pozele în Photos, ca pe cele
din backup.

Capcanele Takeout pe care le rezolvăm:
- data și locul stau adesea doar în fișierul .json de lângă poză (pozele descărcate, primite, editate), cu
  nume trunchiat sau cu „(1)” mutat după extensie; potrivim după câmpul „title” din json, nu după nume;
- arhiva vine în mai multe bucăți, iar json-ul poate fi în altă bucată decât poza: întâi citim toate
  json-urile, apoi pozele;
- aceeași poză apare și în „Photos from 2019”, și în fiecare album: o păstrăm o dată (după amprentă),
  inclusiv dacă e deja pe NAS din backupul telefonului; albumele, favoritele și arhiva se refac.
Arhivele nu se modifică și nu se șterg. Raportul spune dacă omul le poate șterge: nu, cât timp a rămas
ceva neimportat (alt tip de fișier, o arhivă stricată, discul plin)."""
import bisect
import errno
import hashlib
import json
import logging
import os
import re
import secrets
import tarfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends
from PIL import Image, ImageOps

from . import db, geo, metadata, naming
from .auth import ApiError, current_user, get_db
from .config import get_settings
from .metadata import FMT, TZ
from .users import ensure_photos, photos_root, uid_of

log = logging.getLogger(__name__)
router = APIRouter()

FOLDER = "Import Google"
SOURCE = "Google"
JSON_MAX = 1 << 20
EXAMPLES = 10
_ARCHIVE_RE = re.compile(r"\.(zip|tgz|tar\.gz|tar)$", re.I)
_DUP_RE = re.compile(r"^(?P<stem>.*?)\((?P<n>\d+)\)$")
_JSON_DUP_RE = re.compile(r"\((\d+)\)\.json$", re.I)
# „-edited” în limbile în care Google scrie numele pozelor editate
_EDITED_RE = re.compile(r"-(edited|editat|bearbeitet|modifi[ée]|editado|modificato|bewerkt|edytowane)$", re.I)
_YEAR_RE = re.compile(r"(?<!\d)(19[7-9]\d|20[0-4]\d)(?!\d)")
_JUNK = {".html", ".htm", ".txt", ".csv", ".ds_store", ".ini", ".db"}  # paginile și listele Takeout, resturi de sistem

NOTHING = "N-am găsit nicio arhivă Google în folderul „Import Google”."
RUNNING = "Importul rulează deja."
BUSY = "Alt import rulează acum pe NAS. Încearcă după ce se termină."

# un singur import odată pe tot NAS-ul: pe un NAS mic, două ar sufoca discul și memoria
_jobs: dict[str, dict] = {}
_jobs_guard = threading.Lock()


class DiskFull(Exception):
    pass


def import_dir(user: str) -> Path:
    return get_settings().homes_root / user / FOLDER


# ── Sursele: arhive zip / tar și fișierele dezarhivate de om ─────────────────────────────

def _walk(d: Path):
    """Fișierele dezarhivate: fără arhive, fără fișiere ascunse, @eaDir/#recycle (ale DSM) și legături."""
    for dirpath, dirnames, filenames in os.walk(d):
        dirnames[:] = sorted(x for x in dirnames if not x.startswith((".", "@", "#")))
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if not _ARCHIVE_RE.search(fn) and not fn.startswith(".") and not p.is_symlink():
                yield p.relative_to(d).as_posix(), p


def _sources(user: str) -> list[Path]:
    """Arhivele, în ordinea numelui (takeout-…-001.zip, -002.zip), plus folderul însuși pentru ce e dezarhivat.
    O legătură (symlink) spre folderul sau arhiva altcuiva nu e urmată: în Docker rulăm ca root."""
    home, d = get_settings().homes_root / user, import_dir(user)
    if not d.is_dir() or d.is_symlink() or not d.resolve().is_relative_to(home.resolve()):
        return []
    archives = sorted(p for p in d.iterdir() if _ARCHIVE_RE.search(p.name) and not p.is_symlink() and p.is_file())
    return archives + ([d] if next(_walk(d), None) else [])


def _entries(src: Path, want):
    """(cale în arhivă, fișier deschis) pentru intrările pe care `want(cale)` le vrea."""
    if src.is_dir():
        for name, p in _walk(src):
            if want(name):
                with open(p, "rb") as f:
                    yield name, f
    elif src.name.lower().endswith(".zip"):
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                if not info.is_dir() and want(info.filename):
                    with z.open(info) as f:
                        yield info.filename, f
    else:
        with tarfile.open(src, "r:*") as t:
            for m in t:
                if m.isfile() and want(m.name):
                    f = t.extractfile(m)
                    if f:
                        with f:
                            yield m.name, f


def _is_json(name: str) -> bool:
    return name.lower().endswith(".json")


def _is_media(name: str) -> bool:
    return metadata.kind_of(Path(name)) is not None


def _is_other(name: str) -> bool:
    """Un fișier care nu e nici poză/film știut, nici json, nici o pagină a Takeout: îl raportăm."""
    return not _is_json(name) and not _is_media(name) and PurePosixPath(name.lower()).suffix not in _JUNK \
        and PurePosixPath(name).name.lower() not in _JUNK


# ── Json-urile de lângă poze și albumele ────────────────────────────────────────────────

def _split(name: str) -> tuple[str, str, int]:
    """„IMG_1(1)-edited.JPG” → („img_1”, „.jpg”, 1)."""
    stem, ext = os.path.splitext(name)
    n = 0
    if m := _DUP_RE.match(stem):
        stem, n = m.group("stem"), int(m.group("n"))
    return _EDITED_RE.sub("", stem).lower(), ext.lower(), n


class Sidecars:
    """Doar ce folosim din fiecare json (ora, locul, favorit/arhivat/șters), într-un tuplu: 100.000 de json-uri
    întregi ar ține sute de MB pe un NAS cu 512 MB. Căutarea e prin dicționare, nu prin toată lista folderului."""

    def __init__(self):
        self.exact: dict[tuple[str, str, str], list] = {}   # (folder, stem, ext) → [(n, date)]
        self.by_stem: dict[tuple[str, str], list] = {}      # (folder, stem) → [(n, date)]
        self.stems: dict[str, list[str]] = {}               # folder → stem-urile, sortate (nume trunchiate)
        self.albums: dict[str, str] = {}                    # folder → numele albumului

    def add(self, path: str, data: dict) -> None:
        p = PurePosixPath(path)
        folder = p.parent.as_posix()
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            return
        if "photoTakenTime" not in data:
            if "url" not in data:  # metadata.json al unui album (numele fișierului variază cu limba)
                self.albums[folder] = title.strip()[:100]
            return
        stem, ext = os.path.splitext(title.lower())
        m = _JSON_DUP_RE.search(p.name)
        item = (int(m.group(1)) if m else 0, _facts(data))
        self.exact.setdefault((folder, stem, ext), []).append(item)
        if (folder, stem) not in self.by_stem:
            self.stems.setdefault(folder, []).append(stem)
        self.by_stem.setdefault((folder, stem), []).append(item)

    def done(self) -> None:
        for v in self.stems.values():
            v.sort()

    def find(self, path: str):
        p = PurePosixPath(path)
        folder = p.parent.as_posix()
        stem, ext, n = _split(p.name)

        def pick(items):
            if not items:
                return None
            return next((d for k, d in items if k == n), items[0][1])

        if found := pick(self.exact.get((folder, stem, ext))):
            return found
        if len(stem) >= 20:  # numele pozei trunchiat de Google (47 de caractere): titlul din json e întreg
            stems = self.stems.get(folder, [])
            i = bisect.bisect_left(stems, stem)
            if i < len(stems) and stems[i].startswith(stem):
                return pick(self.by_stem[(folder, stems[i])])
        # Live Photo / poză cu mișcare: videoul n-are json, îl ia de la poză
        return pick(self.by_stem.get((folder, stem)))


def _facts(data: dict) -> tuple:
    """(ora în ms sau None, (lat, lon) sau None, favorit, arhivat, șters)."""
    try:
        ts = int(data["photoTakenTime"]["timestamp"])
    except (TypeError, KeyError, ValueError):
        ts = 0
    gps = None
    for key in ("geoData", "geoDataExif"):
        try:
            if gps := geo._valid(float(data[key]["latitude"]), float(data[key]["longitude"])):
                break
        except (TypeError, KeyError, ValueError):
            continue
    return (ts * 1000 if ts > 0 else None, gps, bool(data.get("favorited")), bool(data.get("archived")),
            bool(data.get("trashed")))


def _year_fallback(path: str) -> str | None:
    """Folderul „Photos from 2019” (în orice limbă): fără altă dată, poza ajunge în anul ei, la 1 iulie."""
    m = _YEAR_RE.search(PurePosixPath(path).parent.name)
    return f"{m.group(1)}-07-01 12:00:00" if m else None


# ── Importul ───────────────────────────────────────────────────────────────────────────

def _album_id(conn, user: str, name: str, cache: dict) -> int:
    if name not in cache:
        row = conn.execute("SELECT id FROM albums WHERE user=? AND name=?", (user, name)).fetchone()
        cache[name] = row[0] if row else conn.execute(
            "INSERT INTO albums(user, name, created_at) VALUES(?,?,?)",
            (user, name, datetime.now(TZ).strftime(FMT))).lastrowid
    return cache[name]


def _copy(f, part: Path) -> str:
    h = hashlib.sha256()
    with open(part, "wb") as out:
        while block := f.read(1 << 20):
            h.update(block)
            out.write(block)
    return h.hexdigest()


def _date(info, part: Path, name: str, facts) -> tuple[str, bool, bool]:
    """(data, are dată adevărată, e precisă la secundă). Precisă = din poză (EXIF / film) sau de la Google,
    nu din numele fișierului (WhatsApp pune 12:00) și nici din folder."""
    hint = facts[0] if facts else None
    filename = PurePosixPath(name).name
    if info.taken_at or hint is not None or metadata.taken_at_from_name(filename):
        taken = metadata.resolve_taken_at(info, part, hint, name=filename)
        return taken, True, bool(info.taken_at or hint is not None) and not metadata._WA_RE.search(filename)
    return _year_fallback(name) or metadata.resolve_taken_at(info, part, None, name=filename), False, False


def _model(path: Path) -> str | None:
    try:
        with Image.open(path) as img:
            m = img.getexif().get(0x0110)
            return str(m).strip() or None if m else None
    except Exception:
        return None


def _dhash(path: Path) -> int | None:
    """Amprenta după cum arată poza (9×8, tonuri de gri): rămâne aproape la fel după micșorare și recomprimare."""
    try:
        with Image.open(path) as img:
            g = ImageOps.exif_transpose(img).convert("L").resize((9, 8), Image.LANCZOS)
            px = g.tobytes()  # un octet pe punct (tonuri de gri)
    except Exception:
        return None
    return sum(1 << i for i, (r, c) in enumerate((r, c) for r in range(8) for c in range(8))
               if px[r * 9 + c] < px[r * 9 + c + 1])


def _original_on_nas(conn, user: str, taken: str, info, part: Path) -> str | None:
    """Varianta Google micșorată („Economisire spațiu”) a unei poze care e deja pe NAS de pe telefon: aceeași
    secundă, același tip și aceeași formă, același aparat (când îl știm) și aceeași imagine (amprenta după
    cum arată; la filme, durata). Pozele importate tot de la Google nu contează: o rafală rămâne întreagă."""
    if not info.width or not info.height:
        return None
    rows = conn.execute("SELECT sha256, relpath, width, height, duration_ms FROM assets WHERE user=? AND taken_at=?"
                        " AND kind=? AND deleted_at IS NULL AND source != ?", (user, taken, info.kind, SOURCE)).fetchall()
    mine = model = None
    for r in rows:
        if not r["width"] or not r["height"] or abs(r["width"] / r["height"] - info.width / info.height) > 0.02:
            continue
        if info.kind == "video":
            if r["duration_ms"] is not None and info.duration_ms is not None \
                    and abs(r["duration_ms"] - info.duration_ms) <= 1000:
                return r["sha256"]
            continue
        theirs = photos_root(user) / r["relpath"]
        if mine is None:
            mine, model = _dhash(part), _model(part)
        other_model = _model(theirs)
        if model and other_model and model != other_model:
            continue
        other = _dhash(theirs)
        if mine is not None and other is not None and bin(mine ^ other).count("1") <= 10:
            return r["sha256"]
    return None


def _place(conn, user: str, part: Path, sha: str, taken: str, info, facts) -> None:
    """Poza nouă: locul în Photos, rândul din bază și locul pe hartă."""
    rel = naming.place_file(user, part, taken, SOURCE, part.suffix.lstrip("."))
    # data și pe fișier: în File Station, și pentru indexer dacă rândul de mai jos nu apucă să se salveze
    stamp = datetime.strptime(taken, FMT).replace(tzinfo=TZ).timestamp()
    os.utime(photos_root(user) / rel, (stamp, stamp))
    row = db.upsert_asset(conn, user, rel, sha, taken, info, SOURCE)
    gps = facts[1] if facts else None
    if gps:
        place = geo.nearest(*gps)
        conn.execute("UPDATE assets SET lat=?, lon=?, place_id=?, geo_done=1 WHERE id=?",
                     (gps[0], gps[1], geo._place_id(conn, place) if place else None, row["id"]))


def run_import(conn, user: str, progress: dict) -> dict:
    sources = _sources(user)
    side = Sidecars()
    rep = {"added": 0, "duplicates": 0, "originals": 0, "no_date": 0, "trashed": 0, "errors": 0, "albums": 0,
           "skipped": 0, "skipped_examples": [], "bad_archives": [], "disk_full": False}
    total = 0
    for src in sources:  # 1: json-urile (mici), numărul pozelor și ce nu putem importa
        try:
            for name, f in _entries(src, lambda n: True):
                if _is_media(name):
                    total += 1
                elif _is_json(name):
                    raw = f.read(JSON_MAX + 1)
                    try:
                        if len(raw) <= JSON_MAX and isinstance(data := json.loads(raw), dict):
                            side.add(name, data)
                    except (ValueError, UnicodeDecodeError):
                        pass
                elif _is_other(name):
                    rep["skipped"] += 1
                    if len(rep["skipped_examples"]) < EXAMPLES:
                        rep["skipped_examples"].append(PurePosixPath(name).name)
        except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError) as e:
            # o bucată descărcată pe jumătate: o raportăm și mergem mai departe cu celelalte
            log.warning("import Google %s: arhiva %s: %s", user, src.name, e)
            rep["bad_archives"].append(src.name)
    side.done()
    rep["albums"] = len(set(side.albums.values()))
    progress.update(total=total, done=0)

    ensure_photos(user)
    incoming = photos_root(user) / ".incoming"
    incoming.mkdir(exist_ok=True)
    albums: dict[str, int] = {}
    now = datetime.now(TZ).strftime(FMT)
    try:
        for src in sources:  # 2: pozele
            if src.name in rep["bad_archives"]:
                continue
            try:
                for name, f in _entries(src, _is_media):
                    progress["done"] += 1
                    _one(conn, user, name, f, side, incoming, albums, now, rep)
            except (zipfile.BadZipFile, tarfile.TarError, EOFError) as e:
                log.warning("import Google %s: arhiva %s: %s", user, src.name, e)
                rep["bad_archives"].append(src.name)
    except DiskFull:
        rep["disk_full"] = True
    conn.commit()
    return rep


def _one(conn, user, name, f, side, incoming, albums, now, rep) -> None:
    facts = side.find(name)
    if facts and facts[4]:
        rep["trashed"] += 1
        return
    part = incoming / f"g{secrets.token_hex(8)}.part.{Path(name).suffix.lower().lstrip('.')}"
    try:
        sha = _copy(f, part)
        live = conn.execute("SELECT 1 FROM assets WHERE user=? AND sha256=? AND deleted_at IS NULL",
                            (user, sha)).fetchone()
        seen = conn.execute("SELECT 1 FROM imported WHERE user=? AND sha256=?", (user, sha)).fetchone()
        conn.execute("INSERT OR IGNORE INTO imported(user, sha256) VALUES(?,?)", (user, sha))
        if live or seen:  # pe NAS deja, sau importată o dată și ștearsă de om: nu o aducem înapoi
            part.unlink()
            rep["duplicates"] += 1
        else:
            info = metadata.read_media_info(part)
            taken, dated, precise = _date(info, part, name, facts)
            original = _original_on_nas(conn, user, taken, info, part) if precise else None
            if original:  # originalul de pe telefon e deja aici: păstrăm originalul, albumul îl primește pe el
                part.unlink()
                rep["originals"] += 1
                sha = original
            else:
                _place(conn, user, part, sha, taken, info, facts)
                rep["added"] += 1
                rep["no_date"] += not dated
            live = True
        if live:
            album = side.albums.get(PurePosixPath(name).parent.as_posix())
            if album:
                conn.execute("INSERT OR IGNORE INTO album_items(album_id, sha256, added_at, user) VALUES(?,?,?,?)",
                             (_album_id(conn, user, album, albums), sha, now, user))
            if facts and facts[2]:
                conn.execute("INSERT OR IGNORE INTO favorites(user, sha256, added_at) VALUES(?,?,?)", (user, sha, now))
            if facts and facts[3]:
                conn.execute("INSERT OR IGNORE INTO archive(user, sha256, added_at) VALUES(?,?,?)", (user, sha, now))
        # salvat după fiecare poză: nu ținem baza blocată cât copiem următorul film (uploadurile și indexerul așteaptă)
        conn.commit()
    except Exception as e:
        conn.rollback()
        part.unlink(missing_ok=True)
        if isinstance(e, OSError) and e.errno == errno.ENOSPC:
            raise DiskFull from e
        log.warning("import Google %s: %r: %s", user, name, e)  # o poză stricată nu oprește importul
        rep["errors"] += 1


def _report_key(user: str) -> str:
    return f"import_google:{user}"


def _save_report(conn, user: str, rep: dict) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (_report_key(user), json.dumps(rep)))
    conn.commit()


def _worker(user: str, job: dict) -> None:
    conn = db.connect(get_settings().data_dir)
    try:
        # semnul că rulează: dacă NAS-ul repornește la mijloc, pagina arată că importul s-a întrerupt
        _save_report(conn, user, {"running": True, "started_at": job["started_at"]})
        rep = run_import(conn, user, job)
        rep["finished_at"] = datetime.now(TZ).strftime(FMT)
        _save_report(conn, user, rep)
    except Exception:
        log.exception("importul Google a eșuat pentru %s", user)
        _save_report(conn, user, {"failed": True, "finished_at": datetime.now(TZ).strftime(FMT)})
    finally:
        conn.close()
        with _jobs_guard:
            _jobs.pop(user, None)


def _ensure_folder(user: str) -> None:
    """Folderul apare singur în folderul personal, ca omul să-l găsească în File Station."""
    d = import_dir(user)
    if d.parent.is_dir() and not d.exists() and not d.is_symlink():
        try:
            d.mkdir()
            naming._chown(d, uid_of(user))
        except (OSError, KeyError) as e:
            log.warning("folderul de import pentru %s: %s", user, e)


@router.get("/api/import/google")
def status(user: str = Depends(current_user), conn=Depends(get_db)):
    _ensure_folder(user)
    d = import_dir(user)
    found = [{"name": p.name if p != d else FOLDER, "size": p.stat().st_size if p.is_file() else None}
             for p in _sources(user)]
    row = conn.execute("SELECT value FROM meta WHERE key=?", (_report_key(user),)).fetchone()
    last = json.loads(row[0]) if row else None
    with _jobs_guard:
        job = dict(_jobs[user]) if user in _jobs else None
    if last and last.get("running") and job is None:
        last = {"interrupted": True, "finished_at": last.get("started_at")}
    return {"found": found, "job": job, "last": None if job else last}


@router.post("/api/import/google")
def start(user: str = Depends(current_user)):
    if not _sources(user):
        raise ApiError(404, NOTHING)
    with _jobs_guard:
        if user in _jobs:
            raise ApiError(409, RUNNING)
        if _jobs:
            raise ApiError(409, BUSY)
        job = _jobs[user] = {"done": 0, "total": None, "started_at": datetime.now(TZ).strftime(FMT)}
    threading.Thread(target=_worker, args=(user, job), name=f"import-{user}", daemon=True).start()
    return {"job": dict(job)}
