"""Tests for progress calibration and evaluation against RAM ground truth."""

from datetime import datetime, timezone

from app.progress.calibration import CalibrationTrace, calibrate_params, evaluate_against_ram, evaluate_traces
from app.progress.hmm import FilterParams


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _synthetic_trace(game_id: int) -> CalibrationTrace:
    kinds = ["progression"] * 9 + ["win_condition"]
    return CalibrationTrace(
        game_id=game_id,
        scenario="",
        kinds=kinds,
        ttb_hours=10.0,
        sessions=[
            (_dt("2026-11-01T10:00:00Z"), _dt("2026-11-01T12:00:00Z")),
            (_dt("2026-11-02T09:00:00Z"), _dt("2026-11-02T12:00:00Z")),
            (_dt("2026-11-03T09:00:00Z"), _dt("2026-11-03T12:00:00Z")),
            (_dt("2026-11-04T10:00:00Z"), _dt("2026-11-04T12:00:00Z")),
        ],
        achievements=[
            ("2026-11-01T12:01:00Z", 2, False),
            ("2026-11-02T12:01:00Z", 5, False),
            ("2026-11-03T12:01:00Z", 8, False),
            ("2026-11-04T12:01:00Z", 10, True),
        ],
        ram_points=[
            ("2026-11-01T12:02:00Z", 20.0),
            ("2026-11-02T12:02:00Z", 50.0),
            ("2026-11-03T12:02:00Z", 80.0),
            ("2026-11-04T12:02:00Z", 100.0),
        ],
    )


def test_evaluate_traces_computes_mae_rmse_and_coverage():
    report = evaluate_traces([_synthetic_trace(1)])
    assert report["games"] == 1
    assert report["traces"] == 1
    assert report["note"] is not None  # few games warning

    pt = report["subsets"]["playtime_only"]
    both = report["subsets"]["achievements_and_playtime"]
    assert pt["samples"] == 4
    assert pt["mae"] is not None and pt["mae"] < 20.0
    assert pt["ci_coverage_90"] >= 0.75
    assert both["samples"] == 4
    assert both["mae"] <= pt["mae"] + 5.0


def test_calibrate_params_respects_coverage_floor():
    traces = [_synthetic_trace(1), _synthetic_trace(2)]
    tuned, report = calibrate_params(traces, base_params=FilterParams(), min_coverage=0.85)
    assert isinstance(tuned, FilterParams)
    metrics = report["subsets"]["achievements_and_playtime"]
    assert metrics["ci_coverage_90"] >= 0.85


def test_evaluate_against_empty_db_returns_zero_samples(conn):
    report = evaluate_against_ram(conn)
    assert report["games"] == 0
    assert report["subsets"]["playtime_only"]["samples"] == 0
    assert report["note"] is not None
