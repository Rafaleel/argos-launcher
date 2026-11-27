"""Signal fusion engine: replays sessions and raw signals through the HMM and stores progress_estimates."""

from datetime import datetime
import json
import sqlite3

from app import milestones
from app.collectors import ra_store
from app.editions import edition_ids
from app.progress.hmm import DiscreteProgressFilter, FilterParams
from app.sessions.tracker import iso, utc_now

DEFAULT_PARAMS = FilterParams()


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def get_ttb_info(conn: sqlite3.Connection, game_id: int) -> tuple[float | None, str | None]:
    """(ttb_hours, source) for a game (shared across discs of an edition). source is 'ra' or 'manual'."""
    ids = edition_ids(conn, game_id)
    placeholders = ",".join("?" * len(ids))
    row = conn.execute(
        f"SELECT ttb_hours, source FROM game_progress_config WHERE game_id IN ({placeholders}) AND ttb_hours IS NOT NULL LIMIT 1",
        ids,
    ).fetchone()
    if row is None:
        return None, None
    return float(row["ttb_hours"]), (row["source"] or "manual")


def get_ttb(conn: sqlite3.Connection, game_id: int) -> float | None:
    """Time-to-beat in hours for a game (shared across discs of an edition)."""
    return get_ttb_info(conn, game_id)[0]


def set_ttb(conn: sqlite3.Connection, game_id: int, ttb_hours: float | None, source: str = "manual") -> float | None:
    """Save or clear time-to-beat (hours) across all discs of the edition."""
    ids = edition_ids(conn, game_id)
    with conn:
        if ttb_hours is None:
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM game_progress_config WHERE game_id IN ({placeholders})", ids)
        else:
            for disc in ids:
                conn.execute(
                    "INSERT INTO game_progress_config (game_id, ttb_hours, source) VALUES (?, ?, ?) "
                    "ON CONFLICT(game_id) DO UPDATE SET ttb_hours = excluded.ttb_hours, source = excluded.source",
                    (disc, float(ttb_hours), source),
                )
    return float(ttb_hours) if ttb_hours is not None else None


def sync_ra_ttb(conn: sqlite3.Connection, game_id: int) -> float | None:
    """Fetch community median time-to-beat from RetroAchievements unless the user set a manual override."""
    from app.collectors.retroachievements import RAError, fetch_game_ttb

    existing, source = get_ttb_info(conn, game_id)
    if existing is not None and source == "manual":
        return existing
    creds = ra_store.get_credentials(conn)
    ids = edition_ids(conn, game_id)
    ra_id = _edition_ra_id(conn, game_id, ids)
    if creds is None or ra_id is None:
        return existing
    try:
        hours = fetch_game_ttb(creds[0], creds[1], ra_id)
    except RAError:
        return existing
    if hours is not None:
        set_ttb(conn, game_id, hours, source="ra")
        return hours
    return existing


def _load_sessions(conn: sqlite3.Connection, ids: list[int]) -> list[tuple[datetime, datetime]]:
    """Return chronological (start_dt, end_dt) intervals for all sessions of the edition."""
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT started_at, COALESCE(ended_at, last_heartbeat, started_at) AS end_at
            FROM sessions WHERE game_id IN ({placeholders}) ORDER BY started_at, id""",
        ids,
    ).fetchall()
    out: list[tuple[datetime, datetime]] = []
    for r in rows:
        start, end = _parse_ts(r["started_at"]), _parse_ts(r["end_at"])
        if end > start:
            out.append((start, end))
    return out


def split_sessions(
    sessions: list[tuple[datetime, datetime]],
    split_times: list[datetime],
) -> list[tuple[datetime, float]]:
    """Split session intervals at mid-session observation timestamps so playtime before an observation
    is applied before the update, and playtime after is applied after."""
    cuts = sorted(set(split_times))
    out: list[tuple[datetime, float]] = []
    for start, end in sessions:
        cur = start
        for t in cuts:
            if cur < t < end:
                out.append((t, (t - cur).total_seconds() / 3600.0))
                cur = t
        if end > cur:
            out.append((end, (end - cur).total_seconds() / 3600.0))
    return out


def _load_signals(conn: sqlite3.Connection, ids: list[int], ra_id: int | None) -> list[tuple[str, int, str, dict]]:
    """Return chronological (timestamp, id, type, payload) for milestone and achievement signals."""
    if ra_id is None:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"""SELECT id, type, payload, timestamp FROM signals
            WHERE game_id IN ({placeholders}) AND type IN ('milestones', 'achievements')
            ORDER BY timestamp, id""",
        ids,
    ).fetchall()
    out: list[tuple[str, int, str, dict]] = []
    for r in rows:
        try:
            payload = json.loads(r["payload"])
        except ValueError:
            continue
        if isinstance(payload, dict) and payload.get("ra_id") == ra_id:
            out.append((r["timestamp"], r["id"], r["type"], payload))
    return out


def _edition_milestones(conn: sqlite3.Connection, ids: list[int]) -> tuple[list[dict], list[dict]]:
    """Load milestones and groups from whichever disc of the edition has them."""
    for disc in ids:
        items = milestones.load(conn, disc)
        if items:
            return items, milestones.groups(conn, disc)
    return [], []


def _edition_ra_id(conn: sqlite3.Connection, game_id: int, ids: list[int]) -> int | None:
    ra_id = ra_store.get_ra_id(conn, game_id)
    if ra_id is not None:
        return ra_id
    for disc in ids:
        found = ra_store.get_ra_id(conn, disc)
        if found is not None:
            return found
    return None


def _run_scenario(
    group: list[dict],
    scenario: str,
    sessions: list[tuple[datetime, datetime]],
    signals: list[tuple[str, int, str, dict]],
    ttb_hours: float | None,
    params: FilterParams,
) -> tuple[dict, str | None]:
    """Run the HMM for a single scenario. Returns (scenario_summary, last_ram_ts)."""
    kinds = [m.get("kind") or "progression" for m in group]
    filt = DiscreteProgressFilter.for_milestones(kinds, params=params)
    name_to_idx = {m["name"]: i for i, m in enumerate(group, start=1)}
    ra_to_idx = {
        m["ra_achievement_id"]: (i, m.get("kind") == "win_condition")
        for i, m in enumerate(group, start=1)
        if m.get("ra_achievement_id") is not None
    }

    relevant_signals: list[tuple[datetime, str, int, str, dict]] = []
    for ts, sig_id, sig_type, payload in signals:
        if sig_type == "achievements" or (sig_type == "milestones" and payload.get("scenario") == scenario):
            relevant_signals.append((_parse_ts(ts), ts, sig_id, sig_type, payload))

    # Split sessions at every mid-session signal timestamp so pre-signal playtime precedes the update.
    split_times = [dt for dt, _, _, _, _ in relevant_signals]
    session_slices = split_sessions(sessions, split_times)

    # Unified chronological event stream: (dt, order_rank, kind, ts_str, data)
    events: list[tuple[datetime, int, str, str, object]] = []
    for end_dt, hours in session_slices:
        events.append((end_dt, 0, "session", iso(end_dt), hours))
    for dt, ts, _, sig_type, payload in relevant_signals:
        rank = 1 if sig_type == "achievements" else 2
        events.append((dt, rank, sig_type, ts, payload))
    events.sort(key=lambda e: (e[0], e[1]))

    sources: set[str] = set()
    furthest_ram = 0
    furthest_ach = 0
    max_ach_applied = 0
    ach_win_applied = False
    win_reached = False
    last_ram_ts: str | None = None
    reset_happened = False

    for _, _, ev_kind, ts, data in events:
        if ev_kind == "session":
            filt.predict(float(data), ttb_hours)
            sources.add("playtime")
        elif ev_kind == "achievements":
            if reset_happened:
                continue  # after a live RAM reset (New Game+ / old save), old achievements don't override RAM
            earned_list = data.get("earned_list") if isinstance(data, dict) else None
            if not isinstance(earned_list, list):
                continue
            best_idx = 0
            ach_win = False
            for entry in earned_list:
                if not isinstance(entry, dict):
                    continue
                hit = ra_to_idx.get(entry.get("id"))
                if hit is not None:
                    idx, is_win = hit
                    best_idx = max(best_idx, idx)
                    if is_win:
                        ach_win = True
            # Only apply when achievements genuinely advance (deduplicates multi-disc & repeated sync snapshots).
            advances = best_idx > max_ach_applied or (ach_win and not ach_win_applied)
            if advances:
                if best_idx > furthest_ram or (ach_win and not win_reached):
                    filt.update_achievements(best_idx, win_reached=ach_win)
                max_ach_applied = max(max_ach_applied, best_idx)
                ach_win_applied = ach_win_applied or ach_win
                furthest_ach = max(furthest_ach, best_idx)
                win_reached = win_reached or ach_win
                sources.add("achievements")
        elif ev_kind == "milestones":
            reached_names = data.get("reached") if isinstance(data, dict) else None
            if not isinstance(reached_names, list):
                continue
            best_idx = 0
            ram_win = False
            for name in reached_names:
                idx = name_to_idx.get(name)
                if idx is not None:
                    best_idx = max(best_idx, idx)
                    if kinds[idx - 1] == "win_condition":
                        ram_win = True
            did_reset = filt.update_ram(best_idx, win_reached=ram_win)
            if did_reset:
                reset_happened = True
                win_reached = ram_win
            else:
                win_reached = win_reached or ram_win
            furthest_ram = best_idx
            last_ram_ts = ts
            sources.add("ram")

    est = filt.estimate()
    summary = {
        "scenario": scenario,
        "mean": est.mean,
        "lower": est.lower,
        "upper": est.upper,
        "margin": est.margin,
        "furthest": max(furthest_ram, 0 if reset_happened else furthest_ach),
        "total": len(group),
        "win_reached": win_reached,
        "resets": filt.resets,
        "sources": sorted(sources),
    }
    return summary, last_ram_ts


def _run_generic(
    sessions: list[tuple[datetime, datetime]],
    ttb_hours: float,
    params: FilterParams,
) -> dict:
    """Run the HMM on a generic 0%..100% grid using playtime and manual TTB."""
    filt = DiscreteProgressFilter.generic(params=params)
    for start, end in sessions:
        filt.predict((end - start).total_seconds() / 3600.0, ttb_hours)
    est = filt.estimate()
    return {
        "scenario": "",
        "mean": est.mean,
        "lower": est.lower,
        "upper": est.upper,
        "margin": est.margin,
        "furthest": None,
        "total": None,
        "win_reached": False,
        "resets": 0,
        "sources": ["playtime"],
    }


def clear_estimates(conn: sqlite3.Connection, ids: list[int]) -> None:
    """Remove stored progress_estimates for the given game ids."""
    if not ids:
        return
    with conn:
        conn.execute(f"DELETE FROM progress_estimates WHERE game_id IN ({','.join('?' * len(ids))})", ids)


def _persist(conn: sqlite3.Connection, ids: list[int], record: dict, force: bool) -> None:
    """Store a progress_estimates row for every disc of the edition when changed (or forced)."""
    now = iso(utc_now())
    sources_json = json.dumps(record["sources"])
    details_json = json.dumps(record["details"])
    with conn:
        for disc in ids:
            if not force:
                prev = conn.execute(
                    "SELECT mean, lower, upper, scenario, sources, details FROM progress_estimates "
                    "WHERE game_id = ? ORDER BY id DESC LIMIT 1",
                    (disc,),
                ).fetchone()
                if (
                    prev is not None
                    and prev["mean"] == record["mean"]
                    and prev["lower"] == record["lower"]
                    and prev["upper"] == record["upper"]
                    and (prev["scenario"] or "") == (record["scenario"] or "")
                    and (prev["sources"] or "[]") == sources_json
                    and (prev["details"] or "{}") == details_json
                ):
                    continue
            conn.execute(
                "INSERT INTO progress_estimates (game_id, timestamp, mean, lower, upper, scenario, sources, details) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (disc, now, record["mean"], record["lower"], record["upper"], record["scenario"], sources_json, details_json),
            )


def recompute(
    conn: sqlite3.Connection,
    game_id: int,
    params: FilterParams | None = None,
    persist: bool = True,
    force: bool = False,
) -> dict | None:
    """Recompute the progress estimate for a game from its raw sessions and signals."""
    p = params or DEFAULT_PARAMS
    ids = edition_ids(conn, game_id)
    ra_id = _edition_ra_id(conn, game_id, ids)
    ttb_hours = get_ttb(conn, game_id)
    sessions = _load_sessions(conn, ids)
    signals = _load_signals(conn, ids, ra_id)
    ms_items, ms_groups = _edition_milestones(conn, ids)

    if ms_items and (sessions or signals):
        scenario_order = [g["scenario"] for g in ms_groups] or list(dict.fromkeys(m["scenario"] for m in ms_items))
        scenarios: list[dict] = []
        last_ram_by_scenario: dict[str, str] = {}
        for sc in scenario_order:
            group = [m for m in ms_items if m["scenario"] == sc]
            if not group:
                continue
            sc_summary, last_ram_ts = _run_scenario(group, sc, sessions, signals, ttb_hours, p)
            scenarios.append(sc_summary)
            if last_ram_ts is not None:
                last_ram_by_scenario[sc] = last_ram_ts
        if not scenarios:
            if persist:
                clear_estimates(conn, ids)
            return None
        # Active scenario: latest RAM reading > highest estimated progress > first scenario
        if last_ram_by_scenario:
            active_sc = max(last_ram_by_scenario.items(), key=lambda kv: kv[1])[0]
            chosen = next(s for s in scenarios if s["scenario"] == active_sc)
        else:
            chosen = max(scenarios, key=lambda s: s["mean"])
            if chosen["mean"] == 0.0:
                chosen = scenarios[0]
        record = {
            "mean": chosen["mean"],
            "lower": chosen["lower"],
            "upper": chosen["upper"],
            "margin": chosen["margin"],
            "scenario": chosen["scenario"],
            "sources": chosen["sources"],
            "details": {"mode": "milestones", "scenarios": scenarios},
        }
    elif ttb_hours is not None and sessions:
        chosen = _run_generic(sessions, ttb_hours, p)
        record = {
            "mean": chosen["mean"],
            "lower": chosen["lower"],
            "upper": chosen["upper"],
            "margin": chosen["margin"],
            "scenario": "",
            "sources": chosen["sources"],
            "details": {"mode": "generic", "scenarios": []},
        }
    else:
        if persist:
            clear_estimates(conn, ids)
        return None

    if persist:
        _persist(conn, ids, record, force=force)
    return {
        **record,
        "ttb_hours": ttb_hours,
        "scenarios": record["details"]["scenarios"],
        "mode": record["details"]["mode"],
        "updated_at": iso(utc_now()),
    }


def recompute_all(conn: sqlite3.Connection, params: FilterParams | None = None) -> int:
    """Recompute progress estimates for every game in the library. Returns number of editions updated."""
    rows = conn.execute("SELECT id FROM games ORDER BY id").fetchall()
    done: set[int] = set()
    updated = 0
    for r in rows:
        gid = r["id"]
        if gid in done:
            continue
        ids = edition_ids(conn, gid)
        done.update(ids)
        if recompute(conn, gid, params=params, persist=True, force=True) is not None:
            updated += 1
    return updated


def _row_to_estimate(row: sqlite3.Row) -> dict:
    try:
        sources = json.loads(row["sources"]) if row["sources"] else []
    except ValueError:
        sources = []
    try:
        details = json.loads(row["details"]) if row["details"] else {}
    except ValueError:
        details = {}
    mean = float(row["mean"])
    lower = float(row["lower"])
    upper = float(row["upper"])
    return {
        "mean": round(mean, 1),
        "lower": round(lower, 1),
        "upper": round(upper, 1),
        "margin": round(max(0.0, (upper - lower) / 2.0), 1),
        "scenario": row["scenario"] or "",
        "sources": sources if isinstance(sources, list) else [],
        "scenarios": details.get("scenarios", []) if isinstance(details, dict) else [],
        "mode": details.get("mode", "milestones") if isinstance(details, dict) else "milestones",
        "updated_at": row["timestamp"],
    }


def latest_estimate(conn: sqlite3.Connection, game_id: int) -> dict | None:
    """Latest stored progress estimate for a game, or None."""
    row = conn.execute(
        "SELECT mean, lower, upper, scenario, sources, details, timestamp "
        "FROM progress_estimates WHERE game_id = ? ORDER BY id DESC LIMIT 1",
        (game_id,),
    ).fetchone()
    return _row_to_estimate(row) if row is not None else None


def latest_estimates_map(conn: sqlite3.Connection) -> dict[int, dict]:
    """Compact latest estimate per game_id for the library list endpoint."""
    rows = conn.execute(
        """SELECT p.game_id, p.mean, p.lower, p.upper, p.scenario
           FROM progress_estimates p
           JOIN (SELECT game_id, MAX(id) AS mid FROM progress_estimates GROUP BY game_id) m
             ON p.id = m.mid"""
    ).fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        mean, lower, upper = float(r["mean"]), float(r["lower"]), float(r["upper"])
        out[r["game_id"]] = {
            "mean": round(mean, 1),
            "lower": round(lower, 1),
            "upper": round(upper, 1),
            "margin": round(max(0.0, (upper - lower) / 2.0), 1),
            "scenario": r["scenario"] or "",
        }
    return out
