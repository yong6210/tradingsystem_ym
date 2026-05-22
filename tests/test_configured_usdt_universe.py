from types import SimpleNamespace

from app.services import market_data, scanner
from app.services.market_data import MarketDataService


def test_market_data_usdt_universe_prefers_configured_micro_live_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        market_data,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_micro_live_allowed_symbols="BTCUSDT,ETHUSDT",
            session_impulse_retest_allowed_symbols="BTCUSDT,ETHUSDT,SOLUSDT",
            auto_trading_allowed_symbols="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT",
        ),
    )

    assert MarketDataService.default_universe("usdt_reliable_balanced_31") == ["BTCUSDT", "ETHUSDT"]
    assert MarketDataService.default_universe("micro_live_usdt_2") == ["BTCUSDT", "ETHUSDT"]


def test_scanner_usdt_universe_prefers_configured_micro_live_symbols(monkeypatch) -> None:
    monkeypatch.setattr(
        market_data,
        "get_settings",
        lambda: SimpleNamespace(
            auto_trading_micro_live_allowed_symbols="BTCUSDT,ETHUSDT",
            session_impulse_retest_allowed_symbols="BTCUSDT,ETHUSDT,SOLUSDT",
            auto_trading_allowed_symbols="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT",
        ),
    )

    assert scanner.get_universe_symbols("usdt_reliable_balanced_31") == ["BTCUSDT", "ETHUSDT"]
    assert scanner.get_universe_symbols("micro_live_usdt_2") == ["BTCUSDT", "ETHUSDT"]
