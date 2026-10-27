from poze.extras import parse_query


def test_english_months_and_seasons():
    assert parse_query("summer 2024")["months"] == [6, 7, 8]
    assert parse_query("summer 2024")["year"] == 2024
    assert parse_query("June")["months"] == [6]
    assert parse_query("photos from Rome")["text"] == "Rome"
    assert parse_query("fall")["months"] == [9, 10, 11]


def test_romanian_still_wins():
    assert parse_query("mar")["months"] == [3]   # martie (în engleză ar fi ambiguu: march/may)
    assert parse_query("vara 2023")["months"] == [6, 7, 8]
    assert parse_query("mai")["months"] == [5]
