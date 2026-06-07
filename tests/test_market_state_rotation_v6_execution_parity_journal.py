from datetime import UTC, datetime

from scripts.run_market_state_rotation_v6_execution_parity_journal import (
    build_execution_parity_journal_report,
    build_execution_parity_journal_rows,
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
                        "add_by_role": {"base": 10, "probe": 6, "chase": 4},
                        "add_by_kst_hour": {"09": 10, "10": 10},
                        "remove_by_kst_hour": {"11": 10},
                    },
                },
            }
        ],
    }


def _lifecycle_rows(count: int = 20) -> list[dict]:
    rows = []
    for idx in range(count):
        role = "base" if idx % 3 == 0 else ("probe" if idx % 3 == 1 else "chase")
        side = "long" if idx % 2 == 0 else "short"
        exchange_side = "BUY" if side == "long" else "SELL"
        ts = f"2026-01-01T00:{idx:02d}:00+00:00"
        rows.append(
            {
                "symbol": "BTCUSDT",
                "strategy_family": "market_state_rotation_v6",
                "plan_id": f"plan-{idx}",
                "intent_id": f"intent-{idx}",
                "submission_id": f"sub-{idx}",
                "client_order_id": f"client-{idx}",
                "adapter": "paper",
                "side": exchange_side,
                "plan_direction": side,
                "submitted_at": ts,
                "acknowledged_at": ts,
                "entry_first_fill_at": ts,
                "entry_fill_count": 1,
                "entry_fill_qty": 1.0,
                "entry_slippage_bps": 4.5,
                "plan_source_event": {
                    "ts": ts,
                    "action": "add",
                    "side": side,
                    "role": role,
                },
            }
        )
    return rows


def _closed_lifecycle_rows(count: int = 10) -> list[dict]:
    rows = _lifecycle_rows(count)
    for idx, row in enumerate(rows):
        side = row["plan_direction"]
        exit_ts = f"2026-01-01T01:{idx:02d}:00+00:00"
        row.update(
            {
                "exit_last_fill_at": exit_ts,
                "exit_fill_count": 1,
                "exit_fill_qty": 1.0,
                "exit_slippage_bps": 3.0,
                "exit_source_event": {
                    "ts": exit_ts,
                    "action": "remove",
                    "side": side,
                    "price": 100_100.0,
                },
            }
        )
    return rows


def test_execution_parity_journal_converts_paper_lifecycle_rows_to_contract_rows() -> None:
    rows = build_execution_parity_journal_rows({"rows": _lifecycle_rows()})

    assert len(rows) == 20
    assert rows[0]["actual_action"] == "add"
    assert rows[0]["expected_action"] == "add"
    assert rows[0]["position_diff_units"] == 0.0
    assert rows[0]["fee_slippage_bps"] == 4.5
    assert rows[0]["signal_lag_bars"] == 0.0


def test_execution_parity_journal_report_passes_when_lifecycle_has_required_fields() -> None:
    report, journal_rows = build_execution_parity_journal_report(
        walk_report=_walk_report(),
        lifecycle_payload={"rows": _lifecycle_rows()},
        input_walk_report="walk.json",
        input_lifecycle_report="lifecycle.json",
        input_execution_journal="journal.jsonl",
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert len(journal_rows) == 20
    assert report["no_live_order_sent"] is True
    assert report["status"] == "execution_parity_journal_passed"
    assert report["contract_summary"]["passed"] is True
    assert report["conversion"]["missing_to_min_sample_count"] == 0
    assert report["collection_plan"]["status"] == "passed"
    assert report["collection_plan"]["estimated_future_paper_apply_events_needed"] == 0
    assert report["collection_plan"]["accepted_actions"] == ["add"]
    assert report["collection_plan"]["backtest_substitution_allowed"] is False
    assert report["collection_plan"]["no_live_order_sent"] is True


def test_execution_parity_journal_can_count_exit_rows_when_exit_fields_are_complete() -> None:
    report, journal_rows = build_execution_parity_journal_report(
        walk_report=_walk_report(),
        lifecycle_payload={"rows": _closed_lifecycle_rows(10)},
        min_sample_count=20,
        include_exit_rows=True,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert len(journal_rows) == 20
    assert sum(1 for row in journal_rows if row["actual_action"] == "add") == 10
    assert sum(1 for row in journal_rows if row["actual_action"] == "remove") == 10
    assert all(row["fee_slippage_bps"] is not None for row in journal_rows)
    assert report["status"] == "execution_parity_journal_passed"
    assert report["contract_summary"]["passed"] is True
    assert report["collection_plan"]["accepted_actions"] == ["add", "remove"]
    assert report["collection_plan"]["entry_rows_written"] == 10
    assert report["collection_plan"]["exit_rows_written"] == 10


def test_execution_parity_journal_collection_plan_counts_missing_paper_apply_events() -> None:
    report, journal_rows = build_execution_parity_journal_report(
        walk_report=_walk_report(),
        lifecycle_payload={"rows": _lifecycle_rows(3)},
        min_sample_count=20,
        include_exit_rows=True,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert len(journal_rows) == 3
    assert report["status"] == "execution_parity_journal_collecting"
    assert report["collection_plan"]["status"] == "collecting_samples"
    assert report["collection_plan"]["sample_count"] == 3
    assert report["collection_plan"]["required_samples"] == 20
    assert report["collection_plan"]["missing_samples"] == 17
    assert report["collection_plan"]["estimated_future_paper_apply_events_needed"] == 17
    assert report["collection_plan"]["sample_credit_per_completed_paper_apply_event"] == 1
    assert report["collection_plan"]["accepted_actions"] == ["add", "remove"]
    assert report["collection_plan"]["non_substitutable"] is True


def test_execution_parity_journal_keeps_schema_blocker_when_source_event_missing() -> None:
    lifecycle = {"rows": _lifecycle_rows(1)}
    lifecycle["rows"][0]["plan_source_event"] = {}
    lifecycle["rows"][0]["plan_source_event_ts"] = ""

    report, journal_rows = build_execution_parity_journal_report(
        walk_report=_walk_report(),
        lifecycle_payload=lifecycle,
        min_sample_count=1,
        generated_at=datetime(2026, 6, 7, tzinfo=UTC),
    )

    assert journal_rows[0]["source_bar_ts"] is None
    assert report["status"] == "execution_parity_journal_collecting"
    assert "execution_journal_schema_missing_required_fields" in report["contract_summary"]["blockers"]
    assert report["contract_observed"]["schema_issue_counts"]["missing_source_bar_ts"] == 1
    assert report["collection_plan"]["status"] == "schema_or_threshold_blocked"
    assert report["collection_plan"]["missing_samples"] == 0
    assert report["collection_plan"]["next_step"] == "fix_contract_blockers_before_promotion"
