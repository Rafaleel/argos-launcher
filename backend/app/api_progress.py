"""Progress estimation, Time-to-Beat config, calibration, and derived insights routes."""

import sqlite3

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.api import Conn
from app.progress import calibration, engine
from app.stats import progress_stats

router = APIRouter(prefix="/api")


class ProgressConfigIn(BaseModel):
    ttb_hours: float | None = Field(None, ge=0.5, le=1000.0)


def _game(conn: sqlite3.Connection, game_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, title FROM games WHERE id = ?", (game_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Jogo não encontrado")
    return row


def _progress_response(conn: sqlite3.Connection, game_id: int, est: dict | None) -> dict:
    ttb = engine.get_ttb(conn, game_id)
    insights = progress_stats.game_insights(conn, game_id, est=est, ttb_hours=ttb)
    if est is None:
        return {
            "available": False,
            "ttb_hours": ttb,
            "pace_pct_per_hour": None,
            "remaining_hours": None,
        }
    return {
        "available": True,
        "mean": est["mean"],
        "lower": est["lower"],
        "upper": est["upper"],
        "margin": est["margin"],
        "scenario": est["scenario"],
        "scenarios": est["scenarios"],
        "sources": est["sources"],
        "mode": est["mode"],
        "ttb_hours": ttb,
        "pace_pct_per_hour": insights["pace_pct_per_hour"],
        "remaining_hours": insights["remaining_hours"],
        "updated_at": est["updated_at"],
    }


@router.get("/games/{game_id}/progress")
def get_game_progress(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    est = engine.latest_estimate(conn, game_id)
    if est is None:
        est = engine.recompute(conn, game_id, persist=True)
    return _progress_response(conn, game_id, est)


@router.put("/games/{game_id}/progress/config")
def put_game_progress_config(game_id: int, body: ProgressConfigIn, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    engine.set_ttb(conn, game_id, body.ttb_hours)
    est = engine.recompute(conn, game_id, persist=True, force=True)
    return _progress_response(conn, game_id, est)


@router.post("/games/{game_id}/progress/recompute")
def recompute_game_progress(game_id: int, conn: sqlite3.Connection = Conn) -> dict:
    _game(conn, game_id)
    est = engine.recompute(conn, game_id, persist=True, force=True)
    return _progress_response(conn, game_id, est)


@router.post("/progress/recompute")
def recompute_all_progress(conn: sqlite3.Connection = Conn) -> dict:
    updated = engine.recompute_all(conn)
    return {"updated": updated}


@router.get("/progress/calibration")
def get_calibration(conn: sqlite3.Connection = Conn) -> dict:
    return calibration.evaluate_against_ram(conn)


@router.get("/stats/insights")
def get_stats_insights(
    abandoned_days: int = Query(30, ge=1, le=365),
    conn: sqlite3.Connection = Conn,
) -> dict:
    return progress_stats.library_insights(conn, abandoned_days=abandoned_days)
