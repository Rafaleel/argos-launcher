"""Calibration and evaluation of weaker progress signals against live RAM ground truth."""

from dataclasses import dataclass, replace
from datetime import datetime
import math
import sqlite3

from app.editions import edition_ids
from app.progress.engine import (
    _edition_milestones,
    _edition_ra_id,
    _load_sessions,
    _load_signals,
    _parse_ts,
    get_ttb,
    split_sessions,
)
from app.progress.hmm import DiscreteProgressFilter, FilterParams


@dataclass(frozen=True)
class CalibrationTrace:
    """One scenario's chronological history with RAM observations as ground truth."""
    game_id: int
    scenario: str
    kinds: list[str]
    ttb_hours: float | None
    sessions: list[tuple[datetime, datetime]]  # (start_dt, end_dt)
    achievements: list[tuple[str, int, bool]]  # (ts, furthest_idx, win_reached)
    ram_points: list[tuple[str, float]]  # (ts, true_pct)


def _eval_subset(traces: list[CalibrationTrace], params: FilterParams, use_playtime: bool, use_ach: bool) -> dict:
    errors: list[float] = []
    covered = 0
    for tr in traces:
        if not tr.ram_points:
            continue
        filt = DiscreteProgressFilter.for_milestones(tr.kinds, params=params)
        split_times = [_parse_ts(ts) for ts, _ in tr.ram_points]
        if use_ach:
            split_times.extend(_parse_ts(ts) for ts, _, _ in tr.achievements)

        events: list[tuple[datetime, int, str, object]] = []
        if use_playtime:
            for end_dt, hours in split_sessions(tr.sessions, split_times):
                events.append((end_dt, 0, "session", hours))
        if use_ach:
            for ts, idx, win in tr.achievements:
                events.append((_parse_ts(ts), 1, "ach", (idx, win)))
        for ts, true_pct in tr.ram_points:
            events.append((_parse_ts(ts), 2, "ram", true_pct))
        events.sort(key=lambda e: (e[0], e[1]))

        max_ach = 0
        ach_win_done = False
        for _, _, kind, data in events:
            if kind == "session":
                filt.predict(float(data), tr.ttb_hours)
            elif kind == "ach":
                idx, win = data
                if idx > max_ach or (win and not ach_win_done):
                    filt.update_achievements(idx, win_reached=win)
                    max_ach = max(max_ach, idx)
                    ach_win_done = ach_win_done or win
            elif kind == "ram":
                true_pct = float(data)
                est = filt.estimate()
                errors.append(est.mean - true_pct)
                if est.lower <= true_pct <= est.upper:
                    covered += 1

    n = len(errors)
    if n == 0:
        return {"samples": 0, "mae": None, "rmse": None, "ci_coverage_90": None}
    mae = sum(abs(e) for e in errors) / n
    rmse = math.sqrt(sum(e * e for e in errors) / n)
    return {
        "samples": n,
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "ci_coverage_90": round(covered / n, 3),
    }


def collect_traces(conn: sqlite3.Connection) -> list[CalibrationTrace]:
    """Build calibration traces from all games in SQLite that have RAM milestone signals."""
    rows = conn.execute(
        "SELECT DISTINCT game_id FROM signals WHERE type = 'milestones' ORDER BY game_id"
    ).fetchall()
    done: set[int] = set()
    traces: list[CalibrationTrace] = []
    for r in rows:
        gid = r["game_id"]
        if gid in done:
            continue
        ids = edition_ids(conn, gid)
        done.update(ids)
        ra_id = _edition_ra_id(conn, gid, ids)
        if ra_id is None:
            continue
        ms_items, _ = _edition_milestones(conn, ids)
        if not ms_items:
            continue
        ttb = get_ttb(conn, gid)
        sessions = _load_sessions(conn, ids)
        signals = _load_signals(conn, ids, ra_id)

        by_scenario: dict[str, list[dict]] = {}
        for m in ms_items:
            by_scenario.setdefault(m["scenario"], []).append(m)

        for sc, group in by_scenario.items():
            kinds = [m.get("kind") or "progression" for m in group]
            name_to_idx = {m["name"]: i for i, m in enumerate(group, start=1)}
            ra_to_idx = {
                m["ra_achievement_id"]: (i, m.get("kind") == "win_condition")
                for i, m in enumerate(group, start=1)
                if m.get("ra_achievement_id") is not None
            }
            ach_events: list[tuple[str, int, bool]] = []
            ram_points: list[tuple[str, float]] = []
            n = len(group)
            for ts, _, sig_type, payload in signals:
                if sig_type == "achievements":
                    best, win = 0, False
                    for entry in payload.get("earned_list") or []:
                        if isinstance(entry, dict) and entry.get("id") in ra_to_idx:
                            idx, is_win = ra_to_idx[entry["id"]]
                            best = max(best, idx)
                            win = win or is_win
                    if best > 0 or win:
                        ach_events.append((ts, best, win))
                elif sig_type == "milestones" and payload.get("scenario") == sc:
                    best, win = 0, False
                    for name in payload.get("reached") or []:
                        idx = name_to_idx.get(name)
                        if idx is not None:
                            best = max(best, idx)
                            if kinds[idx - 1] == "win_condition":
                                win = True
                    true_pct = 100.0 if win else (100.0 * best / n)
                    ram_points.append((ts, true_pct))
            if ram_points:
                traces.append(
                    CalibrationTrace(
                        game_id=gid,
                        scenario=sc,
                        kinds=kinds,
                        ttb_hours=ttb,
                        sessions=sessions,
                        achievements=ach_events,
                        ram_points=ram_points,
                    )
                )
    return traces


def evaluate_traces(traces: list[CalibrationTrace], params: FilterParams | None = None) -> dict:
    """Evaluate weaker signal subsets against RAM ground truth on the given traces."""
    p = params or FilterParams()
    games = len({t.game_id for t in traces})
    note = None
    if games == 0:
        note = "Nenhum jogo com leituras de RAM registradas ainda para calibrar."
    elif games < 3:
        note = "Poucos jogos com leitura de RAM; os intervalos permanecem conservadores e não generalizam ainda."
    return {
        "games": games,
        "traces": len(traces),
        "subsets": {
            "playtime_only": _eval_subset(traces, p, use_playtime=True, use_ach=False),
            "achievements_only": _eval_subset(traces, p, use_playtime=False, use_ach=True),
            "achievements_and_playtime": _eval_subset(traces, p, use_playtime=True, use_ach=True),
        },
        "note": note,
    }


def evaluate_against_ram(conn: sqlite3.Connection, params: FilterParams | None = None) -> dict:
    """Evaluate local database signals against RAM ground truth."""
    return evaluate_traces(collect_traces(conn), params=params)


def calibrate_params(
    traces: list[CalibrationTrace],
    base_params: FilterParams | None = None,
    min_coverage: float = 0.85,
) -> tuple[FilterParams, dict]:
    """Grid-search playtime_dispersion and ach_false_pos to minimize MAE while keeping 90% CI coverage >= min_coverage."""
    base = base_params or FilterParams()
    if not traces:
        return base, evaluate_traces(traces, base)

    best_params = base
    best_metrics = _eval_subset(traces, base, use_playtime=True, use_ach=True)
    best_mae = best_metrics["mae"] if best_metrics["mae"] is not None else float("inf")
    best_valid = (best_metrics["ci_coverage_90"] or 0.0) >= min_coverage

    for disp in (0.35, 0.45, 0.55, 0.70, 0.90):
        for ach_fp in (0.0001, 0.0005, 0.002):
            cand = replace(base, playtime_dispersion=disp, ach_false_pos=ach_fp)
            m = _eval_subset(traces, cand, use_playtime=True, use_ach=True)
            if m["mae"] is None:
                continue
            valid = (m["ci_coverage_90"] or 0.0) >= min_coverage
            if (valid and not best_valid) or (valid == best_valid and m["mae"] < best_mae):
                best_params = cand
                best_mae = m["mae"]
                best_valid = valid

    return best_params, evaluate_traces(traces, best_params)
