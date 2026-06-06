#!/usr/bin/env python3
"""Audit v6 tiny-canary risk caps without touching order submission paths."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.run_market_state_rotation_v6_evidence_cycle import (
    DEFAULT_CANARY_RISK_CAPS_PATH,
    _json_default,
    load_canary_risk_caps_config,
)


DEFAULT_REPORT_DIR = "reports/validation/diagnostics/market_state_rotation_v6_canary_risk_caps_audit"
REPORT_NAME = "market_state_rotation_v6_canary_risk_caps_audit.json"
TEMPLATE_NAME = "market_state_rotation_v6_canary_risk_caps.template.json"


ERROR_ACTIONS = {
    "canary_risk_caps_json_required": "copy_the_disabled_template_to_target_path_then_edit_values_after_operator_review",
    "canary_risk_caps_json_disabled": "set_enabled_true_only_after_operator_review",
    "max_notional_usdt_must_be_positive": "set_tiny_positive_max_notional_usdt",
    "max_daily_loss_usdt_must_be_positive": "set_tiny_positive_daily_loss_cap",
    "max_leverage_must_be_between_0_and_10": "set_max_leverage_between_0_and_10",
    "scope_symbol_must_be_BTCUSDT": "keep_scope_symbol_BTCUSDT",
    "strategy_family_must_be_market_state_rotation_v6": "keep_strategy_family_market_state_rotation_v6",
    "max_daily_order_count_must_be_between_1_and_3": "set_max_daily_order_count_between_1_and_3",
    "max_consecutive_loss_count_must_be_between_1_and_2": "set_max_consecutive_loss_count_between_1_and_2",
    "kill_switch_required_must_be_true": "set_kill_switch_required_true",
    "reduce_only_exit_required_must_be_true": "set_reduce_only_exit_required_true",
    "operator_acknowledged_no_auto_live_order_must_be_true": "acknowledge_that_this_config_does_not_enable_auto_live_orders",
    "max_daily_loss_usdt_must_be_lte_50pct_of_max_notional": "lower_daily_loss_cap_to_lte_50pct_of_notional",
    "max_leverage_must_not_exceed_nanyotti_observed_cap_10x": "keep_leverage_lte_10x",
}


def _resolve(path: str | Path) -> Path:
    raw = Path(path)
    return raw if raw.is_absolute() else ROOT_DIR / raw


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR))
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _template_payload() -> dict[str, Any]:
    return {
        "enabled": False,
        "scope_symbol": "BTCUSDT",
        "strategy_family": "market_state_rotation_v6",
        "max_notional_usdt": 0.0,
        "max_leverage": 10.0,
        "max_daily_loss_usdt": 0.0,
        "max_daily_order_count": 1,
        "max_consecutive_loss_count": 1,
        "kill_switch_required": True,
        "reduce_only_exit_required": True,
        "operator_acknowledged_no_auto_live_order": False,
        "notes": (
            "Copy this template to market_state_rotation_v6_canary_risk_caps.json only after operator review. "
            "Set enabled=true and operator_acknowledged_no_auto_live_order=true only after reviewing the launch report. "
            "This audit and the evidence cycle never send live orders."
        ),
    }


def _operator_actions(errors: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "error": error,
            "action": ERROR_ACTIONS.get(error, "inspect_canary_risk_caps_json_and_rerun_audit"),
        }
        for error in errors
    ]


def build_canary_risk_caps_audit(
    *,
    canary_risk_caps_path: Path,
    cli_max_notional_usdt: float = 0.0,
    cli_max_leverage: float = 10.0,
    cli_max_daily_loss_usdt: float = 0.0,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = (generated_at or datetime.now(UTC)).astimezone(UTC)
    config = load_canary_risk_caps_config(
        path=canary_risk_caps_path,
        cli_max_notional_usdt=float(cli_max_notional_usdt),
        cli_max_leverage=float(cli_max_leverage),
        cli_max_daily_loss_usdt=float(cli_max_daily_loss_usdt),
    )
    errors = list(config.get("errors") or [])
    if config.get("configured") is True:
        overall_status = "PASS"
    elif config.get("status") in {"missing_optional_config_file", "disabled"}:
        overall_status = "INCOMPLETE"
    else:
        overall_status = "FAIL"
    target_path = _resolve(DEFAULT_CANARY_RISK_CAPS_PATH)
    template_path = target_path.with_name(TEMPLATE_NAME)
    return {
        "created_at": generated_at.isoformat(),
        "overall_status": overall_status,
        "canary_risk_caps_path": _display_path(canary_risk_caps_path),
        "template_path": _display_path(template_path),
        "target_config_path": _display_path(target_path),
        "config": config,
        "operator_actions": _operator_actions(errors),
        "ready_for_operator_review": config.get("configured") is True,
        "safe_template_copy_command": f"cp {_display_path(template_path)} {_display_path(target_path)}",
        "evidence_cycle_validation_command": (
            ".venv/bin/python scripts/run_market_state_rotation_v6_evidence_cycle.py "
            "--quote-samples-per-tick 0 "
            f"--canary-risk-caps-json {_display_path(canary_risk_caps_path)} "
            "--report-dir reports/validation/diagnostics/market_state_rotation_v6_canary_risk_caps_review"
        ),
        "order_submission_allowed": False,
        "no_live_order_sent": True,
    }


def _markdown(report: dict[str, Any]) -> str:
    config = dict(report.get("config") or {})
    effective = dict(config.get("effective") or {})
    lines = [
        "# Market State Rotation V6 Canary Risk Caps Audit",
        "",
        f"- Status: `{report.get('overall_status')}`",
        f"- Config status: `{config.get('status')}`",
        f"- Configured: `{config.get('configured')}`",
        f"- Path: `{report.get('canary_risk_caps_path')}`",
        f"- max_notional_usdt: `{effective.get('max_notional_usdt')}`",
        f"- max_leverage: `{effective.get('max_leverage')}`",
        f"- max_daily_loss_usdt: `{effective.get('max_daily_loss_usdt')}`",
        f"- Errors: `{', '.join(config.get('errors') or [])}`",
        f"- no_live_order_sent: `{report.get('no_live_order_sent')}`",
        "",
        "## Operator Actions",
        "",
    ]
    for item in list(report.get("operator_actions") or []):
        lines.append(f"- `{item.get('error')}` -> {item.get('action')}")
    lines.extend(
        [
            "",
            "## Commands",
            "",
            f"- template_copy: `{report.get('safe_template_copy_command')}`",
            f"- evidence_validation: `{report.get('evidence_cycle_validation_command')}`",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit v6 tiny-canary risk caps without sending orders.")
    parser.add_argument("--canary-risk-caps-json", default=DEFAULT_CANARY_RISK_CAPS_PATH)
    parser.add_argument("--canary-max-notional-usdt", type=float, default=0.0)
    parser.add_argument("--canary-max-leverage", type=float, default=10.0)
    parser.add_argument("--canary-max-daily-loss-usdt", type=float, default=0.0)
    parser.add_argument("--report-dir", default=DEFAULT_REPORT_DIR)
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--write-template", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    caps_path = _resolve(args.canary_risk_caps_json)
    if args.write_template:
        template_path = _resolve(DEFAULT_CANARY_RISK_CAPS_PATH).with_name(TEMPLATE_NAME)
        _write_json(template_path, _template_payload())
    report = build_canary_risk_caps_audit(
        canary_risk_caps_path=caps_path,
        cli_max_notional_usdt=float(args.canary_max_notional_usdt),
        cli_max_leverage=float(args.canary_max_leverage),
        cli_max_daily_loss_usdt=float(args.canary_max_daily_loss_usdt),
    )
    if args.write_report:
        report_dir = _resolve(args.report_dir)
        json_path = report_dir / REPORT_NAME
        md_path = report_dir / "market_state_rotation_v6_canary_risk_caps_audit.md"
        _write_json(json_path, report)
        _write_text(md_path, _markdown(report) + "\n")
        print(f"wrote {_display_path(json_path)}")
        print(f"wrote {_display_path(md_path)}")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if report["overall_status"] in {"PASS", "INCOMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
