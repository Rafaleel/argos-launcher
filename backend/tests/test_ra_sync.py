from app.collectors import ra_sync
from app.collectors.retroachievements import RAError, RetroAchievementsCollector
from app.db import connect

REAL_AUTO_SYNC = ra_sync.auto_sync  # the autouse fixture stubs it in every test


def test_auto_sync_is_quiet_when_busy_or_failing(monkeypatch):
    conn = connect()
    calls = []

    def collect(self, conn, game_id):
        calls.append(game_id)
        return {"ra_id": 1}

    monkeypatch.setattr(RetroAchievementsCollector, "collect", collect)
    assert REAL_AUTO_SYNC(conn, 1) is True and calls == [1]
    assert ra_sync.LOCK.acquire(blocking=False)
    try:
        assert REAL_AUTO_SYNC(conn, 1) is False and calls == [1]  # another sync runs: skipped, not queued
    finally:
        ra_sync.LOCK.release()

    def offline(self, conn, game_id):
        raise RAError("offline")

    monkeypatch.setattr(RetroAchievementsCollector, "collect", offline)
    assert REAL_AUTO_SYNC(conn, 1) is False
    assert ra_sync.LOCK.acquire(blocking=False)  # the lock was released after the failure
    ra_sync.LOCK.release()


def test_nothing_to_sync_without_credentials_or_link():
    conn = connect()
    assert REAL_AUTO_SYNC(conn, 1) is False  # collect returns None: no credentials
