from app.services.micro_main_universe_policy import (
    build_micro_main_universe_policy_snapshot,
    micro_main_universe_entry,
)


def test_micro_main_universe_policy_snapshot_shapes_core_and_secondary_lists() -> None:
    snapshot = build_micro_main_universe_policy_snapshot()
    assert snapshot["family"] == "session_impulse_retest"
    assert snapshot["core_symbols"] == [
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
    ]
    assert snapshot["secondary_symbols"] == [
        "SUIUSDC",
        "AAVEUSDC",
        "HBARUSDC",
    ]
    assert snapshot["partial_activation_priority"][0] == "BTCUSDC"
    assert snapshot["partial_activation_priority"][-1] == "HBARUSDC"


def test_micro_main_universe_entry_returns_expected_risk_multiplier() -> None:
    btc = micro_main_universe_entry("BTCUSDC")
    link = micro_main_universe_entry("LINKUSDC")
    xrp = micro_main_universe_entry("XRPUSDC")
    avax = micro_main_universe_entry("AVAXUSDC")
    sui = micro_main_universe_entry("SUIUSDC")
    hbar = micro_main_universe_entry("HBARUSDC")
    assert btc is not None
    assert link is not None
    assert xrp is not None
    assert avax is not None
    assert sui is not None
    assert hbar is not None
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
