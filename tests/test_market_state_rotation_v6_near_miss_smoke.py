from datetime import UTC, datetime
from types import SimpleNamespace

import scripts.run_market_state_rotation_v6_near_miss_smoke as near_miss
from scripts.run_market_state_rotation_v6_near_miss_smoke import (
    _candidate_configs,
    _summarize_result,
    _with_deltas,
    build_near_miss_smoke_report,
)


def _result(*, return_pct: float, dd: float, trade_events: int, adds: int) -> dict:
    return {
        "model_id": "model",
        "total_return_pct": return_pct,
        "max_drawdown_pct": dd,
        "trade_like_events": trade_events,
        "event_diagnostics": {
            "add_events": adds,
            "remove_events": trade_events - adds,
            "ratios": {
                "turnover_events_per_add": 2.0,
                "probe_add_per_add": 0.1,
                "one_way_forced_trim_per_add": 0.2,
            },
        },
        "recent_events": [],
    }


def test_near_miss_smoke_promotes_candidate_that_adds_entries_without_breaking_gates() -> None:
    rows = _with_deltas(
        [
            _summarize_result("base", {}, _result(return_pct=50, dd=10, trade_events=20, adds=10)),
            _summarize_result(
                "near_miss_probe_001_guarded",
                {"near_miss_probe_units": 0.001},
                _result(return_pct=48, dd=12, trade_events=24, adds=13),
            ),
        ]
    )

    candidate = rows[1]

    assert candidate["delta_vs_base"]["add_events"] == 3
    assert candidate["delta_vs_base"]["return_pct"] == -2
    assert candidate["delta_vs_base"]["max_drawdown_pct"] == 2
    assert candidate["smoke_decision"] == "promote_to_full_walk_forward_evidence_probe_candidate"
    assert candidate["primary_use"] == "paper_evidence_collection_probe"


def test_near_miss_smoke_rejects_candidate_with_large_drawdown_worsening() -> None:
    rows = _with_deltas(
        [
            _summarize_result("base", {}, _result(return_pct=50, dd=10, trade_events=20, adds=10)),
            _summarize_result(
                "near_miss_probe_0025_guarded",
                {"near_miss_probe_units": 0.0025},
                _result(return_pct=55, dd=16, trade_events=26, adds=14),
            ),
        ]
    )

    assert rows[1]["delta_vs_base"]["max_drawdown_pct"] == 6
    assert rows[1]["smoke_decision"] == "reject_or_keep_for_manual_review"


def test_near_miss_candidate_configs_include_mc04_mc12_context_hotspot_probe(monkeypatch) -> None:
    def fake_replace(base, **changes):
        data = dict(vars(base))
        data.update(changes)
        return SimpleNamespace(**data)

    monkeypatch.setattr(near_miss, "replace", fake_replace)

    candidates = _candidate_configs(SimpleNamespace(model_id="base"))
    by_name = {name: change for name, change, _config in candidates}
    change = by_name["near_miss_mc12_mc04_trend_normal_0001_score3_ext15"]

    assert change["near_miss_probe_allowed_soft_reasons"] == (
        "MC12_low_confluence",
        "MC04_no_clear_first_touch",
    )
    assert change["near_miss_probe_allowed_alignments"] == ("with_trend",)
    assert change["near_miss_probe_allowed_execution_contexts"] == ("normal",)
    assert change["near_miss_probe_min_score"] == 3
    assert change["near_miss_probe_units"] == 0.0001


def test_near_miss_smoke_inherits_source_report_runtime_context(monkeypatch) -> None:
    captured = {}

    def fake_load_feature_sets(namespace):
        captured["namespace"] = namespace
        return object(), {}, {}, {
            "exec_start": "2026-01-01T00:00:00+00:00",
            "exec_end": "2026-06-05T00:00:00+00:00",
        }

    def fake_backtest_config(**kwargs):
        captured.setdefault("backtest_kwargs", []).append(kwargs)
        return _result(return_pct=10, dd=1, trade_events=2, adds=1)

    monkeypatch.setattr(near_miss, "_source_config", lambda _report: SimpleNamespace(model_id="source"))
    monkeypatch.setattr(
        near_miss,
        "_candidate_configs",
        lambda base: [
            ("base", {}, SimpleNamespace(model_id=base.model_id)),
            (
                "probe",
                {"near_miss_probe_units": 0.0001},
                SimpleNamespace(model_id="probe"),
            ),
        ],
    )
    monkeypatch.setattr(near_miss, "_load_feature_sets", fake_load_feature_sets)
    monkeypatch.setattr(near_miss, "backtest_config", fake_backtest_config)

    report = build_near_miss_smoke_report(
        source_report={
            "args": {
                "load_days": 1825,
                "exec_interval": "5m",
                "scenario_intervals": "1h,4h",
                "cache_dir": "source/cache",
                "base_url": "https://source.example",
                "sleep_seconds": 0.0,
                "fee_bps_per_side": 7.0,
                "slippage_bps_per_side": 2.0,
                "funding_bps_per_8h": 1.5,
                "borrow_bps_per_day": 0.25,
                "min_periods": 7000,
            }
        },
        days=120,
        generated_at=datetime(2026, 6, 5, tzinfo=UTC),
    )

    namespace = captured["namespace"]
    assert namespace.load_days == 1825
    assert namespace.cache_dir == "source/cache"
    assert namespace.base_url == "https://source.example"
    assert captured["backtest_kwargs"][0]["min_periods"] == 7000
    assert captured["backtest_kwargs"][0]["cost_rate"] == 0.0009
    assert report["window"]["load_days"] == 1825
    assert report["resolved_runtime_args"]["fee_bps_per_side"] == 7.0
