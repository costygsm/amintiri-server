"""Amintirile „În ziua asta”: pozele din aceeași zi, în anii trecuți."""
import calendar
from datetime import date, datetime

from .db import asset_json
from .metadata import FMT

MAX_PER_YEAR = 24
BURST_SECONDS = 3
MIN_SIDE = 200


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


def on_this_day(conn, user: str, day: date) -> list[dict]:
    days = [day.strftime("%m-%d")]
    if days[0] == "02-28" and not calendar.isleap(day.year):
        days.append("02-29")
    marks = ",".join("?" * len(days))
    rows = conn.execute(
        f"SELECT * FROM assets WHERE user=? AND deleted_at IS NULL AND substr(taken_at, 6, 5) IN ({marks})"
        " AND substr(taken_at, 1, 4) < ? ORDER BY taken_at, id",
        (user, *days, f"{day.year:04}")).fetchall()
    seen: set[str] = set()
    by_year: dict[int, list] = {}
    prev: dict[int, datetime] = {}
    for row in rows:
        if row["sha256"] in seen or not _keep(row):
            continue
        seen.add(row["sha256"])
        t = datetime.strptime(row["taken_at"], FMT)
        last, prev[t.year] = prev.get(t.year), t
        if last is not None and (t - last).total_seconds() < BURST_SECONDS:
            continue  # rafală: rămâne prima
        by_year.setdefault(t.year, []).append(row)
    return [{"years_ago": day.year - y, "year": y, "items": [asset_json(r) for r in _spread(by_year[y])]}
            for y in sorted(by_year, reverse=True)]
