"""Synthetic signal tests for the pure-NumPy discrete Bayesian progress filter (HMM)."""

import pytest

from app.progress.hmm import DiscreteProgressFilter, FilterParams


def test_playtime_only_advances_with_wide_confidence_interval():
    filt = DiscreteProgressFilter.generic()
    # 4 hours into a 10-hour game -> ~40% with wide uncertainty
    filt.predict(dt_hours=2.0, ttb_hours=10.0)
    filt.predict(dt_hours=2.0, ttb_hours=10.0)
    est = filt.estimate()
    assert 25.0 <= est.mean <= 55.0
    assert est.upper - est.lower >= 20.0
    assert est.lower <= est.mean <= est.upper


def test_ram_observation_collapses_confidence_interval():
    kinds = ["progression"] * 9 + ["win_condition"]
    filt = DiscreteProgressFilter.for_milestones(kinds)
    filt.predict(dt_hours=3.0, ttb_hours=10.0)
    wide = filt.estimate()
    assert wide.margin >= 10.0

    reset = filt.update_ram(furthest_idx=6, win_reached=False)
    assert not reset
    tight = filt.estimate()
    assert abs(tight.mean - 60.0) <= 3.0
    assert tight.margin <= 5.0


def test_furthest_milestone_matters_more_than_raw_count():
    kinds = ["progression"] * 10
    f_low = DiscreteProgressFilter.for_milestones(kinds)
    f_low.update_ram(furthest_idx=3)

    f_high = DiscreteProgressFilter.for_milestones(kinds)
    f_high.update_ram(furthest_idx=5)

    assert f_high.estimate().mean > f_low.estimate().mean


def test_win_condition_locks_progress_to_100_even_before_last_index():
    # Milestone 8 is win_condition, milestones 9..10 are post-game or later listed
    kinds = ["progression"] * 7 + ["win_condition", "progression", "progression"]
    filt = DiscreteProgressFilter.for_milestones(kinds)
    filt.predict(dt_hours=6.0, ttb_hours=10.0)
    filt.update_ram(furthest_idx=8, win_reached=True)
    est = filt.estimate()
    assert est.mean >= 98.0
    assert est.lower <= est.mean <= est.upper == 100.0
    # Further playtime after winning must never regress below 100%
    filt.predict(dt_hours=2.0, ttb_hours=10.0)
    after = filt.estimate()
    assert after.mean >= 98.0
    assert after.lower <= after.mean <= after.upper == 100.0


def test_win_condition_via_achievements_never_inverts_ci():
    kinds = ["progression"] * 7 + ["win_condition", "progression", "progression"]
    filt = DiscreteProgressFilter.for_milestones(kinds)
    filt.predict(dt_hours=6.0, ttb_hours=10.0)
    filt.update_achievements(furthest_idx=8, win_reached=True)
    est = filt.estimate()
    assert est.lower <= est.mean <= est.upper
    assert est.mean >= 95.0


def test_achievements_act_as_lower_bound_without_capping_upper_tail():
    kinds = ["progression"] * 9 + ["win_condition"]
    filt = DiscreteProgressFilter.for_milestones(kinds)
    filt.predict(dt_hours=5.0, ttb_hours=10.0)
    filt.update_achievements(furthest_idx=5, win_reached=False)
    est = filt.estimate()
    assert est.mean >= 50.0
    assert est.lower >= 45.0
    # Upper bound remains above 50% since achievements only prove "at least here"
    assert est.upper > 55.0


def test_monotonicity_and_new_game_plus_reset_detection():
    kinds = ["progression"] * 9 + ["win_condition"]
    filt = DiscreteProgressFilter.for_milestones(kinds)
    filt.predict(dt_hours=7.0, ttb_hours=10.0)
    filt.update_ram(furthest_idx=8)
    assert filt.estimate().mean >= 78.0
    assert filt.resets == 0

    # Normal playtime never regresses belief
    before = filt.estimate().mean
    filt.predict(dt_hours=1.0, ttb_hours=10.0)
    assert filt.estimate().mean >= before

    # Loading an old save or starting New Game+: RAM drops sharply to milestone 1
    did_reset = filt.update_ram(furthest_idx=1)
    assert did_reset is True
    assert filt.resets == 1
    after = filt.estimate()
    assert abs(after.mean - 10.0) <= 5.0


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        DiscreteProgressFilter.for_milestones([])
    filt = DiscreteProgressFilter.generic(FilterParams(generic_states=10))
    # Non-positive dt is a no-op
    filt.predict(0.0, ttb_hours=10.0)
    assert filt.estimate().mean == 0.0
