"""Tests for derived progress statistics: pace, remaining hours, and abandoned games."""

from datetime import datetime, timezone

from app.progress import engine
from app.stats import progress_stats


def _add_game(conn, key: str, title: str) -> int:
    cur = conn.execute(
        "INSERT INTO games (key, title, platform, identified) VALUES (?, ?, 'Nintendo - GameCube', 1)",
        (key, title),
    )
    conn.commit()
    return cur.lastrowid


def _add_session(conn, game_id: int, start: str, end: str) -> None:
    conn.execute(
        "INSERT INTO sessions (game_id, started_at, ended_at, last_heartbeat) VALUES (?, ?, ?, ?)",
        (game_id, start, end, end),
    )
    conn.commit()


def test_compute_pace_and_remaining_hours():
    # 50% done in 5 hours -> 10%/h, ~5h remaining
    pace, rem = progress_stats.compute_pace_and_remaining(
        mean=50.0, lower=40.0, upper=60.0, seconds_played=5 * 3600, ttb_hours=10.0
    )
    assert pace == 10.0
    assert rem == {"mean": 5.0, "min": 4.0, "max": 6.0}

    # Completed game -> 0h remaining
    _, rem_done = progress_stats.compute_pace_and_remaining(
        mean=100.0, lower=100.0, upper=100.0, seconds_played=8 * 3600, ttb_hours=10.0
    )
    assert rem_done == {"mean": 0.0, "min": 0.0, "max": 0.0}


def test_library_insights_separates_in_progress_and_abandoned(conn):
    active_id = _add_game(conn, "g-active", "Active Game")
    old_id = _add_game(conn, "g-old", "Abandoned Game")

    _add_session(conn, active_id, "2026-11-25T10:00:00Z", "2026-11-25T14:00:00Z")
    engine.set_ttb(conn, active_id, 10.0)
    engine.recompute(conn, active_id)

    _add_session(conn, old_id, "2026-09-01T10:00:00Z", "2026-09-01T13:00:00Z")
    engine.set_ttb(conn, old_id, 12.0)
    engine.recompute(conn, old_id)

    now = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
    ins = progress_stats.library_insights(conn, abandoned_days=30, now=now)

    assert [g["game_id"] for g in ins["in_progress"]] == [active_id]
    assert ins["in_progress"][0]["remaining_hours"] is not None
    assert [g["game_id"] for g in ins["abandoned"]] == [old_id]
    assert ins["abandoned"][0]["days_idle"] >= 80
