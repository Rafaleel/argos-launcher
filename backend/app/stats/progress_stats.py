"""Derived progress statistics: progress pace, estimated hours remaining, and abandoned games."""

from datetime import datetime, timedelta
import sqlite3

from app.editions import edition_ids, edition_title
from app.progress import engine
from app.sessions.tracker import utc_now
from app.stats import play_time

MIN_PACE_SECONDS = 600  # at least 10 minutes played before estimating pace


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _edition_time(conn: sqlite3.Connection, ids: list[int], per_game: dict[int, dict]) -> tuple[int, int, str | None]:
    secs = sum(per_game.get(gid, {}).get("seconds", 0) for gid in ids)
    sess = sum(per_game.get(gid, {}).get("sessions", 0) for gid in ids)
    last_dates = [per_game[gid]["last_played"] for gid in ids if gid in per_game and per_game[gid].get("last_played")]
    return secs, sess, max(last_dates) if last_dates else None


def compute_pace_and_remaining(
    mean: float,
    lower: float,
    upper: float,
    seconds_played: int,
    ttb_hours: float | None,
) -> tuple[float | None, dict | None]:
    """Compute (pace_pct_per_hour, remaining_hours_dict) from progress estimate and playtime."""
    if mean >= 99.5:
        pace = round(mean / (seconds_played / 3600.0), 1) if seconds_played >= MIN_PACE_SECONDS else None
        return pace, {"mean": 0.0, "min": 0.0, "max": 0.0}

    hours_played = seconds_played / 3600.0
    pace: float | None = None
    if seconds_played >= MIN_PACE_SECONDS and mean > 0.0:
        pace = round(mean / hours_played, 1)

    # Blend observed pace with manual TTB when available so early noisy sessions stay grounded.
    effective_pace: float | None = None
    if pace is not None and pace > 0.0 and ttb_hours is not None and ttb_hours > 0.0:
        ttb_pace = 100.0 / ttb_hours
        weight = min(1.0, hours_played / max(2.0, ttb_hours * 0.25))
        effective_pace = weight * pace + (1.0 - weight) * ttb_pace
    elif pace is not None and pace > 0.0:
        effective_pace = pace
    elif ttb_hours is not None and ttb_hours > 0.0:
        effective_pace = 100.0 / ttb_hours

    if effective_pace is None or effective_pace <= 0.0:
        return pace, None

    rem_mean = max(0.0, (100.0 - mean) / effective_pace)
    rem_min = max(0.0, (100.0 - upper) / effective_pace)
    rem_max = max(0.0, (100.0 - lower) / effective_pace)
    return pace, {
        "mean": round(rem_mean, 1),
        "min": round(rem_min, 1),
        "max": round(rem_max, 1),
    }


def game_insights(
    conn: sqlite3.Connection,
    game_id: int,
    est: dict | None = None,
    ttb_hours: float | None = None,
) -> dict:
    """Pace and estimated remaining hours for one game (aggregated across edition discs)."""
    ids = edition_ids(conn, game_id)
    est = est if est is not None else engine.latest_estimate(conn, game_id)
    ttb = ttb_hours if ttb_hours is not None else engine.get_ttb(conn, game_id)
    per_game = play_time.per_game(conn)
    secs, _, _ = _edition_time(conn, ids, per_game)
    if est is None:
        return {"pace_pct_per_hour": None, "remaining_hours": None}
    pace, remaining = compute_pace_and_remaining(est["mean"], est["lower"], est["upper"], secs, ttb)
    return {"pace_pct_per_hour": pace, "remaining_hours": remaining}


def library_insights(
    conn: sqlite3.Connection,
    abandoned_days: int = 30,
    now: datetime | None = None,
) -> dict:
    """Library-wide progress insights: active in-progress games and abandoned games."""
    now = now or utc_now()
    cutoff = now - timedelta(days=abandoned_days)
    per_game = play_time.per_game(conn)
    estimates = engine.latest_estimates_map(conn)

    rows = conn.execute(
        "SELECT id, title, platform FROM games ORDER BY title"
    ).fetchall()

    done: set[int] = set()
    in_progress: list[dict] = []
    abandoned: list[dict] = []

    for r in rows:
        gid = r["id"]
        if gid in done:
            continue
        ids = edition_ids(conn, gid)
        done.update(ids)

        secs, sess, last_played = _edition_time(conn, ids, per_game)
        est = next((estimates[d] for d in ids if d in estimates), None)
        ttb = engine.get_ttb(conn, gid)
        if sess == 0 and est is None:
            continue

        title = edition_title(r["title"]) if len(ids) > 1 else r["title"]
        is_complete = est is not None and est["mean"] >= 95.0
        is_stale = last_played is not None and _parse_ts(last_played) < cutoff

        pace, remaining = (
            compute_pace_and_remaining(est["mean"], est["lower"], est["upper"], secs, ttb)
            if est is not None
            else (None, None)
        )

        entry = {
            "game_id": gid,
            "title": title,
            "platform": r["platform"],
            "seconds": secs,
            "sessions": sess,
            "last_played": last_played,
            "progress": est,
            "pace_pct_per_hour": pace,
            "remaining_hours": remaining,
        }

        if sess > 0 and not is_complete and is_stale:
            days_idle = max(0, (now - _parse_ts(last_played)).days)
            abandoned.append({**entry, "days_idle": days_idle})
        elif est is not None and est["mean"] < 99.5 and (sess > 0 or est["mean"] > 0.0):
            in_progress.append(entry)

    in_progress.sort(key=lambda x: (x["last_played"] or "", x["progress"]["mean"]), reverse=True)
    abandoned.sort(key=lambda x: x["days_idle"], reverse=True)
    return {
        "abandoned_days": abandoned_days,
        "in_progress": in_progress,
        "abandoned": abandoned,
    }
