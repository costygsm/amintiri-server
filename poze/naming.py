import logging
import os
import re
import unicodedata
from pathlib import Path

from . import users

MONTHS = (
    "ianuarie februarie martie aprilie mai iunie iulie august septembrie octombrie noiembrie decembrie"
).split()
GID = 100
log = logging.getLogger(__name__)
_TAKEN_RE = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01]) ([01][0-9]|2[0-3]):[0-5]\d:[0-5]\d")
_EXT_RE = re.compile(r"[a-z0-9]{1,10}")
MAX_ATTEMPTS = 10_000


def clean_source(source: str) -> str:
    base = unicodedata.normalize("NFD", source or "")
    base = base.encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]", "", base)[:40] or "Telefon"


def target_relpath(taken_at: str, source: str, ext: str, n: int = 1) -> str:
    if not _TAKEN_RE.fullmatch(taken_at):
        raise ValueError(f"dată invalidă: {taken_at!r}")
    ext = ext.lower().lstrip(".")
    if not _EXT_RE.fullmatch(ext):
        raise ValueError(f"extensie invalidă: {ext!r}")
    date, time = taken_at.split(" ")
    year, month, _ = date.split("-")
    suffix = "" if n <= 1 else f"_{n}"
    name = f"{date}_{time.replace(':', '-')}_{clean_source(source)}{suffix}.{ext}"
    return f"{year}/{month}-{MONTHS[int(month) - 1]}/{name}"


def _make_dirs(user: str, rel_dir: str, uid: int) -> None:
    target = users.safe_path(user, rel_dir)
    new = []
    d = target
    while not d.exists():
        new.append(d)
        d = d.parent
    os.makedirs(target, exist_ok=True)
    for d in reversed(new):
        os.chown(d, uid, GID)


def place_file(user: str, part: Path, taken_at: str, source: str, ext: str) -> str:
    uid = users.uid_of(user)
    for n in range(1, MAX_ATTEMPTS + 1):
        rel = target_relpath(taken_at, source, ext, n)
        final = users.safe_path(user, rel)
        _make_dirs(user, str(Path(rel).parent), uid)
        try:
            os.link(part, final)
        except FileExistsError:
            continue
        try:
            os.chown(final, uid, GID)
            os.chmod(final, 0o644)
        except BaseException:
            try:
                os.unlink(final)
            except OSError:
                pass
            raise
        try:
            os.unlink(part)
        except OSError as e:
            log.warning("nu s-a putut șterge partea %s: %s", part, e)
        return rel
    raise RuntimeError(f"nu s-a găsit un nume liber după {MAX_ATTEMPTS} încercări")
