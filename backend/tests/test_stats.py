import time
from datetime import date

import pytest

from app.stats import play_time
from tests.test_sessions import add_game


@pytest.fixture
def tz():
    mp = pytest.MonkeyPatch()  # its own instance: undo() must not touch the conftest isolation

    def set_tz(name):
        mp.setenv("TZ", name)
        time.tzset()

    yield set_tz
    mp.undo()
    time.tzset()


def add_session(conn, game_id, start, end):
    conn.execute("INSERT INTO sessions (game_id, started_at, ended_at) VALUES (?, ?, ?)", (game_id, start, end))
    conn.commit()


def test_session_across_local_midnight_is_split(conn, tz):
    tz("America/Sao_Paulo")  # UTC-3
    g = add_game(conn)
    add_session(conn, g, "2026-05-11T02:30:00Z", "2026-05-11T03:30:00Z")  # 23:30 -> 00:30 local
    assert play_time.per_day(conn) == {date(2026, 5, 10): 1800, date(2026, 5, 11): 1800}


def test_dst_day_is_23_hours_not_24(conn, tz):
    tz("America/New_York")  # spring forward on 2026-03-08
    g = add_game(conn)
    add_session(conn, g, "2026-03-08T05:00:00Z", "2026-03-09T04:00:00Z")  # local midnight to midnight
    assert play_time.per_day(conn) == {date(2026, 3, 8): 23 * 3600}


def test_per_game_platform_and_day_totals_agree(conn, tz):
    tz("America/Sao_Paulo")
    a, b = add_game(conn, "A"), add_game(conn, "B")
    add_session(conn, a, "2026-05-10T12:00:00Z", "2026-05-10T13:00:00Z")
    add_session(conn, a, "2026-05-11T02:30:00Z", "2026-05-11T03:30:00Z")
    add_session(conn, b, "2026-05-12T10:00:00Z", "2026-05-12T10:10:00Z")
    games = play_time.per_game(conn)
    assert games[a]["seconds"] == 7200 and games[a]["sessions"] == 2 and games[b]["seconds"] == 600
    total = sum(v["seconds"] for v in games.values())
    assert sum(play_time.per_day(conn).values()) == total == sum(play_time.per_platform(conn).values())


def test_open_session_counts_up_to_its_last_heartbeat(conn):
    g = add_game(conn)
    conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, '2026-05-10T12:00:00Z', '2026-05-10T12:20:00Z')", (g,))
    conn.commit()
    assert play_time.per_game(conn)[g]["seconds"] == 1200


def test_weeks_start_on_monday_and_months_group_days(conn, tz):
    tz("UTC")
    g = add_game(conn)
    add_session(conn, g, "2026-05-10T10:00:00Z", "2026-05-10T11:00:00Z")  # Sunday
    add_session(conn, g, "2026-05-11T10:00:00Z", "2026-05-11T10:30:00Z")  # Monday
    add_session(conn, g, "2026-06-01T10:00:00Z", "2026-06-01T10:10:00Z")
    weeks = {p["period"]: p["seconds"] for p in play_time.per_period(conn, "week", 5, today=date(2026, 6, 1))}
    assert weeks["2026-05-04"] == 3600 and weeks["2026-05-11"] == 1800 and weeks["2026-06-01"] == 600
    months = play_time.per_period(conn, "month", 3, today=date(2026, 6, 15))
    assert [(m["period"], m["seconds"]) for m in months] == [("2026-04", 0), ("2026-05", 5400), ("2026-06", 600)]
    days = play_time.per_period(conn, "day", 3, today=date(2026, 5, 12))
    assert [d["period"] for d in days] == ["2026-05-10", "2026-05-11", "2026-05-12"]
    assert [d["seconds"] for d in days] == [3600, 1800, 0]


def test_journal_pages_whole_local_days_and_uses_recorded_session_time(conn, tz):
    tz("America/Sao_Paulo")
    a = add_game(conn, "A")
    b = add_game(conn, "B")
    add_session(conn, a, "2026-05-12T02:00:00Z", "2026-05-12T03:05:00Z")  # starts on May 11
    add_session(conn, a, "2026-05-11T14:00:00Z", "2026-05-11T14:05:00Z")
    add_session(conn, b, "2026-05-10T20:00:00Z", "2026-05-10T20:00:03Z")
    conn.execute(
        "INSERT INTO sessions(game_id, started_at, last_heartbeat) VALUES (?, ?, ?)",
        (b, "2026-05-11T16:00:00Z", "2026-05-11T16:01:00Z"),
    )
    page = play_time.journal(conn, days=1)
    assert page["next_before"] == "2026-05-11"
    day, = page["days"]
    assert day["day"] == "2026-05-11"
    assert [(r["game_id"], r["sessions"], r["seconds"]) for r in day["games"]] == [(a, 2, 4200), (b, 1, 60)]
    older = play_time.journal(conn, date.fromisoformat(page["next_before"]), days=1)
    assert older["next_before"] is None
    assert [d["day"] for d in older["days"]] == ["2026-05-10"]
