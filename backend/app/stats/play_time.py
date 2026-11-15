import sqlite3
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from app.sessions.tracker import utc_now


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def intervals(conn: sqlite3.Connection) -> list[tuple[int, str | None, datetime, datetime]]:
    """(game_id, platform, start, end) for every session. The single definition
    of a session's time: end is ended_at, else the last heartbeat."""
    rows = conn.execute(
        """SELECT s.game_id, g.platform, s.started_at,
                  COALESCE(s.ended_at, s.last_heartbeat, s.started_at) AS end_at
           FROM sessions s JOIN games g ON g.id = s.game_id"""
    ).fetchall()
    out = []
    for r in rows:
        start, end = _parse(r["started_at"]), _parse(r["end_at"])
        out.append((r["game_id"], r["platform"], start, max(start, end)))
    return out


def seconds(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds())


def per_game(conn: sqlite3.Connection) -> dict[int, dict]:
    result: dict[int, dict] = defaultdict(lambda: {"seconds": 0, "sessions": 0, "last_played": None})
    for game_id, _, start, end in intervals(conn):
        r = result[game_id]
        r["seconds"] += seconds(start, end)
        r["sessions"] += 1
        iso_start = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        r["last_played"] = max(r["last_played"] or iso_start, iso_start)
    return dict(result)


def per_platform(conn: sqlite3.Connection) -> dict[str | None, int]:
    totals: dict[str | None, int] = defaultdict(int)
    for _, platform, start, end in intervals(conn):
        totals[platform] += seconds(start, end)
    return dict(totals)


def per_day(conn: sqlite3.Connection) -> dict[date, int]:
    """Seconds per local day. A session across midnight is split in two."""
    days: dict[date, int] = defaultdict(int)
    for _, _, start, end in intervals(conn):
        cur, end_local = start.astimezone(), end.astimezone()
        while cur < end_local:
            # Next midnight from the local date, never "+24 h" (DST days are 23 or 25 h).
            midnight = datetime.combine(cur.date() + timedelta(days=1), time.min).astimezone()
            nxt = min(midnight, end_local)
            days[cur.date()] += seconds(cur, nxt)
            cur = nxt
    return dict(days)


def _key(day: date, by: str) -> str:
    if by == "week":
        return (day - timedelta(days=day.weekday())).isoformat()  # Monday
    if by == "month":
        return day.strftime("%Y-%m")
    return day.isoformat()


def _recent_keys(today: date, by: str, n: int) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    cur = today
    while len(keys) < n:
        key = _key(cur, by)
        if key not in seen:
            seen.add(key)
            keys.append(key)
        if by == "month":
            cur = cur.replace(day=1) - timedelta(days=1)
        else:
            cur -= timedelta(days=7 if by == "week" else 1)
    return keys[::-1]


def per_period(conn: sqlite3.Connection, by: str, n: int, today: date | None = None) -> list[dict]:
    """Last `n` periods (day, week from Monday, or month), empty ones included."""
    today = today or utc_now().astimezone().date()
    totals: dict[str, int] = defaultdict(int)
    for day, secs in per_day(conn).items():
        totals[_key(day, by)] += secs
    return [{"period": k, "seconds": totals.get(k, 0)} for k in _recent_keys(today, by, n)]
