"""API tests for progress estimation, TTB configuration, calibration, and insights endpoints."""

from fastapi.testclient import TestClient

from app.main import app


def _seed_game(conn, title: str = "Wind Waker") -> int:
    cur = conn.execute(
        "INSERT INTO games (key, title, platform, identified) VALUES (?, ?, 'Nintendo - GameCube', 1)",
        (title.lower(), title),
    )
    gid = cur.lastrowid
    conn.execute(
        "INSERT INTO files (game_id, path, size, mtime_ns, crc32, sha1) VALUES (?, ?, 100, 1, '00000000', '00000000')",
        (gid, f"/roms/{title}.iso"),
    )
    conn.execute(
        "INSERT INTO sessions (game_id, started_at, ended_at, last_heartbeat) "
        "VALUES (?, '2026-11-26T10:00:00Z', '2026-11-26T14:00:00Z', '2026-11-26T14:00:00Z')",
        (gid,),
    )
    conn.commit()
    return gid


def test_progress_endpoints_and_ttb_config(conn):
    gid = _seed_game(conn)
    client = TestClient(app, base_url="http://127.0.0.1")

    # Initially unavailable (no milestones, no TTB)
    r = client.get(f"/api/games/{gid}/progress")
    assert r.status_code == 200
    assert r.json()["available"] is False

    # Reject invalid TTB
    assert client.put(f"/api/games/{gid}/progress/config", json={"ttb_hours": 0.1}).status_code == 422

    # Save TTB -> computes generic HMM estimate and surfaces it in GET /api/games
    r = client.put(f"/api/games/{gid}/progress/config", json={"ttb_hours": 10.0})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["ttb_hours"] == 10.0
    assert 25.0 <= body["mean"] <= 55.0
    assert body["remaining_hours"] is not None

    games = client.get("/api/games").json()
    assert games[0]["progress"] is not None
    assert games[0]["progress"]["mean"] == body["mean"]

    # Recompute single and all
    assert client.post(f"/api/games/{gid}/progress/recompute").status_code == 200
    assert client.post("/api/progress/recompute").json()["updated"] == 1

    # Insights and calibration
    insights = client.get("/api/stats/insights").json()
    assert len(insights["in_progress"]) == 1
    cal = client.get("/api/progress/calibration").json()
    assert cal["games"] == 0

    # Clear TTB -> clears generic estimate
    r = client.put(f"/api/games/{gid}/progress/config", json={"ttb_hours": None})
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_progress_404_for_missing_game():
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/games/9999/progress").status_code == 404
    assert client.put("/api/games/9999/progress/config", json={"ttb_hours": 10.0}).status_code == 404
