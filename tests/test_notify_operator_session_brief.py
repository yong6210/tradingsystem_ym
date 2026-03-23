from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from scripts import notify_operator_session_brief


def _fake_brief() -> dict:
    return {
        "symbol": "BTCUSDC",
        "universe": "usdc_perp_top30",
        "brief_status": "DEPLOYMENT_REVIEW_REQUIRED",
        "headline": "headline",
        "report_path": "reports/operations/operator_session_briefs/brief.md",
        "next_steps": ["step-a"],
        "snapshot": {
            "report_path": "reports/operations/operator_surface_divergence/snapshot.md",
            "deployment_alignment": "DIVERGED",
            "playbook_alignment": "DIVERGED",
            "dashboard_summary": {
                "top_operator_action": "continue_candidate_review_under_portfolio_caps",
                "deployment_go_no_go": "GO",
                "playbook_action": "continue_candidate_review_under_portfolio_caps",
            },
            "validation_summary": {
                "deployment_go_no_go": "NO_GO",
                "playbook_action": "resolve_selected_trial_lineage_before_rollout",
            },
            "checklist_summary": {
                "deployment_go_no_go": "NO_GO",
                "playbook_action": "resolve_selected_trial_lineage_before_rollout",
            },
            "signal_funnel_snapshot": {
                "research_action": "run_shadow_exit_timing_review",
                "top_family_bottleneck": "legacy_zone_plan",
                "top_session_bottleneck": "preferred_live_window",
            },
            "operator_ui_sections": {
                "all_present": True,
            },
        },
    }


def test_main_blocks_live_send_without_allow_flag(monkeypatch, tmp_path: Path, capsys) -> None:
    state_file = tmp_path / "state.json"
    latest_run_file = tmp_path / "latest.json"
    args = Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=7,
        portfolio_limit=5,
        intent_limit=5,
        reconcile_limit=5,
        state_file=str(state_file),
        latest_run_file=str(latest_run_file),
        channel="system",
        brief_mode="shift-start",
        webhook_url="",
        allow_live_send=False,
        force_send=True,
        dry_run=False,
    )
    writes: list[Path] = []

    monkeypatch.setattr(notify_operator_session_brief, "parse_args", lambda: args)
    monkeypatch.setattr(notify_operator_session_brief, "_run_brief", lambda _args: _fake_brief())
    monkeypatch.setattr(notify_operator_session_brief, "_read_json", lambda path: None)

    def _write(path: Path, payload: dict) -> None:
        writes.append(path)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(notify_operator_session_brief, "_write_json", _write)

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ANN001
            raise AssertionError("dispatcher should not be created when live send is not allowed")

    monkeypatch.setattr(notify_operator_session_brief, "NotificationDispatcher", _Dispatcher)

    assert notify_operator_session_brief.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["allow_live_send"] is False
    assert payload["delivery"]["reason"] == "live_send_not_allowed"
    assert payload["notified"] is False
    assert "message" in payload
    assert latest_run_file in writes
    assert state_file not in writes


def test_main_dispatches_when_allow_live_send(monkeypatch, tmp_path: Path, capsys) -> None:
    state_file = tmp_path / "state.json"
    latest_run_file = tmp_path / "latest.json"
    args = Namespace(
        symbol="BTCUSDC",
        universe="usdc_perp_top30",
        days=7,
        portfolio_limit=5,
        intent_limit=5,
        reconcile_limit=5,
        state_file=str(state_file),
        latest_run_file=str(latest_run_file),
        channel="discord",
        brief_mode="shift-end",
        webhook_url="https://discord.example/webhook",
        allow_live_send=True,
        force_send=True,
        dry_run=False,
    )
    writes: list[Path] = []
    dispatch_calls: list[dict] = []

    monkeypatch.setattr(notify_operator_session_brief, "parse_args", lambda: args)
    monkeypatch.setattr(notify_operator_session_brief, "_run_brief", lambda _args: _fake_brief())
    monkeypatch.setattr(notify_operator_session_brief, "_read_json", lambda path: None)

    def _write(path: Path, payload: dict) -> None:
        writes.append(path)
        path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(notify_operator_session_brief, "_write_json", _write)

    class _Settings:
        alert_discord_webhook_url = ""

    monkeypatch.setattr(notify_operator_session_brief, "get_settings", lambda: _Settings())

    class _Dispatcher:
        def __init__(self, settings):  # noqa: ANN001
            self.settings = settings

        def dispatch(self, *, channel, alert_type, symbol, payload):  # noqa: ANN001
            dispatch_calls.append(
                {"channel": channel, "alert_type": alert_type, "symbol": symbol, "payload": payload}
            )
            return {"channel": channel, "delivered": True, "skipped": False, "reason": "delivered"}

    monkeypatch.setattr(notify_operator_session_brief, "NotificationDispatcher", _Dispatcher)

    assert notify_operator_session_brief.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["allow_live_send"] is True
    assert payload["notified"] is True
    assert payload["delivery"]["reason"] == "delivered"
    assert dispatch_calls[0]["channel"] == "discord"
    assert dispatch_calls[0]["symbol"] == "BTCUSDC"
    assert state_file in writes
    assert latest_run_file in writes

