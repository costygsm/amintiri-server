from datetime import date

from poze import auth, db
from poze.memories import on_this_day

_n = 0


def add(conn, taken, user="ana", sha=None, source="Camera", w=4000, h=3000):
    global _n
    _n += 1
    conn.execute(
        "insert into assets(user, relpath, sha256, size, mtime, taken_at, kind, width, height, source)"
        " values(?,?,?,?,?,?,?,?,?,?)",
        (user, f"f{_n}.jpg", sha or f"{_n:064x}", 1, 0, taken, "photo", w, h, source))
    conn.commit()


def years(result):
    return [y["years_ago"] for y in result]


def test_groups_by_year(env):
    conn = db.connect(env["data"])
    for t in ("2023-10-26 10:00:00", "2025-10-26 10:00:00", "2025-10-27 10:00:00", "2026-10-26 08:00:00"):
        add(conn, t)
    res = on_this_day(conn, "ana", date(2026, 10, 26))
    assert years(res) == [1, 3]
    assert [y["year"] for y in res] == [2025, 2023]
    # are poză fix în ziua asta: zilele din jur nu mai intră (altfel o vacanță întreagă ajunge „amintire”)
    assert [i["taken_at"] for i in res[0]["items"]] == ["2025-10-26 10:00:00"]


def test_days_around_only_without_exact_day(env):
    conn = db.connect(env["data"])
    add(conn, "2025-10-25 10:00:00")
    add(conn, "2025-10-28 10:00:00")
    items = on_this_day(conn, "ana", date(2026, 10, 26))[0]["items"]
    assert [i["taken_at"] for i in items] == ["2025-10-25 10:00:00", "2025-10-28 10:00:00"]


def test_window_three_days(env):
    # ca Google Photos: anii fără poză fix în ziua asta apar cu pozele din jur (±3 zile), nu mai departe
    conn = db.connect(env["data"])
    add(conn, "2024-10-23 10:00:00")  # -3: intră
    add(conn, "2022-10-29 23:59:00")  # +3: intră
    add(conn, "2021-10-22 10:00:00")  # -4: nu
    add(conn, "2020-10-30 00:00:00")  # +4: nu
    assert [y["year"] for y in on_this_day(conn, "ana", date(2026, 10, 26))] == [2024, 2022]


def test_new_year_boundary(env):
    conn = db.connect(env["data"])
    add(conn, "2025-12-30 10:00:00")  # acum 3 zile: nu e amintire
    add(conn, "2024-12-31 10:00:00")  # în fereastra lui 2 ianuarie 2025: acum 1 an
    add(conn, "2025-01-04 10:00:00")
    res = on_this_day(conn, "ana", date(2026, 1, 2))
    assert [(y["year"], y["years_ago"], len(y["items"])) for y in res] == [(2025, 1, 2)]


def test_empty_library(env):
    assert on_this_day(db.connect(env["data"]), "ana", date(2026, 10, 26)) == []


def test_excludes_screenshots(env):
    conn = db.connect(env["data"])
    add(conn, "2025-10-26 10:00:00", source="Screenshots")
    add(conn, "2025-10-26 11:00:00", source="CapturiDeEcran")
    add(conn, "2025-10-26 12:00:00", w=150, h=100)
    assert on_this_day(conn, "ana", date(2026, 10, 26)) == []
    add(conn, "2025-10-26 13:00:00", w=None, h=None)  # Ruling 2: fără dimensiuni rămâne
    assert years(on_this_day(conn, "ana", date(2026, 10, 26))) == [1]


def test_burst_collapsed(env):
    conn = db.connect(env["data"])
    for s in range(5):
        add(conn, f"2025-10-26 10:00:0{s}")
    add(conn, "2025-10-26 10:00:30")
    items = on_this_day(conn, "ana", date(2026, 10, 26))[0]["items"]
    assert [i["taken_at"] for i in items] == ["2025-10-26 10:00:00", "2025-10-26 10:00:30"]


def test_cap_per_year(env):
    conn = db.connect(env["data"])
    for i in range(100):
        add(conn, f"2025-10-26 {8 + i // 60:02}:{i % 60:02}:00")
    items = on_this_day(conn, "ana", date(2026, 10, 26))[0]["items"]
    assert len(items) == 12
    assert items[0]["taken_at"] == "2025-10-26 08:00:00"
    assert items[-1]["taken_at"] == "2025-10-26 09:39:00"


def test_feb29_on_feb28(env):
    conn = db.connect(env["data"])
    add(conn, "2024-02-29 10:00:00")
    assert years(on_this_day(conn, "ana", date(2025, 2, 28))) == [1]
    assert years(on_this_day(conn, "ana", date(2028, 2, 28))) == [4]  # în fereastra de ±3 zile
    assert years(on_this_day(conn, "ana", date(2029, 3, 1))) == [5]


def test_dedup_sha(env):
    conn = db.connect(env["data"])
    add(conn, "2025-10-26 10:00:00", sha="a" * 64)
    add(conn, "2025-10-26 10:00:00", sha="a" * 64)
    add(conn, "2025-10-26 10:00:00", sha="b" * 64, user="bogdan")
    res = on_this_day(conn, "ana", date(2026, 10, 26))
    assert len(res[0]["items"]) == 1


def test_route(client, env):
    conn = db.connect(env["data"])
    add(conn, "2024-10-26 10:00:00")
    h = {"Authorization": f"Bearer {auth.issue_token(conn, 'ana', 't')}"}
    r = client.get("/api/memories", params={"date": "2026-10-26"}, headers=h)
    assert r.json()["years"][0]["years_ago"] == 2
    assert set(r.json()["years"][0]["items"][0]) >= {"id", "sha256", "taken_at"}
    assert client.get("/api/memories", params={"date": "26.10.2026"}, headers=h).status_code == 422
