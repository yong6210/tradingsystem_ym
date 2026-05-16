from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_micro_main_filter_model_search as filter_search
from scripts import run_micro_main_trait_policy_search as trait_search


def _write_backtest(path: Path, *, proxy_symbols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "proxy_symbols": proxy_symbols,
                "results": {
                    proxy_symbols[0]: {
                        "trades": [
                            {
                                "entry_ts": "2026-05-01T00:00:00+00:00",
                                "exit_ts": "2026-05-01T00:05:00+00:00",
                                "r_value": 1.0,
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("module", [filter_search, trait_search])
def test_research_latest_trade_backtest_prefers_current_live_contract(monkeypatch, tmp_path, module) -> None:
    backtest_dir = tmp_path / "validation" / "micro_main_usdt_proxy_backtests"
    matching = backtest_dir / "micro_main_usdt_proxy_backtest_20260515T175711Z.json"
    broader_newer = backtest_dir / "micro_main_usdt_proxy_backtest_20260516T095759Z.json"
    _write_backtest(matching, proxy_symbols=["BTCUSDT"])
    _write_backtest(broader_newer, proxy_symbols=["BTCUSDT", "ETHUSDT"])
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            validation_report_dir=str(tmp_path / "validation"),
            auto_trading_execution_mode="MICRO_LIVE",
            auto_trading_micro_live_allowed_symbols="BTCUSDC",
        ),
    )

    assert module._latest_trade_backtest_path() == matching
