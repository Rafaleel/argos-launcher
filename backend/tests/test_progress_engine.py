"""End-to-end tests for the progress fusion engine with SQLite sessions, signals, multi-scenario and multi-disc."""

import json
from pathlib import Path

from app import milestones
from app.collectors import ra_store
from app.collectors.base import store_signal
from app.progress import engine

FIXTURES = Path(__file__).parent / "fixtures"


def _add_game(conn, key: str, title: str, platform: str = "Nintendo - GameCube") -> int:
    cur = conn.execute(
        "INSERT INTO games (key, title, platform, identified) VALUES (?, ?, ?, 1)",
        (key, title, platform),
    )
    conn.commit()
    return cur.lastrowid


def _add_session(conn, game_id: int, started_at: str, ended_at: str) -> None:
    conn.execute(
        "INSERT INTO sessions (game_id, started_at, ended_at, last_heartbeat) VALUES (?, ?, ?, ?)",
        (game_id, started_at, ended_at, ended_at),
    )
    conn.commit()


def test_generic_grid_uses_playtime_and_manual_ttb(conn):
    gid = _add_game(conn, "g1", "Metroid Prime")
    _add_session(conn, gid, "2026-11-01T10:00:00Z", "2026-11-01T14:00:00Z")

    # Without milestones or TTB, no estimate is invented
    assert engine.recompute(conn, gid) is None

    engine.set_ttb(conn, gid, 10.0)
    est = engine.recompute(conn, gid)
    assert est is not None
    assert est["mode"] == "generic"
    assert est["sources"] == ["playtime"]
    assert 25.0 <= est["mean"] <= 55.0
    assert est["margin"] >= 10.0

    # Stored in progress_estimates
    loaded = engine.latest_estimate(conn, gid)
    assert loaded is not None
    assert loaded["mean"] == est["mean"]


def test_multi_scenario_and_multi_disc_fusion_with_re2_fixture(conn):
    d1 = _add_game(conn, "re2-1", "Resident Evil 2 (USA) (Disc 1)")
    d2 = _add_game(conn, "re2-2", "Resident Evil 2 (USA) (Disc 2)")
    ra_store.set_ra_id(conn, d1, 3176)
    ra_store.set_ra_id(conn, d2, 3176)

    patch = json.loads((FIXTURES / "re2_patch.json").read_text())
    kinds = {a["ID"]: a.get("Type") or "" for a in patch["Achievements"]}
    items, undet = milestones.build(patch, kinds)
    milestones.save(conn, d1, items, undet)

    # Play on disc 1, earn a Leon A milestone in RAM
    _add_session(conn, d1, "2026-11-02T18:00:00Z", "2026-11-02T20:00:00Z")
    leon_a = [m for m in items if m["scenario"] == "Leon A"]
    assert len(leon_a) >= 5
    # Reached milestone 5 (skipping 3) -> furthest milestone rule
    reached = [leon_a[0]["name"], leon_a[4]["name"]]
    store_signal(conn, d1, "milestones", {"ra_id": 3176, "scenario": "Leon A", "reached": reached, "total": len(leon_a)})

    est = engine.recompute(conn, d1)
    assert est is not None
    assert est["scenario"] == "Leon A"
    assert "ram" in est["sources"]
    assert "playtime" in est["sources"]
    expected = round(100.0 * 5 / len(leon_a), 1)
    assert abs(est["mean"] - expected) <= 5.0
    assert len(est["scenarios"]) >= 2

    # Disc 2 of the same edition receives the same stored estimate
    est_d2 = engine.latest_estimate(conn, d2)
    assert est_d2 is not None
    assert est_d2["mean"] == est["mean"]
    assert est_d2["scenario"] == "Leon A"


def test_win_condition_achievement_locks_scenario_to_100(conn):
    gid = _add_game(conn, "g-win", "Simple Story")
    ra_store.set_ra_id(conn, gid, 99)
    items = [
        {"ra_achievement_id": 1, "name": "Ch 1", "scenario": "", "kind": "progression", "address": 1, "size": "H", "value": 1, "gates": []},
        {"ra_achievement_id": 2, "name": "Ch 2", "scenario": "", "kind": "progression", "address": 2, "size": "H", "value": 1, "gates": []},
        {"ra_achievement_id": 3, "name": "Ending", "scenario": "", "kind": "win_condition", "address": 3, "size": "H", "value": 1, "gates": []},
    ]
    milestones.save(conn, gid, items, {"": 0})
    _add_session(conn, gid, "2026-11-03T10:00:00Z", "2026-11-03T12:00:00Z")
    store_signal(conn, gid, "achievements", {"ra_id": 99, "earned_list": [{"id": 3, "points": 25, "at": "2026-11-03T12:00:00Z", "hardcore": False}]})

    est = engine.recompute(conn, gid)
    assert est is not None
    assert est["mean"] >= 95.0
    assert est["upper"] == 100.0
    assert "achievements" in est["sources"]


def test_recompute_all_updates_every_eligible_game(conn):
    g1 = _add_game(conn, "a", "Game A")
    g2 = _add_game(conn, "b", "Game B")
    _add_session(conn, g1, "2026-11-01T10:00:00Z", "2026-11-01T12:00:00Z")
    engine.set_ttb(conn, g1, 8.0)
    # g2 has neither milestones nor TTB
    assert engine.recompute_all(conn) == 1
    assert engine.latest_estimate(conn, g1) is not None
    assert engine.latest_estimate(conn, g2) is None


def test_mid_session_ram_reading_does_not_double_count_prior_playtime(conn):
    gid = _add_game(conn, "mid", "Mid Session")
    ra_store.set_ra_id(conn, gid, 55)
    items = [
        {"ra_achievement_id": i, "name": f"M{i}", "scenario": "", "kind": "win_condition" if i == 10 else "progression",
         "address": i, "size": "H", "value": 1, "gates": []}
        for i in range(1, 11)
    ]
    milestones.save(conn, gid, items, {"": 0})
    engine.set_ttb(conn, gid, 4.0)
    # 2h session (10:00..12:00), RAM M6 (60%) recorded at 11:50 -> only 10 min after M6
    _add_session(conn, gid, "2026-11-01T10:00:00Z", "2026-11-01T12:00:00Z")
    conn.execute(
        "INSERT INTO signals (game_id, type, payload, timestamp) VALUES (?, 'milestones', ?, ?)",
        (gid, json.dumps({"ra_id": 55, "scenario": "", "reached": ["M6"], "total": 10}), "2026-11-01T11:50:00Z"),
    )
    conn.commit()
    est = engine.recompute(conn, gid)
    assert est is not None
    assert 58.0 <= est["mean"] <= 70.0
    assert est["margin"] <= 6.0


def test_repeated_achievement_syncs_do_not_inflate_uncertainty(conn):
    gid = _add_game(conn, "rep", "Repeated Sync")
    ra_store.set_ra_id(conn, gid, 77)
    items = [
        {"ra_achievement_id": i, "name": f"M{i}", "scenario": "", "kind": "progression",
         "address": i, "size": "H", "value": 1, "gates": []}
        for i in range(1, 15)
    ]
    milestones.save(conn, gid, items, {"": 0})
    _add_session(conn, gid, "2026-11-01T10:00:00Z", "2026-11-01T10:30:00Z")
    for k in range(10):
        conn.execute(
            "INSERT INTO signals (game_id, type, payload, timestamp) VALUES (?, 'achievements', ?, ?)",
            (gid, json.dumps({"ra_id": 77, "earned_list": [{"id": 1, "points": 5, "at": "2026-11-01T10:20:00Z"}]}),
             f"2026-11-01T10:{31 + k:02d}:00Z"),
        )
    conn.commit()
    est = engine.recompute(conn, gid)
    assert est is not None
    assert est["mean"] <= 15.0
    assert est["margin"] <= 10.0


def test_migration_commits_milestone_kind_on_reopen(tmp_path):
    import sqlite3
    from app.db import connect

    db_file = tmp_path / "legacy.db"
    raw = sqlite3.connect(db_file)
    raw.executescript(
        """
        CREATE TABLE games (id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, title TEXT NOT NULL, platform TEXT, identified INTEGER NOT NULL, cover TEXT);
        CREATE TABLE ra_games (game_id INTEGER PRIMARY KEY, ra_id INTEGER NOT NULL);
        CREATE TABLE ra_achievements (ra_id INTEGER NOT NULL, achievement_id INTEGER NOT NULL, position INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL, points INTEGER NOT NULL, kind TEXT NOT NULL, PRIMARY KEY (ra_id, achievement_id));
        CREATE TABLE milestones (id INTEGER PRIMARY KEY, game_id INTEGER NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL, ra_achievement_id INTEGER, address INTEGER, size TEXT, value INTEGER, gates TEXT, scenario TEXT);
        INSERT INTO games VALUES (1, 'g1', 'Legacy', 'Nintendo - GameCube', 1, NULL);
        INSERT INTO ra_games VALUES (1, 10);
        INSERT INTO ra_achievements VALUES (10, 100, 0, 'End', 'Beat game', 25, 'win_condition');
        INSERT INTO milestones VALUES (1, 1, 0, 'End', 100, 1, 'H', 1, '[]', '');
        """
    )
    raw.commit()
    raw.close()

    c1 = connect(db_file)
    assert not c1.in_transaction
    c1.close()

    c2 = connect(db_file)
    row = c2.execute("SELECT kind FROM milestones WHERE id = 1").fetchone()
    c2.close()
    assert row["kind"] == "win_condition"


def test_sync_ra_ttb_fetches_automatically_and_respects_manual_override(conn, monkeypatch):
    from app.collectors import retroachievements

    gid = _add_game(conn, "re2-ttb", "RE2")
    ra_store.set_credentials(conn, "u", "secretkey123")
    ra_store.set_ra_id(conn, gid, 3176)

    assert retroachievements.parse_game_ttb({"medianTimeToBeat": 18000, "medianTimeToBeatHardcore": 19800,
                                             "timesUsedInBeatMedian": 50, "timesUsedInHardcoreBeatMedian": 120}) == 5.5
    monkeypatch.setattr(retroachievements, "fetch_game_ttb", lambda u, k, r: 5.5)

    assert engine.sync_ra_ttb(conn, gid) == 5.5
    assert engine.get_ttb_info(conn, gid) == (5.5, "ra")

    # Manual override is never overwritten by automatic RA sync
    engine.set_ttb(conn, gid, 8.0, source="manual")
    monkeypatch.setattr(retroachievements, "fetch_game_ttb", lambda u, k, r: 4.0)
    assert engine.sync_ra_ttb(conn, gid) == 8.0
    assert engine.get_ttb_info(conn, gid) == (8.0, "manual")
