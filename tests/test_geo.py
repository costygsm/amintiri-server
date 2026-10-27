import pytest

from poze import auth, db, geo, indexer
from poze.users import photos_root
from tests.fixtures import HAS_FFMPEG, make_jpeg, make_mp4

AVRIG = (45.7167, 24.3833)


def headers(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        return {"Authorization": f"Bearer {auth.issue_token(conn, user, 'tel')}"}
    finally:
        conn.close()


def index(env, user="ana"):
    conn = db.connect(env["data"])
    try:
        indexer.scan_user(conn, user)
        geo.backfill(conn, user)
    finally:
        conn.close()


def test_read_gps_from_jpeg(tmp_path):
    p = make_jpeg(tmp_path / "a.jpg", "2024:05:01 10:00:00", gps=AVRIG)
    lat, lon = geo.read_gps(p)
    assert lat == pytest.approx(45.7167, abs=1e-4) and lon == pytest.approx(24.3833, abs=1e-4)
    assert geo.read_gps(make_jpeg(tmp_path / "b.jpg", "2024:05:01 10:00:00")) is None


def test_southern_western_hemisphere(tmp_path):
    lat, lon = geo.read_gps(make_jpeg(tmp_path / "s.jpg", gps=(-33.8688, -70.6693)))
    assert lat == pytest.approx(-33.8688, abs=1e-4) and lon == pytest.approx(-70.6693, abs=1e-4)


def test_iso6709():
    assert geo.parse_iso6709("+44.2013+028.6140/") == (44.2013, 28.614)
    assert geo.parse_iso6709("-33.8688+151.2093+012.000/") == (-33.8688, 151.2093)
    assert geo.parse_iso6709("nimic") is None
    assert geo.parse_iso6709("+00.0000+000.0000/") is None  # telefon fără fix GPS


def test_nearest_city():
    p = geo.nearest(45.72, 24.38)
    assert (p.name, p.country, p.region) == ("Avrig", "România", "Sibiu")
    assert geo.nearest(0.0, -30.0) is None  # în mijlocul oceanului


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg lipsește (rulează în container)")
def test_read_gps_from_video(tmp_path):
    p = make_mp4(tmp_path / "v.mp4", location="+44.2013+028.6140/")
    assert geo.read_gps(p) == pytest.approx((44.2013, 28.614), abs=1e-4)


def test_backfill_sets_place_once(env):
    make_jpeg(photos_root("ana") / "a.jpg", "2024:05:01 10:00:00", gps=AVRIG)
    make_jpeg(photos_root("ana") / "b.jpg", "2024:05:02 10:00:00", size=(65, 48))
    index(env)
    conn = db.connect(env["data"])
    rows = {r["relpath"]: r for r in conn.execute("select * from assets")}
    assert rows["a.jpg"]["place_id"] is not None and rows["a.jpg"]["geo_done"] == 1
    assert rows["b.jpg"]["place_id"] is None and rows["b.jpg"]["geo_done"] == 1
    assert geo.backfill(conn, "ana") == 0  # nimic de refăcut


def test_places_api(client, env):
    make_jpeg(photos_root("ana") / "a.jpg", "2024:05:01 10:00:00", gps=AVRIG)
    make_jpeg(photos_root("ana") / "b.jpg", "2024:06:01 10:00:00", size=(70, 48), gps=(45.80, 24.15))
    make_jpeg(photos_root("ana") / "c.jpg", "2024:07:01 10:00:00", size=(71, 48), gps=(45.715, 24.39))
    make_jpeg(photos_root("bogdan") / "x.jpg", "2024:05:01 10:00:00", gps=(44.43, 26.10))
    index(env)
    index(env, "bogdan")
    places = client.get("/api/places", headers=headers(env)).json()["places"]
    assert [(p["name"], p["count"]) for p in places] == [("Avrig", 2), ("Sibiu", 1)]
    avrig = places[0]
    assert avrig["region"] == "Sibiu" and avrig["country"] == "România"
    en = client.get("/api/places", headers={**headers(env), "Accept-Language": "en-US"}).json()["places"]
    assert en[0]["name"] == "Avrig" and en[0]["country"] == "Romania"
    assert avrig["lat"] == pytest.approx(45.7167, abs=1e-3)
    page = client.get(f"/api/places/{avrig['id']}/assets", headers=headers(env)).json()
    assert [a["taken_at"] for a in page["items"]] == ["2024-07-01 10:00:00", "2024-05-01 10:00:00"]
    assert avrig["cover_id"] == page["items"][0]["id"]
    # locul altcuiva nu se vede
    other = client.get("/api/places", headers=headers(env, "bogdan")).json()["places"]
    assert client.get(f"/api/places/{other[0]['id']}/assets", headers=headers(env)).json()["items"] == []


def test_big_city_wins_over_suburb_and_neighbourhood():
    assert geo.nearest(41.8925, 12.4853).name == "Roma"           # Celio, în centru
    assert geo.nearest(52.5200, 13.4050).name == "Berlin"         # Mitte
    assert geo.nearest(44.2180, 28.5953).name == "Constanța"      # Palazu Mare e sat lipit


def test_relocate_once(env):
    make_jpeg(photos_root("ana") / "a.jpg", "2024:05:01 10:00:00", gps=AVRIG)
    index(env)
    conn = db.connect(env["data"])
    conn.execute("UPDATE places SET name='Vechi'")
    conn.execute("DELETE FROM meta")
    conn.commit()
    assert geo.relocate(conn) == 1
    assert conn.execute("select p.name from assets a join places p on p.id=a.place_id").fetchone()[0] == "Avrig"
    assert geo.relocate(conn) == 0


def test_bucharest_in_romanian():
    p = geo.nearest(44.4268, 26.1025)
    assert (p.name, p.region) == ("București", "București")
