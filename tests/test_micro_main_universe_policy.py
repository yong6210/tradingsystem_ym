from app.services.micro_main_universe_policy import (
    build_micro_main_universe_policy_snapshot,
    micro_main_universe_entry,
)


def test_micro_main_universe_policy_snapshot_shapes_core_and_secondary_lists() -> None:
    snapshot = build_micro_main_universe_policy_snapshot()
    assert snapshot["family"] == "session_impulse_retest"
    expected_usdc_core = [
        "BTCUSDC",
        "ETHUSDC",
        "SOLUSDC",
        "LINKUSDC",
        "BNBUSDC",
        "XRPUSDC",
        "ADAUSDC",
        "AVAXUSDC",
        "BCHUSDC",
        "LTCUSDC",
        "NEARUSDC",
        "1000PEPEUSDC",
        "ARBUSDC",
        "1000SHIBUSDC",
        "FILUSDC",
        "DOGEUSDC",
    ]
    expected_usdt_core = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "BNBUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "AVAXUSDT",
        "LINKUSDT",
        "DOGEUSDT",
        "BCHUSDT",
        "LTCUSDT",
        "NEARUSDT",
        "FILUSDT",
        "DOTUSDT",
        "ATOMUSDT",
        "ETCUSDT",
        "HBARUSDT",
        "AAVEUSDT",
        "UNIUSDT",
        "SUIUSDT",
        "INJUSDT",
        "FETUSDT",
        "ARBUSDT",
        "APTUSDT",
        "RUNEUSDT",
        "PENDLEUSDT",
        "ICPUSDT",
        "XLMUSDT",
        "ZECUSDT",
        "QNTUSDT",
        "DASHUSDT",
    ]
    assert all(symbol in snapshot["core_symbols"] for symbol in expected_usdc_core)
    assert all(symbol in snapshot["core_symbols"] for symbol in expected_usdt_core)
    assert snapshot["secondary_symbols"] == [
        "SUIUSDC",
        "AAVEUSDC",
        "HBARUSDC",
        "ZECUSDC",
        "UNIUSDC",
    ]
    assert snapshot["partial_activation_priority"][0] == "BTCUSDC"
    assert "UNIUSDC" in snapshot["partial_activation_priority"]
    assert snapshot["partial_activation_priority"][-1] == "DASHUSDT"


def test_micro_main_universe_entry_returns_expected_risk_multiplier() -> None:
    btc = micro_main_universe_entry("BTCUSDC")
    link = micro_main_universe_entry("LINKUSDC")
    xrp = micro_main_universe_entry("XRPUSDC")
    avax = micro_main_universe_entry("AVAXUSDC")
    sui = micro_main_universe_entry("SUIUSDC")
    hbar = micro_main_universe_entry("HBARUSDC")
    zec = micro_main_universe_entry("ZECUSDC")
    uni = micro_main_universe_entry("UNIUSDC")
    pepe = micro_main_universe_entry("1000PEPEUSDC")
    doge = micro_main_universe_entry("DOGEUSDC")
    eth_usdt = micro_main_universe_entry("ETHUSDT")
    dash_usdt = micro_main_universe_entry("DASHUSDT")
    assert btc is not None
    assert link is not None
    assert xrp is not None
    assert avax is not None
    assert sui is not None
    assert hbar is not None
    assert zec is not None
    assert uni is not None
    assert pepe is not None
    assert doge is not None
    assert eth_usdt is not None
    assert dash_usdt is not None
    assert btc["risk_multiplier"] == 0.9
    assert link["tier"] == "core"
    assert link["risk_multiplier"] == 0.85
    assert xrp["risk_multiplier"] == 0.6
    assert avax["tier"] == "core"
    assert avax["risk_multiplier"] == 0.35
    assert sui["tier"] == "secondary"
    assert sui["risk_multiplier"] == 0.45
    assert hbar["tier"] == "secondary"
    assert hbar["risk_multiplier"] == 0.45
    assert zec["tier"] == "secondary"
    assert zec["risk_multiplier"] == 0.35
    assert uni["tier"] == "secondary"
    assert uni["risk_multiplier"] == 0.4
    assert pepe["tier"] == "core"
    assert pepe["risk_multiplier"] == 0.35
    assert doge["tier"] == "core"
    assert doge["risk_multiplier"] == 0.45
    assert eth_usdt["tier"] == "core"
    assert eth_usdt["risk_multiplier"] == 1.0
    assert dash_usdt["tier"] == "core"
    assert dash_usdt["risk_multiplier"] == 0.3
