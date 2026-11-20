"""Multi-disc editions: one playlist for Dolphin, one RetroAchievements link and sync for all discs."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api_ra
from app.collectors import retroachievements as ra
from app.config import db_path
from app.db import connect
from app.editions import edition_ids
from app.main import app
from tests.test_dolphin_api import GC, native_dolphin
from tests.test_launcher import wait_for
from tests.test_ra_detect import library

CVX = "Resident Evil - Code - Veronica X (USA)"


@pytest.fixture
def client():
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(api_ra, "PAUSE", 0)


def lib(client, tmp_path, extra=None):
    """Two discs of one edition, a single-disc game and a disc of another region."""
    files = {
        f"{CVX} (Disc 1).iso": (GC, b"GCDE08" + b"\x01" * 200),
        f"{CVX} (Disc 2).iso": (GC, b"GCDE08" + b"\x02" * 200),
        "Resident Evil 2 (USA).iso": (GC, b"GHAE08" + b"\x03" * 200),
        "Resident Evil - Code - Veronica X (Europe) (Disc 1).iso": (GC, b"GCDP08" + b"\x04" * 200),
        **(extra or {}),
    }
    # library() names each game "Game <file name>": strip that to get DAT-like titles
    ids = library(client, tmp_path, files)
    conn = connect()
    for name, gid in ids.items():
        conn.execute("UPDATE games SET title = ? WHERE id = ?", (name.removesuffix(".iso"), gid))
    conn.commit()
    return conn, {name.removesuffix(".iso"): gid for name, gid in ids.items()}


def test_edition_groups_only_discs_of_the_same_title_and_platform(client, tmp_path):
    conn, ids = lib(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    assert edition_ids(conn, d2) == [d1, d2] == edition_ids(conn, d1)
    assert edition_ids(conn, ids["Resident Evil 2 (USA)"]) == [ids["Resident Evil 2 (USA)"]]
    europe = ids["Resident Evil - Code - Veronica X (Europe) (Disc 1)"]
    assert edition_ids(conn, europe) == [europe]  # another region is another edition


def test_playing_a_disc_boots_a_playlist_with_that_disc_first(client, tmp_path):
    conn, ids = lib(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    assert client.post(f"/api/games/{d2}/play").status_code == 200
    argv = wait_for(out)["argv"]
    playlist = Path(argv[argv.index("-e") + 1])
    assert playlist.suffix == ".m3u" and playlist.parent == db_path().parent / "playlists"
    lines = playlist.read_text().splitlines()
    assert [Path(l).name for l in lines] == [f"{CVX} (Disc 2).iso", f"{CVX} (Disc 1).iso"]
    assert all(Path(l).is_absolute() for l in lines)
    assert "Dolphin.Core.AutoDiscChange=True" in argv


def test_another_disc_of_an_open_edition_is_refused(client, tmp_path):
    conn, ids = lib(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, '2026-11-20T10:00:00Z', '2026-11-20T10:00:00Z')", (d2,))
    conn.commit()
    r = client.post(f"/api/games/{d1}/play")
    assert r.status_code == 409 and "Outro disco" in r.json()["detail"] and not out.exists()


def test_a_single_disc_game_launches_its_image_directly(client, tmp_path):
    conn, ids = lib(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    assert client.post(f"/api/games/{ids['Resident Evil 2 (USA)']}/play").status_code == 200
    argv = wait_for(out)["argv"]
    assert argv[argv.index("-e") + 1].endswith("Resident Evil 2 (USA).iso")
    assert not any("AutoDiscChange" in a for a in argv)


def test_a_missing_disc_falls_back_to_the_chosen_one(client, tmp_path):
    conn, ids = lib(client, tmp_path)
    out = native_dolphin(client, tmp_path)
    (tmp_path / "roms" / f"{CVX} (Disc 2).iso").unlink()
    assert client.post(f"/api/games/{ids[f'{CVX} (Disc 1)']}/play").status_code == 200
    argv = wait_for(out)["argv"]
    assert argv[argv.index("-e") + 1].endswith(f"{CVX} (Disc 1).iso")  # no playlist with one disc


def test_linking_one_disc_links_the_whole_edition(client, tmp_path):
    conn, ids = lib(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    assert client.put(f"/api/games/{d2}/ra", json={"ra": "1234"}).json() == {"ra_id": 1234}
    assert client.get(f"/api/games/{d1}/ra").json()["ra_id"] == 1234
    assert client.get(f"/api/games/{ids['Resident Evil 2 (USA)']}/ra").json()["ra_id"] is None


def test_sync_asks_the_site_once_per_edition_and_fills_every_disc(client, tmp_path, monkeypatch):
    conn, ids = lib(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    calls = []

    def fetch(user, key, ra_id):
        calls.append(ra_id)
        return {"ra_id": ra_id, "title": "CVX", "console": "GameCube", "total": 80, "earned": 3, "earned_hardcore": 0,
                "points_total": 0, "points_earned": 0, "earned_list": []}

    monkeypatch.setattr(ra, "fetch_progress", fetch)
    client.put("/api/ra/settings", json={"user": "u", "key": "KEY123"})
    client.put(f"/api/games/{d1}/ra", json={"ra": "1234"})
    client.put(f"/api/games/{ids['Resident Evil 2 (USA)']}/ra", json={"ra": "3176"})
    results = client.post("/api/ra/sync").json()
    assert sorted(calls) == [1234, 3176] and len(results) == 2
    games = {g["id"]: g for g in client.get("/api/games").json()}
    assert games[d1]["achievements"]["earned"] == 3 and games[d2]["achievements"]["earned"] == 3
    calls.clear()
    assert client.post(f"/api/games/{d2}/ra/sync").json()["total"] == 80 and calls == [1234]


def test_bulk_detect_links_the_edition_from_one_disc(client, tmp_path, monkeypatch):
    conn, ids = lib(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    looked_up = []
    monkeypatch.setattr(api_ra, "HASHERS", {GC: lambda path: "a" * 32})
    monkeypatch.setattr(api_ra, "resolve_game_id", lambda md5: looked_up.append(md5) or 1234)
    results = client.post("/api/ra/detect").json()
    titles = [r["title"] for r in results]
    assert f"{CVX} (Disc 2)" not in titles and f"{CVX} (Disc 1)" in titles  # disc 2 came with disc 1
    assert client.get(f"/api/games/{d2}/ra").json()["ra_id"] == 1234
    assert len(looked_up) == len(results)


def test_a_missing_chosen_disc_never_boots_another_one(client, tmp_path):
    conn, ids = lib(client, tmp_path, {f"{CVX} (Disc 3).iso": (GC, b"GCDE08" + b"\x05" * 200)})
    out = native_dolphin(client, tmp_path)
    (tmp_path / "roms" / f"{CVX} (Disc 1).iso").unlink()
    r = client.post(f"/api/games/{ids[f'{CVX} (Disc 1)']}/play")
    assert r.status_code == 409 and not out.exists()  # files missing, not disc 2 booting as disc 1


def test_three_discs_rotate_from_the_chosen_one(client, tmp_path):
    conn, ids = lib(client, tmp_path, {f"{CVX} (Disc 3).iso": (GC, b"GCDE08" + b"\x05" * 200)})
    out = native_dolphin(client, tmp_path)
    assert client.post(f"/api/games/{ids[f'{CVX} (Disc 2)']}/play").status_code == 200
    argv = wait_for(out)["argv"]
    names = [Path(l).name for l in Path(argv[argv.index("-e") + 1]).read_text().splitlines()]
    assert names == [f"{CVX} (Disc 2).iso", f"{CVX} (Disc 3).iso", f"{CVX} (Disc 1).iso"]


def test_two_discs_clicked_at_once_open_only_one(client, tmp_path, monkeypatch):
    from app.sessions import tracker
    conn, ids = lib(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    conn.execute("INSERT INTO sessions (game_id, started_at, last_heartbeat) VALUES (?, '2026-11-20T10:00:00Z', '2026-11-20T10:00:00Z')", (d1,))
    conn.commit()  # disc 1 open
    with pytest.raises(tracker.AlreadyPlaying):
        tracker.start_session(conn, d2, lambda: 999998, (d1,))  # the check holds under the play lock


def test_sync_all_still_syncs_a_disc_linked_to_another_set(client, tmp_path, monkeypatch):
    conn, ids = lib(client, tmp_path)
    d1, d2 = ids[f"{CVX} (Disc 1)"], ids[f"{CVX} (Disc 2)"]
    calls = []
    monkeypatch.setattr(ra, "fetch_progress", lambda u, k, ra_id: calls.append(ra_id) or {
        "ra_id": ra_id, "title": "x", "console": "", "total": 1, "earned": 0, "earned_hardcore": 0,
        "points_total": 0, "points_earned": 0, "earned_list": []})
    client.put("/api/ra/settings", json={"user": "u", "key": "KEY123"})
    conn.execute("INSERT INTO ra_games (game_id, ra_id) VALUES (?, 100), (?, 200)", (d1, d2))
    conn.commit()
    client.post("/api/ra/sync")
    assert sorted(calls) == [100, 200]


def test_backend_grouping_matches_the_frontend_on_odd_titles(client, tmp_path):
    from app.editions import DISC, disc_number
    assert disc_number("Game (Disc ２)") == 0  # fullwidth digit: not a disc, like JS \d
    assert DISC.sub("", "Game (Disc 1) (Disc 2)", count=1).strip() == "Game (Disc 2)"
