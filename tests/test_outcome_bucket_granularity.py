from app.services.outcome_bucket_granularity import OutcomeBucketGranularityService


def test_outcome_bucket_granularity_identifies_top_condition_axis() -> None:
    service = OutcomeBucketGranularityService()

    payload = service.generate(
        score_to_outcome_funnel={
            "available": True,
            "report_window_days": 30,
            "decomposition": {
                "family": [
                    {
                        "key": "trend_continuation",
                        "runtime_candidates": 12,
                        "submitted": 6,
                        "closed": 10,
                        "baseline_cost_profitable_rate_from_closed": 0.3,
                    }
                ],
                "volatility_condition": [
                    {
                        "key": "low_vol",
                        "runtime_candidates": 4,
                        "submitted": 2,
                        "closed": 4,
                        "baseline_cost_profitable_rate_from_closed": 0.5,
                    },
                    {
                        "key": "high_vol",
                        "runtime_candidates": 5,
                        "submitted": 3,
                        "closed": 5,
                        "baseline_cost_profitable_rate_from_closed": 0.45,
                    },
                ],
                "cost_condition": [
                    {
                        "key": "low_cost",
                        "runtime_candidates": 4,
                        "submitted": 2,
                        "closed": 4,
                        "baseline_cost_profitable_rate_from_closed": 0.75,
                    },
                    {
                        "key": "high_cost",
                        "runtime_candidates": 5,
                        "submitted": 3,
                        "closed": 5,
                        "baseline_cost_profitable_rate_from_closed": 0.3,
                    },
                ],
                "liquidity_condition": [
                    {
                        "key": "deep_liquidity",
                        "runtime_candidates": 3,
                        "submitted": 2,
                        "closed": 3,
                        "baseline_cost_profitable_rate_from_closed": 0.6,
                    },
                    {
                        "key": "shallow_liquidity",
                        "runtime_candidates": 2,
                        "submitted": 1,
                        "closed": 2,
                        "baseline_cost_profitable_rate_from_closed": 0.55,
                    },
                ],
            },
        }
    )

    assert payload is not None
    assert payload["available"] is True
    assert payload["family_focus"]["key"] == "trend_continuation"
    assert payload["top_condition_axis"] == "cost_condition"
    assert payload["top_condition_bucket"]["key"] == "high_cost"
    assert payload["confidence"] == "medium"
    assert "top_axis:cost_condition" in payload["reason_codes"]
    assert payload["condition_axes"][2]["proxy_note"] == "liquidity_proxy"


def test_outcome_bucket_granularity_stays_informational_when_coverage_is_thin() -> None:
    service = OutcomeBucketGranularityService()

    payload = service.generate(
        score_to_outcome_funnel={
            "available": True,
            "report_window_days": 30,
            "decomposition": {
                "family": [
                    {
                        "key": "sweep_reversal",
                        "runtime_candidates": 3,
                        "submitted": 1,
                        "closed": 3,
                        "baseline_cost_profitable_rate_from_closed": 0.3333,
                    }
                ],
                "volatility_condition": [
                    {
                        "key": "high_vol",
                        "runtime_candidates": 2,
                        "submitted": 1,
                        "closed": 3,
                        "baseline_cost_profitable_rate_from_closed": 0.3333,
                    }
                ],
                "cost_condition": [],
                "liquidity_condition": [],
            },
        }
    )

    assert payload is not None
    assert payload["top_condition_axis"] == ""
    assert payload["top_condition_bucket"] is None
    assert payload["confidence"] == "low"
    assert payload["summary"].startswith("family=sweep_reversal remains family-first")
