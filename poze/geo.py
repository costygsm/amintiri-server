"""Locul pozelor: GPS din EXIF / din film, apoi cel mai apropiat oraș dintr-o listă offline (GeoNames).

Nimic nu pleacă de pe NAS: lista de orașe e în `date/orase.tsv.gz` (vezi tools/geonames.py).
"""
import gzip
import json
import logging
import math
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import metadata
from .users import photos_root

log = logging.getLogger(__name__)

CITIES = Path(__file__).parent / "date" / "orase.tsv.gz"
MAX_KM = 30  # mai departe de atât de orice oraș: fără loc (mare, munte izolat)

COUNTRIES = {
    "RO": "România", "MD": "Republica Moldova", "HU": "Ungaria", "BG": "Bulgaria", "RS": "Serbia",
    "UA": "Ucraina", "GR": "Grecia", "TR": "Turcia", "IT": "Italia", "ES": "Spania", "FR": "Franța",
    "DE": "Germania", "AT": "Austria", "CH": "Elveția", "GB": "Regatul Unit", "IE": "Irlanda",
    "NL": "Țările de Jos", "BE": "Belgia", "LU": "Luxemburg", "PT": "Portugalia", "PL": "Polonia",
    "CZ": "Cehia", "SK": "Slovacia", "SI": "Slovenia", "HR": "Croația", "BA": "Bosnia și Herțegovina",
    "ME": "Muntenegru", "MK": "Macedonia de Nord", "AL": "Albania", "CY": "Cipru", "MT": "Malta",
    "DK": "Danemarca", "SE": "Suedia", "NO": "Norvegia", "FI": "Finlanda", "IS": "Islanda",
    "EE": "Estonia", "LV": "Letonia", "LT": "Lituania", "US": "Statele Unite", "CA": "Canada",
    "EG": "Egipt", "TN": "Tunisia", "MA": "Maroc", "AE": "Emiratele Arabe Unite", "TH": "Thailanda",
    "IL": "Israel", "JP": "Japonia", "CN": "China", "MX": "Mexic", "BR": "Brazilia", "RU": "Rusia",
}


# GeoNames dă numele în engleză pentru orașele mari; pe cele știute le spunem pe românește
EXONYMS = {
    "Bucharest": "București", "Rome": "Roma", "Vienna": "Viena", "Prague": "Praga", "Venice": "Veneția",
    "Florence": "Florența", "Milan": "Milano", "Naples": "Napoli", "Turin": "Torino", "Genoa": "Genova",
    "Munich": "München", "Cologne": "Köln", "Nuremberg": "Nürnberg", "Athens": "Atena",
    "Thessaloniki": "Salonic", "Lisbon": "Lisabona", "Warsaw": "Varșovia", "Krakow": "Cracovia",
    "Moscow": "Moscova", "Copenhagen": "Copenhaga", "Brussels": "Bruxelles", "The Hague": "Haga",
    "Belgrade": "Belgrad", "Kyiv": "Kiev", "Odesa": "Odesa", "Chisinau": "Chișinău", "Istanbul": "Istanbul",
    "London": "Londra", "Edinburgh": "Edinburgh", "Seville": "Sevilla", "Saragossa": "Zaragoza",
    "Geneva": "Geneva", "Zurich": "Zürich", "Antwerp": "Anvers", "Bruges": "Brugge",
    "Sofia": "Sofia", "Budapest": "Budapesta", "Bratislava": "Bratislava", "Ljubljana": "Ljubljana",
}
REGIONS = {"Bucharest": "București", "State of Berlin": "Berlin", "Land Berlin": "Berlin"}

# În baza de date locurile stau pe românește; pentru cine folosește aplicația în engleză le traducem la ieșire
COUNTRIES_EN = {
    "RO": "Romania", "MD": "Moldova", "HU": "Hungary", "BG": "Bulgaria", "RS": "Serbia",
    "UA": "Ukraine", "GR": "Greece", "TR": "Turkey", "IT": "Italy", "ES": "Spain", "FR": "France",
    "DE": "Germany", "AT": "Austria", "CH": "Switzerland", "GB": "United Kingdom", "IE": "Ireland",
    "NL": "Netherlands", "BE": "Belgium", "LU": "Luxembourg", "PT": "Portugal", "PL": "Poland",
    "CZ": "Czechia", "SK": "Slovakia", "SI": "Slovenia", "HR": "Croatia", "BA": "Bosnia and Herzegovina",
    "ME": "Montenegro", "MK": "North Macedonia", "AL": "Albania", "CY": "Cyprus", "MT": "Malta",
    "DK": "Denmark", "SE": "Sweden", "NO": "Norway", "FI": "Finland", "IS": "Iceland",
    "EE": "Estonia", "LV": "Latvia", "LT": "Lithuania", "US": "United States", "CA": "Canada",
    "EG": "Egypt", "TN": "Tunisia", "MA": "Morocco", "AE": "United Arab Emirates", "TH": "Thailand",
    "IL": "Israel", "JP": "Japan", "CN": "China", "MX": "Mexico", "BR": "Brazil", "RU": "Russia",
}
_EN = {**{ro: COUNTRIES_EN[cc] for cc, ro in COUNTRIES.items()},
       **{ro: en for en, ro in EXONYMS.items() if en != ro},
       **{ro: en for en, ro in REGIONS.items() if en != ro and ro != "Berlin"}}


def english(name: str) -> str:
    """„Roma” → „Rome”, „Grecia” → „Greece”; ce nu știm rămâne cum e."""
    return _EN.get(name, name)


@dataclass(frozen=True)
class Place:
    name: str
    region: str
    country: str
    lat: float
    lon: float


_grid: dict[tuple[int, int], list[tuple[float, float, str, str, str]]] | None = None
_grid_lock = threading.Lock()


def _region(cc: str, region: str) -> str:
    # „Sibiu County” → „Sibiu”; „Bucuresti” rămâne
    return re.sub(r"\s+County$", "", region) if cc == "RO" else region


def _load():
    global _grid
    with _grid_lock:
        if _grid is not None:
            return _grid
        grid: dict = {}
        with gzip.open(CITIES, "rt", encoding="utf-8") as f:
            for line in f:
                name, lat, lon, cc, region, pop = line.rstrip("\n").split("\t")
                la, lo = float(lat), float(lon)
                grid.setdefault((math.floor(la), math.floor(lo)), []).append((la, lo, name, cc, region, int(pop or 0)))
        _grid = grid
        return grid


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def _radius_km(pop: int) -> float:
    """Cât „acoperă” un oraș în jurul centrului: ~1 km la 5.000 de locuitori, ~10 km la 300.000, max 25."""
    return min(25.0, max(0.5, math.sqrt(pop) / 55))


def nearest(lat: float, lon: float) -> Place | None:
    """Orașul în care pare făcută poza: cel cu marginea cea mai apropiată, ca un sat de lângă un
    oraș mare să nu „fure” pozele făcute în oraș."""
    grid = _load()
    best, best_score = None, None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for c in grid.get((math.floor(lat) + dy, math.floor(lon) + dx), ()):
                d = _km(lat, lon, c[0], c[1])
                if d > MAX_KM:
                    continue
                score = d - _radius_km(c[5])
                if best_score is None or score < best_score:
                    best, best_score = c, score
    if best is None:
        return None
    la, lo, name, cc, region, _pop = best
    region = _region(cc, region)
    return Place(_ro(EXONYMS.get(name, name)), _ro(REGIONS.get(region, region)), COUNTRIES.get(cc, cc), la, lo)


def _ro(s: str) -> str:
    # GeoNames are încă diacriticele vechi cu sedilă (Constanţa)
    return s.replace("ţ", "ț").replace("ş", "ș").replace("Ţ", "Ț").replace("Ş", "Ș")


def _ratio(v) -> float:
    return float(v[0]) / float(v[1]) if isinstance(v, tuple) else float(v)


def _from_exif(path: Path) -> tuple[float, float] | None:
    try:
        with Image.open(path) as img:
            g = img.getexif().get_ifd(0x8825)
    except Exception:
        return None
    try:
        lat = sum(_ratio(x) / 60 ** i for i, x in enumerate(g[2]))
        lon = sum(_ratio(x) / 60 ** i for i, x in enumerate(g[4]))
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    if str(g.get(1, "N")).upper().startswith("S"):
        lat = -lat
    if str(g.get(3, "E")).upper().startswith("W"):
        lon = -lon
    return _valid(lat, lon)


_ISO6709 = re.compile(r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def _valid(lat: float, lon: float) -> tuple[float, float] | None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 1e-6 and abs(lon) < 1e-6):
        return None
    return round(lat, 6), round(lon, 6)


def parse_iso6709(s: str) -> tuple[float, float] | None:
    m = _ISO6709.match(s.strip())
    return _valid(float(m.group(1)), float(m.group(2))) if m else None


def _from_video(path: Path) -> tuple[float, float] | None:
    try:
        out = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
                             capture_output=True, timeout=60, check=True).stdout
        tags = json.loads(out).get("format", {}).get("tags", {})
    except Exception:
        return None
    for k, v in tags.items():
        if k.lower().startswith("location") or k.lower().endswith("iso6709"):
            if r := parse_iso6709(str(v)):
                return r
    return None


def read_gps(path: Path) -> tuple[float, float] | None:
    kind = metadata.kind_of(path)
    if kind == "photo":
        return _from_exif(path)
    if kind == "video":
        return _from_video(path)
    return None


def _place_id(conn, p: Place) -> int:
    row = conn.execute("SELECT id FROM places WHERE name=? AND region=? AND country=?",
                       (p.name, p.region, p.country)).fetchone()
    if row:
        return row[0]
    return conn.execute("INSERT INTO places(name, region, country, lat, lon) VALUES(?,?,?,?,?)",
                        (p.name, p.region, p.country, p.lat, p.lon)).lastrowid


# crește când se schimbă lista de orașe sau regula de alegere: locurile se refac din coordonate
PLACES_VERSION = 3


def relocate(conn) -> int:
    """Recalculează locul din lat/lon deja salvate (fără să recitească fișierele)."""
    row = conn.execute("SELECT value FROM meta WHERE key='places_version'").fetchone()
    if row and int(row[0]) == PLACES_VERSION:
        return 0
    rows = conn.execute("SELECT id, lat, lon FROM assets WHERE lat IS NOT NULL").fetchall()
    found = [(r["id"], nearest(r["lat"], r["lon"])) for r in rows]
    conn.execute("UPDATE assets SET place_id=NULL")
    conn.execute("DELETE FROM places")
    for aid, place in found:
        if place:
            conn.execute("UPDATE assets SET place_id=? WHERE id=?", (_place_id(conn, place), aid))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('places_version', ?)", (str(PLACES_VERSION),))
    conn.commit()
    return len(found)


def backfill(conn, user: str, batch: int = 200) -> int:
    """Citește locul pentru pozele încă necitite; întoarce câte a citit. Pornit de indexer."""
    root = photos_root(user)
    done = 0
    while True:
        rows = conn.execute("SELECT id, relpath FROM assets WHERE user=? AND geo_done=0 AND deleted_at IS NULL "
                            "LIMIT ?", (user, batch)).fetchall()
        if not rows:
            return done
        # întâi citim (ffprobe poate dura), apoi scriem într-o tranzacție scurtă: uploadurile nu așteaptă
        found = []
        for r in rows:
            gps = read_gps(root / r["relpath"])
            found.append((r["id"], gps, nearest(*gps) if gps else None))
        for aid, gps, place in found:
            conn.execute("UPDATE assets SET lat=?, lon=?, place_id=?, geo_done=1 WHERE id=?",
                         (gps[0] if gps else None, gps[1] if gps else None,
                          _place_id(conn, place) if place else None, aid))
        conn.commit()
        done += len(found)
