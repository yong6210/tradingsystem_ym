from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_conditional_overfit_holdout_audit import (
    build_conditional_overfit_holdout_audit,
)


def _compound(values: list[float]) -> float:
    equity = 1.0
    for value in values:
        equity *= 1.0 + value / 100.0
    return round((equity - 1.0) * 100.0, 4)


def _report(returns: list[float], *, token_folds: set[int] | None = None) -> dict:
    token_folds = token_folds or set()
    folds = []
    costs = [1.0 for _ in returns]
    drawdowns = [3.0 for _ in returns]
    events = [10 for _ in returns]
    for idx, value in enumerate(returns, start=1):
        folds.append(
            {
                "fold": idx,
                "test_start": f"2026-01-{idx:02d}",
                "test_end": f"2026-01-{idx + 1:02d}",
                "selected_model_id": "base:wfWinPyrMinExtAS" if idx in token_folds else "base",
                "after_selection_overlays_applied": (
                    ["winner_pyramid_min_extension"] if idx in token_folds else []
                ),
                "test_result": {
                    "total_return_pct": value,
                    "max_drawdown_pct": drawdowns[idx - 1],
                    "estimated_cost_drag_pct": costs[idx - 1],
                    "trade_like_events": events[idx - 1],
                },
            }
        )
    return {
        "folds": folds,
        "aggregate": {
            "fold_count": len(returns),
            "compounded_oos_return_pct": _compound(returns),
            "avg_oos_return_pct": round(sum(returns) / len(returns), 4),
            "min_oos_return_pct": min(returns),
            "positive_fold_count": sum(1 for item in returns if item > 0),
            "max_fold_drawdown_pct": max(drawdowns),
            "avg_oos_cost_drag_pct": round(sum(costs) / len(costs), 4),
            "total_trade_like_events": sum(events),
        },
    }


def _compare() -> dict:
    return {
        "best_candidate": {
            "recipe_id": "conditional_candidate",
            "decision": "promotion_candidate_after_formal_wfo",
            "overfit_audit": {
                "status": "requires_shadow_holdout_review",
                "conditional_model_token": "wfWinPyrMinExtAS",
                "conditional_overlay_keys": ["winner_pyramid_min_extension_after_selection"],
            },
        }
    }


def test_conditional_overfit_holdout_audit_passes_historical_proxy_without_tail_damage() -> None:
    payload = build_conditional_overfit_holdout_audit(
        baseline_report=_report([10.0, 20.0, 30.0, 40.0]),
        candidate_report=_report([10.0, 21.0, 30.0, 40.8], token_folds={2}),
        compare_report=_compare(),
        tail_holdout_folds=2,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert payload["status"] == "historical_proxy_pass_real_shadow_required"
    assert payload["blockers"] == []
    assert payload["tail_holdout_proxy"]["passed"] is True
    assert payload["conditional_token_proxy"]["passed"] is True
    assert payload["no_live_order_sent"] is True


def test_conditional_overfit_holdout_audit_blocks_when_tail_proxy_worsens() -> None:
    payload = build_conditional_overfit_holdout_audit(
        baseline_report=_report([10.0, 20.0, 30.0, 40.0]),
        candidate_report=_report([10.0, 21.0, 30.0, 39.0], token_folds={2}),
        compare_report=_compare(),
        tail_holdout_folds=2,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert payload["status"] == "historical_proxy_failed_real_shadow_required"
    assert "tail_holdout_proxy_not_worse" in payload["blockers"]
    assert payload["tail_holdout_proxy"]["passed"] is False
    assert payload["no_live_order_sent"] is True
