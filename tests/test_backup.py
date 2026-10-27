import sqlite3
from datetime import date, timedelta

from poze import backup, db


def test_daily_copy_once_per_day_keeps_seven(tmp_path):
    conn = db.connect(tmp_path)
    conn.execute("INSERT INTO albums(user, name, created_at) VALUES('ana', 'Vara', '2026-10-27 10:00:00')")
    conn.commit()
    start = date(2026, 10, 1)
    for i in range(10):
        backup.daily(conn, tmp_path, today=start + timedelta(days=i))
    assert backup.daily(conn, tmp_path, today=start + timedelta(days=9)) is None  # a doua oară în aceeași zi
    files = sorted(p.name for p in (tmp_path / "backup").iterdir())
    assert files == [f"poze-{(start + timedelta(days=i)).isoformat()}.db" for i in range(3, 10)]
    copy = sqlite3.connect(tmp_path / "backup" / files[-1])
    assert copy.execute("SELECT name FROM albums").fetchone()[0] == "Vara"
