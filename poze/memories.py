"""Amintirile „În ziua asta”: pozele din jurul aceleiași zile, în anii trecuți."""
from datetime import date, datetime, timedelta

from .db import asset_json
from .metadata import FMT

MAX_PER_YEAR = 12
BURST_SECONDS = 3
MIN_SIDE = 200
# ca Google Photos: anii fără poză fix în ziua asta vin cu pozele de cu câteva zile înainte/după;
# anii cu poze în ziua asta rămân doar cu ele (altfel o vacanță întreagă ajunge în amintire)
WINDOW_DAYS = 3


def _keep(row) -> bool:
    src = (row["source"] or "").lower()
    if "screenshot" in src or "captur" in src:
        return False
    w, h = row["width"], row["height"]
    return w is None or h is None or max(w, h) >= MIN_SIDE  # Ruling 2


def _spread(items: list) -> list:
    n = len(items)
    if n <= MAX_PER_YEAR:
        return items
    return [items[round(i * (n - 1) / (MAX_PER_YEAR - 1))] for i in range(MAX_PER_YEAR)]


def _anniversary(day: date, year: int) -> date:
    try:
        return day.replace(year=year)
    except ValueError:  # 29 februarie într-un an nebisect
        return date(year, 2, 28)


def on_this_day(conn, user: str, day: date) -> list[dict]:
    first = conn.execute("SELECT min(taken_at) FROM assets WHERE user=? AND deleted_at IS NULL", (user,)).fetchone()[0]
    if not first:
        return []
    # pentru fiecare an trecut, o săptămână în jurul aniversării zilei; o poză aparține anului a cărui
    # aniversare o încadrează (pe 2 ianuarie, 30 decembrie de anul trecut e „acum 1 an” doar dacă e
    # din fereastra lui 2 ianuarie de anul trecut, nu „de acum câteva zile”)
    windows = []
    for y in range(int(first[:4]) - 1, day.year):
        a = _anniversary(day, y)
        windows.append((y, a - timedelta(days=WINDOW_DAYS), a + timedelta(days=WINDOW_DAYS)))
    where = " OR ".join("taken_at BETWEEN ? AND ?" for _ in windows)
    params = [v for _, lo, hi in windows for v in (f"{lo} 00:00:00", f"{hi} 23:59:59")]
    rows = conn.execute(
        f"SELECT * FROM assets WHERE user=? AND deleted_at IS NULL AND ({where})"
        " AND sha256 NOT IN (SELECT sha256 FROM archive WHERE user=?) ORDER BY taken_at, id",
        (user, *params, user)).fetchall()
    seen: set[str] = set()
    by_year: dict[int, list] = {}
    prev: dict[int, datetime] = {}
    for row in rows:
        if row["sha256"] in seen or not _keep(row):
            continue
        seen.add(row["sha256"])
        t = datetime.strptime(row["taken_at"], FMT)
        year = next(y for y, lo, hi in windows if lo <= t.date() <= hi)
        last, prev[year] = prev.get(year), t
        if last is not None and (t - last).total_seconds() < BURST_SECONDS:
            continue  # rafală: rămâne prima
        by_year.setdefault(year, []).append(row)
    out = []
    for y in sorted(by_year, reverse=True):
        exact = str(_anniversary(day, y))
        rows = [r for r in by_year[y] if r["taken_at"].startswith(exact)] or by_year[y]
        out.append({"years_ago": day.year - y, "year": y, "items": [asset_json(r) for r in _spread(rows)]})
    return out
