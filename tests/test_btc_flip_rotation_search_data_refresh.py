import sys
from datetime import UTC, datetime, timedelta

from scripts import run_btc_flip_rotation_search as search


def test_data_refresh_only_writes_separate_report_without_strategy_latest(monkeypatch, tmp_path) -> None:
    calls = []
    start = datetime(2026, 1, 1, tzinfo=UTC)

    def fake_load_bars(**kwargs):
        calls.append(kwargs)
        interval = str(kwargs["interval"])
        step = timedelta(minutes=5 if interval == "5m" else 60)
        return [
            search.Bar(ts=start, open_ms=int(start.timestamp() * 1000), o=100.0, h=101.0, l=99.0, c=100.5, v=1.0),
            search.Bar(
                ts=start + step,
                open_ms=int((start + step).timestamp() * 1000),
                o=100.5,
                h=102.0,
                l=100.0,
                c=101.0,
                v=1.0,
            ),
        ]

    monkeypatch.setattr(search, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(search, "_load_bars", fake_load_bars)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_btc_flip_rotation_search.py",
            "--data-refresh-only",
            "--write-report",
            "--symbol",
            "BTCUSDT",
            "--days",
            "30",
            "--intervals",
            "5m,1h",
            "--cache-dir",
            "cache",
            "--report-dir",
            "reports",
            "--max-cache-age-minutes",
            "0",
        ],
    )

    assert search.main() == 0

    refresh_latest = tmp_path / "reports" / "data_refresh_latest.json"
    assert refresh_latest.exists()
    assert not (tmp_path / "reports" / "latest.json").exists()
    assert len(calls) == 2
    assert {call["interval"] for call in calls} == {"5m", "1h"}
    assert all(call["max_cache_age_minutes"] == 0.0 for call in calls)
