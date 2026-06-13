import subprocess
import sys
from datetime import UTC, datetime, timedelta

import scripts.run_market_state_rotation_v6_quote_shadow_audit as quote_shadow
from scripts.run_market_state_rotation_v6_quote_shadow_audit import (
    build_quote_shadow_audit_report,
    build_quote_shadow_row,
)


def _book() -> dict:
    return {
        "bids": [["99999", "1.0"], ["99998", "1.0"]],
        "asks": [["100001", "1.0"], ["100002", "1.0"]],
    }


def test_quote_shadow_audit_import_does_not_load_binance_client_module() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "import scripts.run_market_state_rotation_v6_quote_shadow_audit; "
                "print('app.integrations.binance_futures' in sys.modules)"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.stdout.strip() == "False"


def test_capture_quote_shadow_rows_loads_client_lazily(monkeypatch) -> None:
    class FakeClient:
        def fetch_order_book(self, *, symbol: str, limit: int) -> dict:
            assert symbol == "BTCUSDT"
            assert limit == 100
            return _book()

    monkeypatch.setattr(quote_shadow, "_binance_futures_client_cls", lambda: FakeClient)

    rows = quote_shadow.capture_quote_shadow_rows(
        symbol="BTCUSDT",
        strategy_family="market_state_rotation_v6",
        decision_id="decision_1",
        side="both",
        order_notional_usdt=100.0,
        order_book_limit=100,
    )

    assert [row["side"] for row in rows] == ["long", "short"]
    assert all(row["source"] == "binance_public_order_book" for row in rows)


def test_quote_shadow_row_computes_spread_depth_and_slippage() -> None:
    row = build_quote_shadow_row(
        order_book=_book(),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="BTCUSDT",
        strategy_family="market_state_rotation_v6",
        decision_id="decision_1",
        side="long",
        order_notional_usdt=100.0,
        latency_ms=25.0,
    )

    assert row["symbol"] == "BTCUSDT"
    assert row["side"] == "long"
    assert row["spread_bps"] == 0.2
    assert row["market_slippage_bps"] > 0
    assert row["depth_notional"] == 200003.0


def test_quote_shadow_audit_passes_when_sample_and_day_gates_are_met() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        build_quote_shadow_row(
            order_book=_book(),
            timestamp=base + timedelta(days=idx),
            symbol="BTCUSDT",
            strategy_family="market_state_rotation_v6",
            decision_id=f"decision_{idx}",
            side="short" if idx % 2 else "long",
            order_notional_usdt=100.0,
            latency_ms=50.0,
        )
        for idx in range(3)
    ]

    report = build_quote_shadow_audit_report(
        rows,
        required_quote_samples=3,
        min_calendar_days=3,
        min_distinct_hours=3,
        max_p95_spread_bps=4.0,
        max_p95_market_slippage_bps=8.0,
        max_p95_latency_ms=1500.0,
        generated_at=base + timedelta(days=3),
    )

    assert report["overall_status"] == "PASS"
    assert report["eligible_row_count"] == 3
    assert report["calendar_day_count"] == 3
    assert report["distinct_hour_count"] == 3
    assert report["coverage"]["first_sample_ts"] == base.isoformat()
    assert report["coverage"]["latest_sample_ts"] == (base + timedelta(days=2)).isoformat()
    assert report["coverage"]["latest_sample_age_hours"] == 24.0
    assert report["coverage"]["utc_hour_of_day_covered"] == ["00"]
    assert report["coverage"]["utc_hour_of_day_missing"][0] == "01"
    assert report["blockers"] == []


def test_quote_shadow_audit_is_incomplete_before_sample_floor() -> None:
    row = build_quote_shadow_row(
        order_book=_book(),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        symbol="BTCUSDT",
        strategy_family="market_state_rotation_v6",
        decision_id="decision_1",
        side="long",
        order_notional_usdt=100.0,
        latency_ms=50.0,
    )

    report = build_quote_shadow_audit_report([row], required_quote_samples=3, min_calendar_days=2)

    assert report["overall_status"] == "INCOMPLETE"
    assert "quote_samples_missing" in report["blockers"]
    assert "calendar_days_missing" in report["blockers"]


def test_quote_shadow_audit_blocks_samples_concentrated_in_one_hour() -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        build_quote_shadow_row(
            order_book=_book(),
            timestamp=base + timedelta(minutes=idx),
            symbol="BTCUSDT",
            strategy_family="market_state_rotation_v6",
            decision_id=f"decision_{idx}",
            side="long",
            order_notional_usdt=100.0,
            latency_ms=50.0,
        )
        for idx in range(3)
    ]

    report = build_quote_shadow_audit_report(
        rows,
        required_quote_samples=3,
        min_calendar_days=1,
        min_distinct_hours=2,
    )

    assert report["overall_status"] == "INCOMPLETE"
    assert report["distinct_hour_count"] == 1
    assert report["coverage"]["utc_hour_of_day_covered_count"] == 1
    assert "distinct_hours_missing" in report["blockers"]
