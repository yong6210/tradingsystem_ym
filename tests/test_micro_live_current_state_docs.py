from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def test_micro_live_current_state_matches_env_example_contract() -> None:
    env = _env_example()
    doc = (ROOT / "docs/MICRO_LIVE_CURRENT_STATE.md").read_text(encoding="utf-8")

    assert f"- execution mode: `{env['AUTO_TRADING_EXECUTION_MODE']}`" in doc
    assert f"- strategy family: `{env['AUTO_TRADING_MICRO_LIVE_ALLOWED_FAMILIES']}`" in doc
    assert f"- entry model: `{env['AUTO_TRADING_MICRO_LIVE_ALLOWED_ENTRY_MODELS']}`" in doc

    for symbol in _csv(env["AUTO_TRADING_MICRO_LIVE_ALLOWED_SYMBOLS"]):
        assert f"`{symbol}`" in doc

    for session in _csv(env["AUTO_TRADING_MICRO_LIVE_ALLOWED_SESSIONS"]):
        assert f"`{session}`" in doc


def test_micro_live_current_state_matches_env_example_pacing() -> None:
    env = _env_example()
    doc = (ROOT / "docs/MICRO_LIVE_CURRENT_STATE.md").read_text(encoding="utf-8")
    keys = [
        "AUTO_TRADING_MICRO_LIVE_MAX_CONCURRENT_POSITIONS",
        "AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES",
        "AUTO_TRADING_LIVE_FAMILY_CLUSTER_WINDOW_MINUTES",
        "AUTO_TRADING_LIVE_MAX_SAME_FAMILY_ENTRIES_PER_WINDOW",
        "AUTO_TRADING_LIVE_MAX_SAME_FAMILY_DIRECTION_EXPOSURES",
        "AUTO_TRADING_LIVE_RECENT_LOSS_COOLDOWN_MINUTES",
        "AUTO_TRADING_LIVE_RECENT_LOSS_TRIGGER_COUNT",
        "SESSION_IMPULSE_RETEST_SATURDAY_RISK_MULTIPLIER",
    ]

    for key in keys:
        assert f"`{key}={env[key]}`" in doc


def test_current_state_doc_is_linked_from_operator_docs() -> None:
    target = "docs/MICRO_LIVE_CURRENT_STATE.md"
    for relative_path in [
        "README.md",
        "docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md",
        "docs/AUTO_TRADING_OPERATING_RUNBOOK.md",
    ]:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert target in text


def test_operator_docs_do_not_describe_legacy_btc_route_as_current() -> None:
    forbidden = [
        "현재 live 계약은 `BTCUSDC + sweep_reversal + LIMIT`",
        "live contract: `BTCUSDC + sweep_reversal + LIMIT`",
        "Current Live Canary Setup",
        "1 concurrent position",
        "limit_only post-patch",
    ]
    for relative_path in [
        "README.md",
        "docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md",
        "docs/AUTO_TRADING_OPERATING_RUNBOOK.md",
    ]:
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text
