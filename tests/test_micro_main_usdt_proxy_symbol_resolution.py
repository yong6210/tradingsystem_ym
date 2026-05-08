from __future__ import annotations

from scripts.run_micro_main_usdt_proxy_backtest import canonical_symbol_for_proxy


def test_canonical_symbol_for_proxy_uses_known_mapping() -> None:
    assert canonical_symbol_for_proxy("BTCUSDT") == "BTCUSDC"


def test_canonical_symbol_for_proxy_falls_back_for_unseen_symbols() -> None:
    assert canonical_symbol_for_proxy("DOGEUSDT") == "DOGEUSDC"
    assert canonical_symbol_for_proxy("MKRUSDT") == "MKRUSDC"


def test_canonical_symbol_for_proxy_rejects_invalid_symbol() -> None:
    assert canonical_symbol_for_proxy("") is None
    assert canonical_symbol_for_proxy("NQ1!") is None
