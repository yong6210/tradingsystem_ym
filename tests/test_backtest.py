from types import SimpleNamespace

import pytest

from app.services.backtest import BacktestService


def _outcome(win):
    return SimpleNamespace(hit_1r=win, hit_2r=False, hit_3r=False)


def test_bootstrap_captures_sampling_uncertainty_and_is_reproducible():
    service = BacktestService()
    outcomes = [_outcome(True), _outcome(False)]
    result = service.monte_carlo(outcomes, simulations=1000, seed=42)
    assert result == service.monte_carlo(outcomes, simulations=1000, seed=42)
    assert result.trades == 2
    assert result.p5_ev == -1.0
    assert result.p95_ev == 1.0
    assert abs(result.mean_ev) < 0.1


def test_bootstrap_does_not_invent_returns_for_constant_sample():
    result = BacktestService().monte_carlo([_outcome(True)] * 3, seed=42)
    assert result.mean_ev == result.p5_ev == result.p50_ev == result.p95_ev == 1.0


@pytest.mark.parametrize("simulations", [0, -1, 1.5, True])
def test_bootstrap_rejects_invalid_simulation_count(simulations):
    with pytest.raises(ValueError, match="positive integer"):
        BacktestService().monte_carlo([_outcome(True)], simulations=simulations)


def test_bootstrap_empty_sample_is_unavailable_zero_report():
    result = BacktestService().monte_carlo([], seed=42)
    assert result.trades == 0
    assert result.mean_ev == 0.0


def test_legacy_summary_does_not_claim_walk_forward_validation():
    service = BacktestService()
    result = service.walk_forward([])
    assert result.method == "empirical_outcome_summary"
    assert result.out_of_sample_validated is False
    assert service.monte_carlo([], seed=42).method == "iid_bootstrap_mean_ev"
    assert service.monte_carlo([_outcome(True)], seed=42).method == "iid_bootstrap_mean_ev"
