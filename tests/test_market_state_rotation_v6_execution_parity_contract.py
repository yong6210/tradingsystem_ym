from scripts.run_market_state_rotation_v6_execution_parity_contract import (
    build_execution_parity_contract_report,
)


def _walk_report() -> dict:
    return {
        "symbol": "BTCUSDT",
        "exec_interval": "5m",
        "folds": [
            {
                "fold": 1,
                "test_result": {
                    "config": {"unit_account_exposure": 10.0},
                    "event_diagnostics": {
                        "add_by_role": {"base": 10, "probe": 4, "chase": 2, "battle": 1},
                        "add_by_kst_hour": {"09": 3, "10": 4},
                        "remove_by_kst_hour": {"11": 2},
                    },
                },
            }
        ],
    }


def _journal_rows(count: int = 20, *, symbol: str = "BTCUSDT", family: str = "market_state_rotation_v6") -> list[dict]:
    rows: list[dict] = []
    for idx in range(count):
        action = "add" if idx % 2 == 0 else "remove"
        role = "base" if idx % 3 == 0 else ("probe" if idx % 3 == 1 else "chase")
        rows.append(
            {
                "timestamp": f"2026-01-01T00:{idx:02d}:00Z",
                "symbol": symbol,
                "strategy_family": family,
                "decision_id": f"msrv6-{idx}",
                "source_bar_ts": f"2026-01-01T00:{idx:02d}:00Z",
                "actual_action": action,
                "expected_action": action,
                "actual_side": "long" if idx % 4 < 2 else "short",
                "expected_side": "long" if idx % 4 < 2 else "short",
                "role": role,
                "signal_lag_bars": 0,
                "position_diff_units": 0.0,
                "fee_slippage_bps": 4.5,
                "effective_exposure": 2.0,
            }
        )
    return rows


def test_execution_parity_contract_reports_missing_journal_as_watch() -> None:
    report = build_execution_parity_contract_report(_walk_report())

    assert report["overall_status"] == "WATCH"
    assert report["summary"]["passed"] is False
    assert "execution_journal_missing" in report["summary"]["blockers"]
    assert "insufficient_execution_sample_count" in report["summary"]["blockers"]
    assert report["summary"]["strategy_families"] == ["market_state_rotation_v6"]
    assert report["contract"]["expected_add_by_role"] == {"base": 10, "chase": 2, "probe": 4}
    assert report["contract"]["ignored_unknown_add_by_role"] == {"battle": 1}


def test_execution_parity_contract_passes_matching_lineage_journal() -> None:
    report = build_execution_parity_contract_report(
        _walk_report(),
        _journal_rows(),
        max_effective_exposure=2.5,
    )

    assert report["overall_status"] == "PASS"
    assert report["summary"]["passed"] is True
    assert report["summary"]["sample_count"] == 20
    assert report["summary"]["order_match_rate"] == 1.0
    assert report["summary"]["max_signal_lag_bars"] == 0.0
    assert report["summary"]["max_position_diff_units"] == 0.0
    assert report["summary"]["blockers"] == []
    assert report["observed"]["role_counts"] == {"base": 7, "chase": 6, "probe": 7}


def test_execution_parity_contract_expected_symbol_can_override_walk_symbol() -> None:
    report = build_execution_parity_contract_report(
        _walk_report(),
        _journal_rows(symbol="BTCUSDC"),
        expected_symbol="BTCUSDC",
        max_effective_exposure=2.5,
    )

    assert report["overall_status"] == "PASS"
    assert report["summary"]["symbol"] == "BTCUSDC"
    assert report["summary"]["walk_forward_symbol"] == "BTCUSDT"
    assert report["observed"]["symbol_mismatch_count"] == 0
    assert "execution_parity_symbol_mismatch" not in report["summary"]["blockers"]


def test_execution_parity_contract_blocks_wrong_symbol_family_and_action_mismatch() -> None:
    rows = _journal_rows(symbol="ETHUSDT", family="session_impulse_retest")
    rows[0]["expected_action"] = "remove"
    rows[1]["signal_lag_bars"] = 2
    rows[2]["position_diff_units"] = 0.2
    rows[3]["fee_slippage_bps"] = 40
    rows[4]["effective_exposure"] = 3.0

    report = build_execution_parity_contract_report(
        _walk_report(),
        rows,
        max_effective_exposure=2.5,
    )

    blockers = report["summary"]["blockers"]
    assert report["overall_status"] == "FAIL"
    assert "execution_parity_symbol_mismatch" in blockers
    assert "execution_parity_strategy_family_mismatch" in blockers
    assert "order_match_rate_below_threshold" in blockers
    assert "signal_lag_bars_above_threshold" in blockers
    assert "position_diff_above_threshold" in blockers
    assert "fee_slippage_bps_above_threshold" in blockers
    assert "effective_exposure_above_contract_cap" in blockers


def test_execution_parity_contract_requires_lineage_and_drift_fields() -> None:
    rows = _journal_rows()
    for key in (
        "decision_id",
        "source_bar_ts",
        "expected_action",
        "expected_side",
        "signal_lag_bars",
        "position_diff_units",
        "fee_slippage_bps",
    ):
        rows[0].pop(key)

    report = build_execution_parity_contract_report(_walk_report(), rows)

    assert report["overall_status"] == "FAIL"
    assert "execution_journal_schema_missing_required_fields" in report["summary"]["blockers"]
    assert report["observed"]["schema_issue_counts"]["missing_decision_id"] == 1
    assert report["observed"]["schema_issue_counts"]["missing_expected_action"] == 1
    assert report["observed"]["schema_issue_counts"]["missing_position_diff_units"] == 1
