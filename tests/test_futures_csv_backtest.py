from __future__ import annotations

from pathlib import Path

from app.services.futures_csv_backtest import load_1m_csv_candles, resample_candles_5m, run_futures_csv_backtest


def test_load_1m_csv_candles_supports_ninjatrader_header(tmp_path: Path) -> None:
    csv_path = tmp_path / "nq.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Time,Open,High,Low,Close,Volume",
                "2026-04-24 08:30:00,20010.25,20012.00,20008.50,20011.75,1543",
                "2026-04-24 08:31:00,20011.75,20013.00,20010.00,20012.50,1650",
            ]
        ),
        encoding="utf-8",
    )

    candles = load_1m_csv_candles(csv_path=csv_path, timezone_name="America/Chicago")

    assert len(candles) == 2
    assert candles[0].ts.isoformat() == "2026-04-24T13:30:00+00:00"
    assert candles[0].o == 20010.25
    assert candles[1].c == 20012.50


def test_resample_candles_5m_rolls_up_expected_bucket(tmp_path: Path) -> None:
    csv_path = tmp_path / "nq_rollup.csv"
    rows = ["timestamp,open,high,low,close,volume"]
    for minute in range(5):
        rows.append(
            f"2026-04-24 08:{30 + minute:02d}:00,{20000 + minute},{20001 + minute},{19999 + minute},{20000.5 + minute},10"
        )
    csv_path.write_text("\n".join(rows), encoding="utf-8")

    candles_1m = load_1m_csv_candles(csv_path=csv_path, timezone_name="UTC")
    candles_5m = resample_candles_5m(candles_1m)

    assert len(candles_5m) == 1
    assert candles_5m[0].o == 20000.0
    assert candles_5m[0].h == 20005.0
    assert candles_5m[0].l == 19999.0
    assert candles_5m[0].c == 20004.5
    assert candles_5m[0].v == 50.0


def test_run_futures_csv_backtest_reports_insufficient_candles(tmp_path: Path) -> None:
    csv_path = tmp_path / "small.csv"
    csv_path.write_text(
        "\n".join(
            [
                "timestamp,open,high,low,close,volume",
                "2026-04-24 08:30:00,20010,20012,20008,20011,10",
                "2026-04-24 08:31:00,20011,20013,20010,20012,10",
            ]
        ),
        encoding="utf-8",
    )

    payload = run_futures_csv_backtest(
        csv_path=csv_path,
        symbol="NQ1!",
        profile_name="baseline",
        timezone_name="UTC",
    )

    assert payload["error"] == "insufficient_candles"
    assert payload["symbol"] == "NQ1!"
