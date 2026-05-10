from fastapi.testclient import TestClient

from app.main import app
from app.core.config import get_settings
from app.services.health_check import ReadySnapshot
from app.services.notification_dispatcher import NotificationDispatcher


client = TestClient(app)


def test_health_and_bootstrap_flow(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "alert_telegram_bot_token", "")
    monkeypatch.setattr(settings, "alert_telegram_chat_id", "")
    monkeypatch.setattr(settings, "alert_discord_webhook_url", "")
    monkeypatch.setattr(settings, "alert_push_webhook_url", "")
    NotificationDispatcher.reset_circuit_state()

    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["status"] == "ok"

    monkeypatch.setattr(
        "app.api.routes.HealthCheckService.evaluate",
        lambda self: ReadySnapshot(
            status="ready",
            checks={"db": True, "binance_rest": True, "event_backend": True},
            details={"db": "ok", "binance_rest": "ok", "event_backend": "ok"},
        ),
    )
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    ready_payload = ready.json()
    assert ready_payload["status"] == "ready"
    assert ready_payload["checks"]["db"] is True
    assert ready_payload["checks"]["binance_rest"] is True
    assert ready_payload["checks"]["event_backend"] is True

    boot = client.post("/internal/demo/bootstrap?symbol=BTCUSDC")
    assert boot.status_code == 200
    assert boot.json()["status"] == "bootstrapped"

    zones = client.get("/zones?symbol=BTCUSDC&tf=15m")
    assert zones.status_code == 200
    assert isinstance(zones.json(), list)

    subscribe = client.post(
        "/alerts/subscribe",
        json={
            "symbol": "BTCUSDC",
            "channel": "push",
            "type": "near",
            "payload": {
                "deployment_go_no_go": "MANUAL_REVIEW",
                "deployment_code": "manual_review_subscribe_contract",
                "deployment_message": "MANUAL_REVIEW: verify subscribed alert contract before rollout.",
                "approval_playbook_go_no_go": "MANUAL_REVIEW",
                "approval_playbook_code": "manual_review_subscribe_contract",
                "approval_playbook_action": "review_subscribed_alert_contract",
                "approval_playbook_message": "MANUAL_REVIEW: review subscribed alert contract before rollout.",
            },
        },
    )
    assert subscribe.status_code == 200
    subscribe_payload = subscribe.json()
    assert subscribe_payload["status"] == "subscribed"
    assert subscribe_payload["deployment_go_no_go"] == "MANUAL_REVIEW"
    assert subscribe_payload["deployment_code"] == "manual_review_subscribe_contract"
    assert subscribe_payload["approval_playbook_go_no_go"] == "MANUAL_REVIEW"
    assert subscribe_payload["approval_playbook_code"] == "manual_review_subscribe_contract"
    assert subscribe_payload["approval_playbook_action"] == "review_subscribed_alert_contract"
    assert subscribe_payload["approval_strip_summary"]["approve_value"] == "manual review first"
    assert subscribe_payload["approval_strip_summary"]["act_value"] == "review_subscribed_alert_contract"

    plans = client.get("/plans/top?symbol=BTCUSDC&tf=5m&limit=5")
    assert plans.status_code == 200
    plans_payload = plans.json()
    assert isinstance(plans_payload, list)
    if plans_payload:
        assert "strategy_family" in plans_payload[0]
        assert "expected_win_prob" in plans_payload[0]
        assert "expected_ev_r" in plans_payload[0]
        assert "expected_summary" in plans_payload[0]
        assert "strategy_scorecard" in plans_payload[0]["validity"]
        assert "strategy_mode" in plans_payload[0]["validity"]
        assert "strategy_sizing" in plans_payload[0]["validity"]
        assert "recommended_risk_r" in plans_payload[0]["validity"]

    indicator_summary = client.get("/indicators/summary?symbol=BTCUSDC&refresh=false&plan_limit=3&zone_limit=5")
    assert indicator_summary.status_code == 200
    indicator_summary_payload = indicator_summary.json()
    assert "available" in indicator_summary_payload
    assert "headline" in indicator_summary_payload
    assert "readable_lines" in indicator_summary_payload
    assert "context" in indicator_summary_payload
    assert "operator_summary" in indicator_summary_payload
    assert "top_zones" in indicator_summary_payload
    assert "trade_now_status" in indicator_summary_payload["operator_summary"]
    assert "authority_source" in indicator_summary_payload["operator_summary"]
    if indicator_summary_payload["available"]:
        assert "regime_label" in indicator_summary_payload["context"]
        assert "transition_state" in indicator_summary_payload["context"]

    indicator_chart = client.get("/indicators/chart?symbol=BTCUSDC&refresh=false&plan_limit=5&zone_limit=8")
    assert indicator_chart.status_code == 200
    indicator_chart_payload = indicator_chart.json()
    assert "available" in indicator_chart_payload
    assert "price_panel" in indicator_chart_payload
    assert "indicator_panel" in indicator_chart_payload
    assert "operator_summary" in indicator_chart_payload
    assert "zones" in indicator_chart_payload
    assert "plans" in indicator_chart_payload
    if indicator_chart_payload["available"]:
        assert "regime_label" in indicator_chart_payload["indicator_panel"]
        assert "transition_score" in indicator_chart_payload["indicator_panel"]

    indicator_pine = client.get("/indicators/pine?symbol=BTCUSDC&refresh=false&plan_limit=5&zone_limit=8")
    assert indicator_pine.status_code == 200
    indicator_pine_payload = indicator_pine.json()
    assert "available" in indicator_pine_payload
    assert "overlay" in indicator_pine_payload
    assert "panels" in indicator_pine_payload
    assert "operator_summary" in indicator_pine_payload
    assert "signals" in indicator_pine_payload
    if indicator_pine_payload["available"]:
        assert "plot_lines" in indicator_pine_payload["overlay"]
        assert "zone_boxes" in indicator_pine_payload["overlay"]

    indicator_pine_script = client.get("/indicators/pine-script")
    assert indicator_pine_script.status_code == 200
    assert indicator_pine_script.text.startswith("//@version=6")
    assert "Trading Engine v1 Mirror" in indicator_pine_script.text
    assert "alertcondition(" in indicator_pine_script.text
    assert "Dashboard position" in indicator_pine_script.text
    assert "Chart-side best setup" in indicator_pine_script.text
    assert "Chart-side operator priority" in indicator_pine_script.text
    assert "Chart-side operator priority, confirm with scanner/ops" in indicator_pine_script.text
    assert "Mirror entry" in indicator_pine_script.text
    assert "Mirror stop" in indicator_pine_script.text
    assert "Authority: mirror only, check scanner/ops; server wins" in indicator_pine_script.text
    assert "math.tanh" not in indicator_pine_script.text
    assert "ta.sum" not in indicator_pine_script.text
    assert 'text=activeGrade' not in indicator_pine_script.text

    if plans_payload:
        preview = client.post("/execution/plans/preview", json={"plan_id": plans_payload[0]["plan_id"]})
        assert preview.status_code == 200
        preview_payload = preview.json()
        assert preview_payload["plan_id"] == plans_payload[0]["plan_id"]
        assert "expected_summary" in preview_payload
        assert "context_snapshot" in preview_payload
        assert "entry_type" in preview_payload

        approval = client.post("/execution/approve-plan", json={"plan_id": plans_payload[0]["plan_id"]})
        assert approval.status_code == 200
        approval_payload = approval.json()
        assert approval_payload["plan_id"] == plans_payload[0]["plan_id"]
        assert "approval_state" in approval_payload
        assert "approval_reasons" in approval_payload
        assert "playbook_go_no_go" in approval_payload

    execution_dashboard = client.get(
        "/execution/operator-dashboard?universe=usdc_perp_top30&portfolio_limit=5&intent_limit=5&reconcile_limit=5&days=7"
    )
    assert execution_dashboard.status_code == 200
    execution_dashboard_payload = execution_dashboard.json()
    assert execution_dashboard_payload["report_window_days"] == 7
    assert "execution_mode" in execution_dashboard_payload
    assert "new_entries_allowed" in execution_dashboard_payload
    assert "recent_intents" in execution_dashboard_payload
    assert "open_orders" in execution_dashboard_payload
    assert "open_positions" in execution_dashboard_payload
    assert "recent_reconciliation_summary" in execution_dashboard_payload
    assert "portfolio_summary" in execution_dashboard_payload
    assert "approval_strip_summary" in execution_dashboard_payload
    assert "approve_value" in execution_dashboard_payload["approval_strip_summary"]
    assert "align_value" in execution_dashboard_payload["approval_strip_summary"]
    assert "act_value" in execution_dashboard_payload["approval_strip_summary"]
    assert "signal_funnel" in execution_dashboard_payload
    assert "live_candidate_promotion_readiness" in execution_dashboard_payload["signal_funnel"]
    assert "live_candidate_promotion_readiness_global" in execution_dashboard_payload["signal_funnel"]
    assert execution_dashboard_payload["signal_funnel"]["live_candidate_promotion_readiness_global"]["scope"] == "global_all_symbols"
    assert "family_pass_rates" in execution_dashboard_payload["signal_funnel"]
    assert "regime_pass_rates" in execution_dashboard_payload["signal_funnel"]
    assert "session_pass_rates" in execution_dashboard_payload["signal_funnel"]
    assert "blocked_gate_group_counts" in execution_dashboard_payload["signal_funnel"]
    assert "blocked_gate_groups" in execution_dashboard_payload["signal_funnel"]
    assert "current_entry_gate_group" in execution_dashboard_payload["signal_funnel"]
    assert "hard_block_summary" in execution_dashboard_payload["signal_funnel"]
    assert "softening_candidate_summary" in execution_dashboard_payload["signal_funnel"]
    assert "rollout_block_summary" in execution_dashboard_payload["signal_funnel"]
    assert "alpha_research_summary" in execution_dashboard_payload["signal_funnel"]
    assert "alpha_research_focus_alignment" in execution_dashboard_payload["signal_funnel"]
    assert "alpha_research_evidence_summary" in execution_dashboard_payload["signal_funnel"]
    assert "alpha_research_softening_review" in execution_dashboard_payload["signal_funnel"]
    assert "alpha_research_promotion_watchlist" in execution_dashboard_payload["signal_funnel"]
    assert "alpha_research_recommended_action" in execution_dashboard_payload["signal_funnel"]
    assert "alpha_research_top_shadow_experiment" in execution_dashboard_payload["signal_funnel"]
    assert "score_to_outcome_funnel" in execution_dashboard_payload["signal_funnel"]
    assert "execution_degradation_advisory" in execution_dashboard_payload["signal_funnel"]
    assert "family_execution_degradation_advisory" in execution_dashboard_payload["signal_funnel"]
    assert "mode_advisory" in execution_dashboard_payload["signal_funnel"]
    assert "operator_action_priority" in execution_dashboard_payload["signal_funnel"]
    assert "priority_source" in execution_dashboard_payload["signal_funnel"]["operator_action_priority"]
    assert "action_family" in execution_dashboard_payload["signal_funnel"]["operator_action_priority"]
    assert "top_action_followup_command" in execution_dashboard_payload["signal_funnel"]["operator_action_priority"]
    assert "capture_context" in execution_dashboard_payload["signal_funnel"]["operator_action_priority"]
    assert "experiment_context" in execution_dashboard_payload["signal_funnel"]["operator_action_priority"]
    assert "outcome_control_trace" in execution_dashboard_payload["signal_funnel"]
    assert "edge_experiment_review" in execution_dashboard_payload["signal_funnel"]
    assert "edge_evolution_rule" in execution_dashboard_payload["signal_funnel"]
    assert "review_followup_ledger" in execution_dashboard_payload["signal_funnel"]
    assert "rollout_recommendation" in execution_dashboard_payload["signal_funnel"]
    assert "strategy_lifecycle" in execution_dashboard_payload["signal_funnel"]
    assert "promotion_governance" in execution_dashboard_payload["signal_funnel"]
    assert "promotion_review_queue" in execution_dashboard_payload["signal_funnel"]
    assert "promotion_remediation_queue" in execution_dashboard_payload["signal_funnel"]
    assert "promotion_clearance_tracker" in execution_dashboard_payload["signal_funnel"]
    assert "promotion_reopen_queue" in execution_dashboard_payload["signal_funnel"]
    assert "promotion_decision_brief" in execution_dashboard_payload["signal_funnel"]
    assert "auto_promotion_rollout_execution" in execution_dashboard_payload["signal_funnel"]
    assert "promotion_lifecycle_history" in execution_dashboard_payload["signal_funnel"]
    assert "research_promotion_operating_loop" in execution_dashboard_payload["signal_funnel"]
    assert "multi_strategy_ab_expansion" in execution_dashboard_payload["signal_funnel"]
    assert "b_continuation_activation" in execution_dashboard_payload["signal_funnel"]
    assert "execution_friction_measurement" in execution_dashboard_payload["signal_funnel"]
    assert "forward_stress_regime_validation" in execution_dashboard_payload["signal_funnel"]
    assert "kill_condition_automation" in execution_dashboard_payload["signal_funnel"]
    assert "b_continuation_edge_validation" in execution_dashboard_payload["signal_funnel"]
    assert "strategy_cluster_balance" in execution_dashboard_payload["signal_funnel"]
    assert "a_strategy_post_cost_edge_validation" in execution_dashboard_payload["signal_funnel"]
    assert "positive_evidence_expansion" in execution_dashboard_payload["signal_funnel"]
    assert "outcome_bucket_granularity" in execution_dashboard_payload["signal_funnel"]
    assert "opportunity_capture" in execution_dashboard_payload["signal_funnel"]
    assert "capital_allocator" in execution_dashboard_payload["signal_funnel"]
    assert "quality_softening_priorities" in execution_dashboard_payload["signal_funnel"]
    assert "family_bottlenecks" in execution_dashboard_payload["signal_funnel"]
    assert "regime_bottlenecks" in execution_dashboard_payload["signal_funnel"]
    assert "session_bottlenecks" in execution_dashboard_payload["signal_funnel"]
    assert "accepted_candidates" in execution_dashboard_payload["portfolio_summary"]
    assert "blocked_candidates" in execution_dashboard_payload["portfolio_summary"]
    if execution_dashboard_payload["portfolio_summary"]["accepted_candidates"]:
        assert "outcome_bias" in execution_dashboard_payload["portfolio_summary"]["accepted_candidates"][0]
        assert "capital_allocator" in execution_dashboard_payload["portfolio_summary"]["accepted_candidates"][0]
        assert "allocated_risk_r" in execution_dashboard_payload["portfolio_summary"]["accepted_candidates"][0]
        assert "strategy_sizing" in execution_dashboard_payload["portfolio_summary"]["accepted_candidates"][0]
    if execution_dashboard_payload["portfolio_summary"]["blocked_candidates"]:
        assert "outcome_bias" in execution_dashboard_payload["portfolio_summary"]["blocked_candidates"][0]
        assert "capital_allocator" in execution_dashboard_payload["portfolio_summary"]["blocked_candidates"][0]
        assert "allocated_risk_r" in execution_dashboard_payload["portfolio_summary"]["blocked_candidates"][0]
        assert "strategy_sizing" in execution_dashboard_payload["portfolio_summary"]["blocked_candidates"][0]
    assert "alert_summary" in execution_dashboard_payload

    execution_operator_ui = client.get("/execution/operator-ui?symbol=BTCUSDC&universe=usdc_perp_top30&days=7")
    assert execution_operator_ui.status_code == 200
    assert execution_operator_ui.headers["content-type"].startswith("text/html")
    assert "실행 운영 화면" in execution_operator_ui.text
    assert "5-Second Operator Kernel" in execution_operator_ui.text
    assert "operator가 5초 안에 money funnel -> outcome attribution -> outcome control -> rollout 순서로 현재 돈 누수와 승인 방향을 읽도록 압축한 kernel view입니다." in execution_operator_ui.text
    assert "Kernel Verdict" in execution_operator_ui.text
    assert "Checklist Trace" in execution_operator_ui.text
    assert "Approval Strip" in execution_operator_ui.text
    assert "Top Opportunity" in execution_operator_ui.text
    assert "Top Blocker" in execution_operator_ui.text
    assert "Current Operating State" in execution_operator_ui.text
    assert "상단 operator surface는 5-Second Operator Kernel을 먼저 보고, 이어서 Approval Strip, Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤" in execution_operator_ui.text
    assert "대표 플랜과 상세 운영 섹션으로 내려가면 됩니다." in execution_operator_ui.text
    assert "kernel verdict가 hold/manual_review/watch면 Top Opportunity / Portfolio Candidate surface는 context-only로 읽습니다." in execution_operator_ui.text
    assert "Deferred Research / Promotion Stack" in execution_operator_ui.text
    assert "kernel verdict가 hold/manual_review/watch라서 promotion/research stack을 기본 접힘 상태로 둡니다." in execution_operator_ui.text
    assert "id=\"top-opportunity-panel\"" in execution_operator_ui.text
    assert "kernel-muted-surface" in execution_operator_ui.text
    assert "kernel-guard-note" in execution_operator_ui.text
    assert "opportunity/candidate surface는 context-only로 읽고 approval/alignment/checklist를 먼저 확인합니다." in execution_operator_ui.text
    assert "opportunity/candidate surface를 정상 우선순위로 읽되 money funnel과 approval alignment를 먼저 확인한 뒤 drilldown으로 내려갑니다." in execution_operator_ui.text
    assert "Family Execution Advisory" in execution_operator_ui.text
    assert "Family Advisory Coverage" in execution_operator_ui.text
    assert "Top Operator Action" in execution_operator_ui.text
    assert "Next Actions" in execution_operator_ui.text
    assert "5-Second Operator Kernel 바로 아래에서 approve -> align -> act 순서로 신규 진입 허용, surface alignment, server-side Top Operator Action을 한 strip으로 압축합니다. policy mutation이 아니라 reading priority입니다." in execution_operator_ui.text
    assert "1. Approve" in execution_operator_ui.text
    assert "2. Align" in execution_operator_ui.text
    assert "3. Act / Top Operator Action" in execution_operator_ui.text
    assert "Approval Strip Detail" in execution_operator_ui.text
    assert "Approval Strip Next Move" in execution_operator_ui.text
    assert "Approval Strip와 Top Opportunity / Top Blocker 다음 순서에서, portfolio/execution/family/mode/research context를 follow-up으로 읽습니다. strong kernel verdict면 expanded operating context는 접힌 상태로 둡니다." in execution_operator_ui.text
    assert "Expanded Operating Context" in execution_operator_ui.text
    assert "kernel verdict가 monitor라서 expanded operating context를 기본 펼침 상태로 둡니다." in execution_operator_ui.text
    assert "kernel verdict가 hold/manual_review/watch라서 expanded operating context는 approve/align/act 확인 전까지 기본 접힘 상태로 둡니다." in execution_operator_ui.text
    assert "A/B Strategy Posture" in execution_operator_ui.text
    assert "A remains anchor인지, B continuation이 research-only인지 guarded activation인지, 현재 mix가 여전히 A 집중인지까지 한 번에 읽습니다." in execution_operator_ui.text
    assert "현재 A/B mix" in execution_operator_ui.text
    assert "Promotion Operating Stack" in execution_operator_ui.text
    assert "승격 review, remediation, clearance, reopen, semi-auto execution, history, research followthrough를 한 번에 읽습니다." in execution_operator_ui.text
    assert "Live Candidate Review" in execution_operator_ui.text
    assert "Global Live Candidate Review" in execution_operator_ui.text
    assert "Global Headline" in execution_operator_ui.text
    assert "Headline Freshness" in execution_operator_ui.text
    assert "Headline Evidence" in execution_operator_ui.text
    assert "Attention Flags" in execution_operator_ui.text
    assert "남은 Guardrail Domain" in execution_operator_ui.text
    assert "최근 Promotion Transition" in execution_operator_ui.text
    assert "Promotion Case Inspector" in execution_operator_ui.text
    assert "현재 headline family의 승격 case를 single-family inspector로 다시 압축해, target posture, write scope, remaining guardrails, next move를 바로 읽습니다." in execution_operator_ui.text
    assert "Next Move" in execution_operator_ui.text
    assert "Remaining Guardrails" in execution_operator_ui.text
    assert "Cleared Guardrails" in execution_operator_ui.text
    assert "Validation / Checklist Review Stack" in execution_operator_ui.text
    assert "validation top-level summary와 checklist item status를 같은 표로 압축해서, raw JSON 없이 operator review stack을 읽습니다." in execution_operator_ui.text
    assert "Validation Approve" in execution_operator_ui.text
    assert "Validation Align" in execution_operator_ui.text
    assert "Validation Act" in execution_operator_ui.text
    assert "Checklist Approve" in execution_operator_ui.text
    assert "Checklist Align" in execution_operator_ui.text
    assert "Checklist Act" in execution_operator_ui.text
    assert "Validation Case Inspector" in execution_operator_ui.text
    assert "현재 symbol validation case를 money funnel, outcome attribution, outcome control, rollout, lifecycle, A/B posture, condition split, capture, allocator 기준으로 다시 압축해 operator가 한 카드로 읽습니다." in execution_operator_ui.text
    assert "Edge Experiment" in execution_operator_ui.text
    assert "Edge Split Focus" in execution_operator_ui.text
    assert "Top Condition Split" in execution_operator_ui.text
    assert "Opportunity Capture" in execution_operator_ui.text
    assert "Next Validation Move" in execution_operator_ui.text
    assert "Operator Reading Order" in execution_operator_ui.text
    assert "Runtime Quality Inspector" in execution_operator_ui.text
    assert "최근 validation alert, retry queue, execution quality, reconciliation health를 한 카드로 압축해 runtime 운영 품질을 빠르게 읽습니다." in execution_operator_ui.text
    assert "Runtime Next Move" in execution_operator_ui.text
    assert "Quality Drift Focus" in execution_operator_ui.text
    assert "Signal Funnel Inspector" in execution_operator_ui.text
    assert "현재 hard gate, softening 후보, rollout block, family/regime/session bottleneck에 money funnel과 outcome attribution까지 묶어서 홈 섹션에서 한 번에 읽도록 압축합니다." in execution_operator_ui.text
    assert "Edge Experiment" in execution_operator_ui.text
    assert "Top Family Bottleneck" in execution_operator_ui.text
    assert "Top Regime Bottleneck" in execution_operator_ui.text
    assert "Top Session Bottleneck" in execution_operator_ui.text
    assert "Current Gate Reason" in execution_operator_ui.text
    assert "Softening Priority Queue" in execution_operator_ui.text
    assert "Alpha Research Inspector" in execution_operator_ui.text
    assert "research backlog, 추천 연구 액션, top shadow experiment, softening review, promotion watchlist를 홈 섹션에서 한 번에 읽도록 압축합니다." in execution_operator_ui.text
    assert "Research Next Move" in execution_operator_ui.text
    assert "Top Shadow Metrics" in execution_operator_ui.text
    assert "Softening Review Queue" in execution_operator_ui.text
    assert "Promotion Watchlist Queue" in execution_operator_ui.text
    assert "Kill Condition Inspector" in execution_operator_ui.text
    assert "stop review verdict, trigger axis, write scope, manual override, 현재 lock state를 홈 섹션에서 한 번에 읽도록 압축합니다." in execution_operator_ui.text
    assert "Stop Review Verdict" in execution_operator_ui.text
    assert "Current Lock State" in execution_operator_ui.text
    assert "Kill Condition Next Move" in execution_operator_ui.text
    assert "Policy / Lock Inspector" in execution_operator_ui.text
    assert "kill switch, close-only, active lock, matching lock, rollout policy를 홈 섹션에서 한 번에 읽도록 압축합니다." in execution_operator_ui.text
    assert "Active Lock Queue" in execution_operator_ui.text
    assert "Rollout Policy Queue" in execution_operator_ui.text
    assert "Policy Next Move" in execution_operator_ui.text
    assert "Intent / Exposure Inspector" in execution_operator_ui.text
    assert "최근 intent 흐름, 열린 주문, 열린 포지션, 현재 익스포저 상태를 홈 섹션에서 한 번에 읽도록 압축합니다." in execution_operator_ui.text
    assert "Recent Intent Queue" in execution_operator_ui.text
    assert "Live Exposure Queue" in execution_operator_ui.text
    assert "Intent Next Move" in execution_operator_ui.text
    assert "Mode / Deployment Inspector" in execution_operator_ui.text
    assert "execution mode, entry gate, dashboard-checklist-validation 배포 상태, rollout recommendation, mode advisory를 홈 섹션에서 한 번에 읽도록 압축합니다." in execution_operator_ui.text
    assert "Entry Gate Reason" in execution_operator_ui.text
    assert "Top Mode Bucket" in execution_operator_ui.text
    assert "Deployment Next Move" in execution_operator_ui.text
    assert "Approval Alignment Inspector" in execution_operator_ui.text
    assert "dashboard, checklist, validation, candidate, operator priority가 같은 배포 방향을 가리키는지 홈 섹션에서 한 번에 읽도록 압축합니다." in execution_operator_ui.text
    assert "Deployment Message Stack" in execution_operator_ui.text
    assert "Approval Next Move" in execution_operator_ui.text
    assert "Data Freshness / Source Inspector" in execution_operator_ui.text
    assert "dashboard, validation, checklist, execution-quality source와 generated_at / report path 상태를 홈 섹션에서 바로 확인합니다." in execution_operator_ui.text
    assert "Source Flow" in execution_operator_ui.text
    assert "Freshness Note" in execution_operator_ui.text
    assert "Portfolio Candidate Drilldown" in execution_operator_ui.text
    assert "accepted / blocked 후보를 raw JSON 없이 읽기 위해, cluster, allocated risk, outcome bias, edge focus, capital allocator, A/B posture를 같은 표로 보여줍니다." in execution_operator_ui.text
    assert "Portfolio Candidate Inspector" in execution_operator_ui.text
    assert "대표 accepted row 1개와 blocked row 1개를 카드로 다시 압축해, risk, allocator, A/B posture, edge focus, session, reaction evidence를 바로 읽습니다." in execution_operator_ui.text
    assert "Representative Accepted Candidate" in execution_operator_ui.text
    assert "Representative Blocked Candidate" in execution_operator_ui.text
    assert "Why This Row Matters" in execution_operator_ui.text
    assert "Edge Focus" in execution_operator_ui.text
    assert "Checklist Evidence Drilldown" in execution_operator_ui.text
    assert "WARN / MANUAL / FAIL 체크를 evidence 중심으로 다시 펼쳐서, raw checklist payload 없이 operator review 포인트를 읽습니다." in execution_operator_ui.text
    assert "Report Navigation" in execution_operator_ui.text
    assert "validation / checklist / execution quality 리포트 파일을 raw JSON 없이 바로 열 수 있게 경로와 file link를 같이 보여줍니다." in execution_operator_ui.text
    assert "Validation Report File" in execution_operator_ui.text
    assert "Checklist Report File" in execution_operator_ui.text
    assert "Execution Quality Report File" in execution_operator_ui.text
    assert "5-Second Operator Kernel에서 money funnel, outcome attribution, outcome control, rollout 순서를 먼저 확인하고, 이어서 Approval Strip, Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤 대표 플랜과 현재 진입 가이드를 봅니다. kernel verdict가 hold/manual_review/watch면 Top Opportunity / Portfolio Candidate surface는 context-only입니다." in execution_operator_ui.text
    assert "Approval Strip Carryover" in execution_operator_ui.text
    assert "리포트 기준 최근 일수" in execution_operator_ui.text
    assert "기간 필터 제외" in execution_operator_ui.text
    assert "게이트 유형별 차단" in execution_operator_ui.text
    assert "유지해야 하는 hard gate" in execution_operator_ui.text
    assert "완화 검토 후보" in execution_operator_ui.text
    assert "연구 우선 포커스" in execution_operator_ui.text
    assert "추천 연구 액션" in execution_operator_ui.text
    assert "shadow research 순서를 안내합니다" in execution_operator_ui.text
    assert "권장 Shadow Experiment" in execution_operator_ui.text
    assert "shadow experiment 절차와 관찰 기준을 보여줍니다" in execution_operator_ui.text
    assert "완화 우선순위" in execution_operator_ui.text
    assert "Family 병목 상위" in execution_operator_ui.text
    assert "Regime 병목 상위" in execution_operator_ui.text
    assert "Session 병목 상위" in execution_operator_ui.text
    assert "multi_strategy_ab_expansion" in execution_operator_ui.text
    assert "b_continuation_activation" in execution_operator_ui.text
    assert "strategy_cluster_balance" in execution_operator_ui.text
    assert "promotion_governance" in execution_operator_ui.text
    assert "promotion_review_queue" in execution_operator_ui.text
    assert "promotion_remediation_queue" in execution_operator_ui.text
    assert "promotion_clearance_tracker" in execution_operator_ui.text
    assert "promotion_reopen_queue" in execution_operator_ui.text
    assert "promotion_decision_brief" in execution_operator_ui.text
    assert "auto_promotion_rollout_execution" in execution_operator_ui.text
    assert "promotion_lifecycle_history" in execution_operator_ui.text
    assert "research_promotion_operating_loop" in execution_operator_ui.text
    assert "live_candidate_promotion_readiness" in execution_operator_ui.text
    assert "live_candidate_promotion_readiness_global" in execution_operator_ui.text
    assert "promotion_decision" in execution_operator_ui.text
    assert "operator_review_items" in execution_operator_ui.text
    assert "attention_flags" in execution_operator_ui.text
    assert "write_scope" in execution_operator_ui.text
    assert "remaining_guardrail_domains" in execution_operator_ui.text
    assert "recent_transitions" in execution_operator_ui.text
    assert "outcome_control_trace_summary" in execution_operator_ui.text
    assert "rollout_recommendation_summary" in execution_operator_ui.text
    assert "capital_allocator_summary" in execution_operator_ui.text
    assert "accepted_candidates" in execution_operator_ui.text
    assert "blocked_candidates" in execution_operator_ui.text
    assert "outcome_bias" in execution_operator_ui.text
    assert "capital_allocator" in execution_operator_ui.text
    assert "session_penalty" in execution_operator_ui.text
    assert "reaction_evidence" in execution_operator_ui.text
    assert "location_reference" in execution_operator_ui.text
    assert "session_liquidity_reference" in execution_operator_ui.text
    assert "file://" in execution_operator_ui.text
    assert "fast=true" in execution_operator_ui.text
    assert "fetchOptionalJson" in execution_operator_ui.text
    assert "source_unavailable" in execution_operator_ui.text
    assert "operator-ui timeout" in execution_operator_ui.text
    assert "/execution/operator-dashboard" in execution_operator_ui.text
    assert "/operations/checklist" in execution_operator_ui.text
    assert "/validation/report" in execution_operator_ui.text
    assert "/execution/quality" in execution_operator_ui.text
    assert "/plans/top" in execution_operator_ui.text
    assert "/scanner/top" in execution_operator_ui.text

    kill_condition_apply = client.post(
        "/execution/control/kill-condition/apply",
        json={
            "symbol": "BTCUSDC",
            "universe": "usdc_perp_top30",
            "days": 7,
            "dry_run": True,
            "allow_live_write": False,
            "updated_by": "api_smoke",
        },
    )
    assert kill_condition_apply.status_code == 200
    kill_condition_apply_payload = kill_condition_apply.json()
    assert "kill_condition_state" in kill_condition_apply_payload
    assert "automation_bias" in kill_condition_apply_payload
    assert "effective_write_scope" in kill_condition_apply_payload
    assert "kill_condition_automation_summary" in kill_condition_apply_payload
    assert "safety_state_before" in kill_condition_apply_payload
    assert "safety_state_after" in kill_condition_apply_payload

    scanner = client.get("/scanner/top?universe=usdc_perp_top30&limit=5")
    assert scanner.status_code == 200
    scanner_rows = scanner.json()
    assert isinstance(scanner_rows, list)
    if scanner_rows:
        first = scanner_rows[0]
        assert "portfolio_penalty" in first
        assert "portfolio_high_corr_count" in first
        assert "risk_budget_score" in first
        assert "portfolio_total_cap" in first
        assert "portfolio_directional_cap" in first
        assert "portfolio_cluster_cap" in first
        assert "regime" in first
        assert "strategy_mode" in first
        assert "deployment_go_no_go" in first
        assert "deployment_code" in first
        assert "deployment_message" in first
        assert "risk_reason" in first
        assert "operating_lock" in first
        assert "session_guidance" in first
        assert "session_penalty" in first
        assert "strategy_family" in first
        assert "strategy_cluster" in first
        assert "strategy_cluster_status" in first
        assert "multi_strategy_overlay" in first
        assert "b_continuation_activation" in first
        assert "strategy_cluster_balance" in first
        assert "strategy_scorecard" in first
        assert "strategy_sizing" in first
        assert "reaction_evidence" in first
        assert "location_reference" in first
        assert "session_liquidity_reference" in first
        assert "recommended_risk_r" in first
        assert "expected_win_prob" in first
        assert "expected_ev_r" in first
        assert "expected_summary" in first
        assert "thesis_cluster_id" in first
        assert "thesis_primary_symbol" in first

    portfolio_budget = client.get("/portfolio/budget?universe=usdc_perp_top30&limit=5&write_report=false")
    assert portfolio_budget.status_code == 200
    portfolio_payload = portfolio_budget.json()
    assert portfolio_payload["universe"] == "usdc_perp_top30"
    assert "deployment_go_no_go" in portfolio_payload
    assert "deployment_code" in portfolio_payload
    assert "deployment_message" in portfolio_payload
    assert "playbook_go_no_go" in portfolio_payload
    assert "playbook_code" in portfolio_payload
    assert "playbook_action" in portfolio_payload
    assert "playbook_message" in portfolio_payload
    assert "approval_strip_summary" in portfolio_payload
    assert "approve_value" in portfolio_payload["approval_strip_summary"]
    assert "align_value" in portfolio_payload["approval_strip_summary"]
    assert "act_value" in portfolio_payload["approval_strip_summary"]
    assert "edge_experiment_review" in portfolio_payload
    assert "edge_evolution_rule" in portfolio_payload
    assert "review_followup_ledger" in portfolio_payload
    assert "current_exposure" in portfolio_payload
    assert "strategy_mode" in portfolio_payload
    assert "operating_lock" in portfolio_payload
    assert "mode_policy" in portfolio_payload
    assert "mode_stats" in portfolio_payload
    assert "headroom_by_regime" in portfolio_payload
    assert "accepted_candidates" in portfolio_payload
    assert "blocked_candidates" in portfolio_payload
    assert "alpha_research_count" in portfolio_payload
    assert "alpha_research_candidates" in portfolio_payload
    assert "multi_strategy_ab_summary" in portfolio_payload
    assert "strategy_cluster_balance_summary" in portfolio_payload
    assert "capital_allocator_summary" in portfolio_payload
    focus_symbol = (portfolio_payload.get("edge_experiment_review") or {}).get("focus_symbol")
    if focus_symbol:
        focus_rows = [
            row
            for row in [
                *portfolio_payload["accepted_candidates"],
                *portfolio_payload["blocked_candidates"],
                *portfolio_payload["alpha_research_candidates"],
            ]
            if row.get("symbol") == focus_symbol
        ]
        if focus_rows:
            assert "edge_experiment_focus" in focus_rows[0]
    if portfolio_payload["accepted_candidates"]:
        assert "strategy_family" in portfolio_payload["accepted_candidates"][0]
        assert "strategy_cluster" in portfolio_payload["accepted_candidates"][0]
        assert "strategy_cluster_status" in portfolio_payload["accepted_candidates"][0]
        assert "multi_strategy_overlay" in portfolio_payload["accepted_candidates"][0]
        assert "b_continuation_activation" in portfolio_payload["accepted_candidates"][0]
        assert "strategy_cluster_balance" in portfolio_payload["accepted_candidates"][0]
        assert "session_guidance" in portfolio_payload["accepted_candidates"][0]
        assert "session_penalty" in portfolio_payload["accepted_candidates"][0]
        assert "reaction_evidence" in portfolio_payload["accepted_candidates"][0]
        assert "location_reference" in portfolio_payload["accepted_candidates"][0]
        assert "session_liquidity_reference" in portfolio_payload["accepted_candidates"][0]
        assert "outcome_bias_score" in portfolio_payload["accepted_candidates"][0]
        assert "outcome_bias" in portfolio_payload["accepted_candidates"][0]
        assert "pre_outcome_final_rank_score" in portfolio_payload["accepted_candidates"][0]
        assert "post_outcome_final_rank_score" in portfolio_payload["accepted_candidates"][0]
        assert "capital_allocator" in portfolio_payload["accepted_candidates"][0]
        assert "allocation_weight" in portfolio_payload["accepted_candidates"][0]
        assert "allocated_risk_r" in portfolio_payload["accepted_candidates"][0]
        assert "capital_pressure" in portfolio_payload["accepted_candidates"][0]
        assert "expected_summary" in portfolio_payload["accepted_candidates"][0]
    if portfolio_payload["blocked_candidates"]:
        assert "strategy_family" in portfolio_payload["blocked_candidates"][0]
        assert "strategy_cluster" in portfolio_payload["blocked_candidates"][0]
        assert "strategy_cluster_status" in portfolio_payload["blocked_candidates"][0]
        assert "multi_strategy_overlay" in portfolio_payload["blocked_candidates"][0]
        assert "b_continuation_activation" in portfolio_payload["blocked_candidates"][0]
        assert "strategy_cluster_balance" in portfolio_payload["blocked_candidates"][0]
        assert "session_guidance" in portfolio_payload["blocked_candidates"][0]
        assert "session_penalty" in portfolio_payload["blocked_candidates"][0]
        assert "reaction_evidence" in portfolio_payload["blocked_candidates"][0]
        assert "location_reference" in portfolio_payload["blocked_candidates"][0]
        assert "session_liquidity_reference" in portfolio_payload["blocked_candidates"][0]
        assert "outcome_bias_score" in portfolio_payload["blocked_candidates"][0]
        assert "outcome_bias" in portfolio_payload["blocked_candidates"][0]
        assert "pre_outcome_final_rank_score" in portfolio_payload["blocked_candidates"][0]
        assert "post_outcome_final_rank_score" in portfolio_payload["blocked_candidates"][0]
        assert "capital_allocator" in portfolio_payload["blocked_candidates"][0]
        assert "allocation_weight" in portfolio_payload["blocked_candidates"][0]
        assert "allocated_risk_r" in portfolio_payload["blocked_candidates"][0]
        assert "capital_pressure" in portfolio_payload["blocked_candidates"][0]
        assert "block_reason_message" in portfolio_payload["blocked_candidates"][0]
        assert "alpha_research_candidate" in portfolio_payload["blocked_candidates"][0]
    if portfolio_payload["current_positions"]:
        assert "thesis_cluster_id" in portfolio_payload["current_positions"][0]
        assert "recommended_risk_r" in portfolio_payload["current_positions"][0]

    alert_test = client.post(
        "/alerts/test",
        json={
            "channel": "system",
            "symbol": "BTCUSDC",
            "message": "smoke test alert",
            "payload": {
                "source": "test_api_smoke",
                "deployment_go_no_go": "MANUAL_REVIEW",
                "deployment_code": "manual_review_test_gate",
                "deployment_message": "MANUAL_REVIEW: review before manual validation alert drill.",
                "approval_playbook_go_no_go": "MANUAL_REVIEW",
                "approval_playbook_code": "manual_review_test_gate",
                "approval_playbook_action": "run_manual_validation_alert_drill",
                "approval_playbook_message": "MANUAL_REVIEW: run the manual validation alert drill before rollout.",
            },
        },
    )
    assert alert_test.status_code == 200
    alert_payload = alert_test.json()
    assert alert_payload["channel"] == "system"
    assert alert_payload["deployment_go_no_go"] == "MANUAL_REVIEW"
    assert alert_payload["deployment_code"] == "manual_review_test_gate"
    assert alert_payload["approval_playbook_go_no_go"] == "MANUAL_REVIEW"
    assert alert_payload["approval_playbook_code"] == "manual_review_test_gate"
    assert alert_payload["approval_playbook_action"] == "run_manual_validation_alert_drill"
    assert alert_payload["approval_strip_summary"]["approve_value"] == "manual review first"
    assert alert_payload["approval_strip_summary"]["act_value"] == "run_manual_validation_alert_drill"
    assert alert_payload["delivery"]["skipped"] is True
    assert "retry_queued" in alert_payload

    alert_metrics = client.get("/alerts/metrics?days=30&write_report=false")
    assert alert_metrics.status_code == 200
    alert_metrics_payload = alert_metrics.json()
    assert "overall" in alert_metrics_payload
    assert "channel_metrics" in alert_metrics_payload
    assert "latest_validation_alert" in alert_metrics_payload
    if alert_metrics_payload["latest_validation_alert"]:
        assert "approval_playbook_go_no_go" in alert_metrics_payload["latest_validation_alert"]
        assert "approval_playbook_code" in alert_metrics_payload["latest_validation_alert"]
        assert "approval_playbook_action" in alert_metrics_payload["latest_validation_alert"]
        assert "approval_strip_summary" in alert_metrics_payload["latest_validation_alert"]
    assert "retry_queue" in alert_metrics_payload

    alert_retry_status = client.get("/internal/alerts/retry-queue/status")
    assert alert_retry_status.status_code == 200
    retry_status_payload = alert_retry_status.json()
    assert "counts" in retry_status_payload
    assert "retry_policy" in retry_status_payload

    alert_retry_process = client.post("/internal/alerts/retry-queue/process?limit=20")
    assert alert_retry_process.status_code == 200
    retry_process_payload = alert_retry_process.json()
    assert "scanned" in retry_process_payload

    alert_dead_letter_requeue = client.post("/internal/alerts/retry-queue/dead-letter/requeue?limit=20")
    assert alert_dead_letter_requeue.status_code == 200
    dead_letter_payload = alert_dead_letter_requeue.json()
    assert "requeued" in dead_letter_payload

    metrics = client.get("/metrics/strategy?symbol=BTCUSDC&version=v1")
    assert metrics.status_code == 200
    payload = metrics.json()
    assert payload["symbol"] == "BTCUSDC"
    assert payload["version"] == "v1"
    assert "risk_reason" in payload
    assert "operating_lock" in payload

    execution = client.get("/execution/quality?symbol=BTCUSDC&days=30&write_report=false")
    assert execution.status_code == 200
    ex_payload = execution.json()
    assert ex_payload["symbol"] == "BTCUSDC"
    assert "fill_sources" in ex_payload
    assert "stage_counts" in ex_payload
    assert "slippage_bps" in ex_payload
    assert "entry_latency_seconds" in ex_payload
    assert "fees" in ex_payload
    assert "unfilled_reasons" in ex_payload
    assert "unfilled_reason_details" in ex_payload
    assert "exit_reasons" in ex_payload
    assert "final_exit_reasons" in ex_payload
    assert "target_exit_ratio" in ex_payload
    assert "forced_exit_ratio" in ex_payload
    assert "by_strategy_family" in ex_payload
    assert "by_strategy_version" in ex_payload
    assert "version_comparison" in ex_payload

    reprocess = client.post("/internal/events/reprocess?limit=20")
    assert reprocess.status_code == 200
    re_payload = reprocess.json()
    assert "scanned" in re_payload
    assert "published" in re_payload

    report = client.post("/validation/report?symbol=BTCUSDC")
    assert report.status_code == 200
    rp = report.json()
    assert rp["symbol"] == "BTCUSDC"
    assert "validation_report" in rp
    assert "deployment_go_no_go" in rp
    assert "deployment_code" in rp
    assert "deployment_message" in rp
    assert "approval_topline_status" in rp
    assert "approval_topline_code" in rp
    assert "approval_topline_message" in rp
    assert "approval_topline_summary_line" in rp
    assert "playbook_go_no_go" in rp
    assert "playbook_code" in rp
    assert "playbook_action" in rp
    assert "playbook_message" in rp
    assert "deployment_approval_summary" in rp["validation_report"]
    assert "approval_strip_summary" in rp["validation_report"]
    assert "approve_value" in rp["validation_report"]["approval_strip_summary"]
    assert "align_value" in rp["validation_report"]["approval_strip_summary"]
    assert "act_value" in rp["validation_report"]["approval_strip_summary"]
    assert "topline_status" in rp["validation_report"]["deployment_approval_summary"]
    assert "topline_message" in rp["validation_report"]["deployment_approval_summary"]
    assert "topline_summary_line" in rp["validation_report"]["deployment_approval_summary"]
    assert "playbook_go_no_go" in rp["validation_report"]["deployment_approval_summary"]
    assert "playbook_code" in rp["validation_report"]["deployment_approval_summary"]
    assert "playbook_action" in rp["validation_report"]["deployment_approval_summary"]
    assert "playbook_message" in rp["validation_report"]["deployment_approval_summary"]
    assert rp["deployment_go_no_go"] == rp["validation_report"]["deployment_approval_summary"]["playbook_go_no_go"]
    assert rp["deployment_code"] == rp["validation_report"]["deployment_approval_summary"]["playbook_code"]
    assert rp["deployment_message"] == rp["validation_report"]["deployment_approval_summary"]["playbook_message"]
    assert rp["approval_topline_status"] == rp["validation_report"]["deployment_approval_summary"]["topline_status"]
    assert rp["approval_topline_code"] == rp["validation_report"]["deployment_approval_summary"]["topline_code"]
    assert rp["approval_topline_message"] == rp["validation_report"]["deployment_approval_summary"]["topline_message"]
    assert (
        rp["approval_topline_summary_line"]
        == rp["validation_report"]["deployment_approval_summary"]["topline_summary_line"]
    )
    assert rp["playbook_go_no_go"] == rp["validation_report"]["deployment_approval_summary"]["playbook_go_no_go"]
    assert rp["playbook_code"] == rp["validation_report"]["deployment_approval_summary"]["playbook_code"]
    assert rp["playbook_action"] == rp["validation_report"]["deployment_approval_summary"]["playbook_action"]
    assert rp["playbook_message"] == rp["validation_report"]["deployment_approval_summary"]["playbook_message"]
    if rp.get("validation_alert") is not None:
        assert "deployment_go_no_go" in rp["validation_alert"]
        assert "deployment_code" in rp["validation_alert"]
        assert "deployment_message" in rp["validation_alert"]
        assert "approval_topline_summary_line" in rp["validation_alert"]
        assert "approval_playbook_go_no_go" in rp["validation_alert"]
        assert "approval_playbook_code" in rp["validation_alert"]
        assert "approval_playbook_action" in rp["validation_alert"]
        assert "approval_playbook_message" in rp["validation_alert"]
    assert "execution_quality" in rp
    assert "feature_importance" in rp
    assert "feature_calibration" in rp
    assert "strategy_v2_validation" in rp
    assert "strategy_v2_lock_validation" in rp
    assert "strategy_v2_pbo_dsr_trial_writer" in rp
    assert "strategy_v2_pbo_dsr_threshold_runner" in rp
    assert "strategy_v2_pbo_dsr_artifact_store" in rp
    assert "strategy_v2_pbo_dsr_design" in rp
    assert "strategy_v2_pbo_dsr_metrics" in rp
    assert "strategy_v2_stress_validation" in rp
    assert "strategy_v2_stress_replay_lineage" in rp
    assert "strategy_v2_stress_replay_assessment" in rp
    assert "strategy_v2_stress_replay_runner_contract" in rp
    assert "strategy_v2_stress_replay_lineage_writer" in rp
    assert "strategy_v2_stress_replay_prototype_worker" in rp
    assert "top_shadow_experiment_id" in rp["validation_report"]["alpha_research_pipeline_summary"]
    assert "top_shadow_experiment_title" in rp["validation_report"]["alpha_research_pipeline_summary"]
    assert "top_shadow_experiment_target" in rp["validation_report"]["alpha_research_pipeline_summary"]
    assert "shadow_experiment_template_count" in rp["validation_report"]["alpha_research_pipeline_summary"]
    assert "evidence_available" in rp["validation_report"]["alpha_research_pipeline_summary"]
    assert "softening_review_available" in rp["validation_report"]["alpha_research_pipeline_summary"]
    assert "promotion_watchlist_available" in rp["validation_report"]["alpha_research_pipeline_summary"]
    assert "forward_stress_regime_validation_available" in rp["validation_report"]
    assert "forward_stress_regime_validation_summary" in rp["validation_report"]
    assert "kill_condition_automation_available" in rp["validation_report"]
    assert "kill_condition_automation_summary" in rp["validation_report"]
    assert "strategy_v2_thesis_validation" in rp
    assert "strategy_v2_scalp_experiment" in rp
    assert "alpha_research_pipeline" in rp
    assert "score_to_outcome_funnel" in rp["validation_report"]
    assert "score_to_outcome_funnel_summary" in rp["validation_report"]
    assert "operating_kpis" in rp["validation_report"]["score_to_outcome_funnel_summary"]
    assert "execution_degradation_advisory_available" in rp["validation_report"]
    assert "execution_degradation_advisory_summary" in rp["validation_report"]
    assert "family_execution_degradation_advisory" in rp["validation_report"]
    assert "family_execution_degradation_advisory_summary" in rp["validation_report"]
    assert "mode_advisory" in rp["validation_report"]
    assert "mode_advisory_summary" in rp["validation_report"]
    assert "operator_action_priority" in rp["validation_report"]
    assert "operator_action_priority_summary" in rp["validation_report"]
    assert rp["operator_action_priority_summary"] == rp["validation_report"]["operator_action_priority_summary"]
    assert "priority_source" in rp["validation_report"]["operator_action_priority_summary"]
    assert "action_family" in rp["validation_report"]["operator_action_priority_summary"]
    assert "top_action_followup_command" in rp["validation_report"]["operator_action_priority_summary"]
    assert "capture_context" in rp["validation_report"]["operator_action_priority_summary"]
    assert "experiment_context" in rp["validation_report"]["operator_action_priority_summary"]
    assert "outcome_control_trace_available" in rp["validation_report"]
    assert "outcome_control_trace_summary" in rp["validation_report"]
    assert "edge_experiment_review_available" in rp["validation_report"]
    assert "edge_experiment_review_summary" in rp["validation_report"]
    assert rp["edge_experiment_review_summary"] == rp["validation_report"]["edge_experiment_review_summary"]
    assert "edge_proof_goal_closed_trades" in rp["edge_experiment_review_summary"]
    assert "edge_proof_posture" in rp["edge_experiment_review_summary"]
    assert "operating_discipline" in rp["edge_experiment_review_summary"]
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["system_mode"] == "operate_and_experiment"
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["current_system_identity"] == "edge_proof_engine"
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["next_system_stage"] == "post_first_verified_edge"
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["resilience_claim"] == "harder_to_fail_from_self_deception"
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["fail_safe_claim"] is False
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["post_proof_scale_spec_id"] == "edge_proof_capital_scale_v1"
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["realized_edge_dependency_domains"] == [
        "market_edge",
        "execution_quality",
        "operating_discipline",
    ]
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["loss_driven_rewrite_allowed"] is False
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["rollout_expansion_allowed"] is False
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["alpha_generator_review_allowed"] is False
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["signal_density_control_review_allowed"] is False
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["execution_strategy_automation_review_allowed"] is False
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["multi_strategy_expansion_review_allowed"] is False
    assert rp["edge_experiment_review_summary"]["operating_discipline"]["capital_scale_review_allowed"] is False
    assert "daily_edge_kpis" in rp["edge_experiment_review_summary"]
    assert "edge_evolution_rule_available" in rp["validation_report"]
    assert "edge_evolution_rule_summary" in rp["validation_report"]
    assert rp["edge_evolution_rule_summary"] == rp["validation_report"]["edge_evolution_rule_summary"]
    assert "review_followup_ledger_available" in rp["validation_report"]
    assert "review_followup_ledger_summary" in rp["validation_report"]
    assert rp["review_followup_ledger_summary"] == rp["validation_report"]["review_followup_ledger_summary"]
    assert "rollout_recommendation_available" in rp["validation_report"]
    assert "rollout_recommendation_summary" in rp["validation_report"]
    assert "strategy_lifecycle_available" in rp["validation_report"]
    assert "strategy_lifecycle_summary" in rp["validation_report"]
    assert "promotion_governance_available" in rp["validation_report"]
    assert "promotion_governance_summary" in rp["validation_report"]
    assert "promotion_review_queue_available" in rp["validation_report"]
    assert "promotion_review_queue_summary" in rp["validation_report"]
    assert "promotion_remediation_queue_available" in rp["validation_report"]
    assert "promotion_remediation_queue_summary" in rp["validation_report"]
    assert "promotion_clearance_tracker_available" in rp["validation_report"]
    assert "promotion_clearance_tracker_summary" in rp["validation_report"]
    assert "promotion_reopen_queue_available" in rp["validation_report"]
    assert "promotion_reopen_queue_summary" in rp["validation_report"]
    assert "promotion_decision_brief_available" in rp["validation_report"]
    assert "promotion_decision_brief_summary" in rp["validation_report"]
    assert "auto_promotion_rollout_execution_available" in rp["validation_report"]
    assert "auto_promotion_rollout_execution_summary" in rp["validation_report"]
    assert "promotion_lifecycle_history_available" in rp["validation_report"]
    assert "promotion_lifecycle_history_summary" in rp["validation_report"]
    assert "research_promotion_operating_loop_available" in rp["validation_report"]
    assert "research_promotion_operating_loop_summary" in rp["validation_report"]
    assert "multi_strategy_ab_available" in rp["validation_report"]
    assert "multi_strategy_ab_summary" in rp["validation_report"]
    assert "b_continuation_activation_available" in rp["validation_report"]
    assert "b_continuation_activation_summary" in rp["validation_report"]
    assert "execution_friction_measurement_available" in rp["validation_report"]
    assert "execution_friction_measurement_summary" in rp["validation_report"]
    assert "b_continuation_edge_validation_available" in rp["validation_report"]
    assert "b_continuation_edge_validation_summary" in rp["validation_report"]
    assert "strategy_cluster_balance_available" in rp["validation_report"]
    assert "strategy_cluster_balance_summary" in rp["validation_report"]
    assert "a_strategy_post_cost_edge_validation_available" in rp["validation_report"]
    assert "a_strategy_post_cost_edge_validation_summary" in rp["validation_report"]
    assert "positive_evidence_expansion_available" in rp["validation_report"]
    assert "positive_evidence_expansion_summary" in rp["validation_report"]
    assert "outcome_bucket_granularity_available" in rp["validation_report"]
    assert "outcome_bucket_granularity_summary" in rp["validation_report"]
    assert "opportunity_capture_available" in rp["validation_report"]
    assert "opportunity_capture_summary" in rp["validation_report"]
    assert "capital_allocator_available" in rp["validation_report"]
    assert "capital_allocator_summary" in rp["validation_report"]
    assert "parameter_changelog" in rp
    stress_payload = rp["strategy_v2_stress_validation"]
    assert "scenario_metrics" in stress_payload
    assert "scenario_comparison" in stress_payload
    assert "replay_output_artifacts" in stress_payload
    assert "replay_output_comparison" in stress_payload
    assert "replay_gate_applied" in stress_payload["deployment_recommendation"]
    assert "worst_scenario_source" in stress_payload["deployment_recommendation"]
    assert "divergence_gate_applied" in stress_payload["deployment_recommendation"]
    assert "divergence_problem_scenarios" in stress_payload["deployment_recommendation"]
    assert "latency_plus_1_bar" in stress_payload["scenario_metrics"]
    assert "partial_fills_only" in stress_payload["scenario_metrics"]
    assert "shock_concentration" in stress_payload["scenario_metrics"]
    artifact_payload = rp["strategy_v2_pbo_dsr_artifact_store"]
    assert "artifact_store_ready" in artifact_payload
    assert "counts" in artifact_payload
    trial_writer_payload = rp["strategy_v2_pbo_dsr_trial_writer"]
    assert "available" in trial_writer_payload
    assert "sample_counts" in trial_writer_payload
    threshold_runner_payload = rp["strategy_v2_pbo_dsr_threshold_runner"]
    assert "available" in threshold_runner_payload
    assert "selection_rule" in threshold_runner_payload
    assert "lineage_namespace" in threshold_runner_payload
    pbo_dsr_metrics_payload = rp["strategy_v2_pbo_dsr_metrics"]
    assert "available" in pbo_dsr_metrics_payload
    assert "pbo" in pbo_dsr_metrics_payload
    assert "dsr" in pbo_dsr_metrics_payload
    assert "selection_rule_counts" in pbo_dsr_metrics_payload
    stress_replay_payload = rp["strategy_v2_stress_replay_assessment"]
    assert "full_replay_ready" in stress_replay_payload
    assert "true_runner_readiness" in stress_replay_payload
    assert "deployment_recommendation" in stress_replay_payload
    assert "true_runner_promotion_ready" in stress_replay_payload["deployment_recommendation"]
    assert "true_runner_promotion_action" in stress_replay_payload["deployment_recommendation"]
    assert "threshold_lineage_audit_status" in stress_replay_payload["deployment_recommendation"]
    assert "replay_output_lineage_alignment_status" in stress_replay_payload["deployment_recommendation"]
    assert "approval_cross_display" in stress_replay_payload["deployment_recommendation"]
    assert "approval_warning_locked" in stress_replay_payload["deployment_recommendation"]["approval_cross_display"]
    stress_replay_runner_payload = rp["strategy_v2_stress_replay_runner_contract"]
    assert "runtime_job_ready" in stress_replay_runner_payload
    assert "true_runner_readiness" in stress_replay_runner_payload
    assert "runner_contract" in stress_replay_runner_payload
    stress_replay_writer_payload = rp["strategy_v2_stress_replay_lineage_writer"]
    assert "artifacts_written" in stress_replay_writer_payload
    assert "scenario_batches" in stress_replay_writer_payload
    stress_replay_prototype_payload = rp["strategy_v2_stress_replay_prototype_worker"]
    assert "executed" in stress_replay_prototype_payload
    assert "scenario_runs" in stress_replay_prototype_payload
    stress_replay_lineage_payload = rp["strategy_v2_stress_replay_lineage"]
    assert "runtime_inputs_ready" in stress_replay_lineage_payload
    assert "coverage" in stress_replay_lineage_payload
    scalp_experiment_payload = rp["strategy_v2_scalp_experiment"]
    assert "available" in scalp_experiment_payload
    assert "comparison" in scalp_experiment_payload
    alpha_research_payload = rp["alpha_research_pipeline"]
    assert "available" in alpha_research_payload
    assert "analysis_symbol" in alpha_research_payload
    assert "summary" in alpha_research_payload
    assert "candidates" in alpha_research_payload
    assert "research_focus_alignment" in alpha_research_payload

    pbo_dsr_trial_writer = client.get("/validation/pbo-dsr/trial-writer?symbol=BTCUSDC&write_report=false")
    assert pbo_dsr_trial_writer.status_code == 200
    pbo_dsr_trial_writer_payload = pbo_dsr_trial_writer.json()
    assert pbo_dsr_trial_writer_payload["symbol"] == "BTCUSDC"
    assert "available" in pbo_dsr_trial_writer_payload
    assert "sample_counts" in pbo_dsr_trial_writer_payload

    pbo_dsr_threshold_runner = client.get("/validation/pbo-dsr/threshold-runner?symbol=BTCUSDC&write_report=false")
    assert pbo_dsr_threshold_runner.status_code == 200
    pbo_dsr_threshold_runner_payload = pbo_dsr_threshold_runner.json()
    assert pbo_dsr_threshold_runner_payload["symbol"] == "BTCUSDC"
    assert "available" in pbo_dsr_threshold_runner_payload
    assert "selection_rule" in pbo_dsr_threshold_runner_payload

    pbo_dsr = client.get("/validation/pbo-dsr?symbol=BTCUSDC&write_report=false")
    assert pbo_dsr.status_code == 200
    pbo_dsr_payload = pbo_dsr.json()
    assert pbo_dsr_payload["symbol"] == "BTCUSDC"
    assert "available" in pbo_dsr_payload
    assert "pbo" in pbo_dsr_payload
    assert "dsr" in pbo_dsr_payload
    assert "selection_rule_counts" in pbo_dsr_payload
    assert "lineage_audit" in pbo_dsr_payload
    assert "selection_universe_summary" in pbo_dsr_payload

    pbo_dsr_artifact = client.get("/validation/pbo-dsr/artifact-store?symbol=BTCUSDC&write_report=false")
    assert pbo_dsr_artifact.status_code == 200
    pbo_dsr_artifact_payload = pbo_dsr_artifact.json()
    assert pbo_dsr_artifact_payload["symbol"] == "BTCUSDC"
    assert "artifact_store_ready" in pbo_dsr_artifact_payload
    assert "counts" in pbo_dsr_artifact_payload
    assert "selection_rule_counts" in pbo_dsr_artifact_payload
    assert "selection_universe_summary" in pbo_dsr_artifact_payload

    scalp_experiment = client.get("/validation/scalp-experiment?symbol=BTCUSDC&write_report=false")
    assert scalp_experiment.status_code == 200
    scalp_experiment_direct_payload = scalp_experiment.json()
    assert scalp_experiment_direct_payload["symbol"] == "BTCUSDC"
    assert "available" in scalp_experiment_direct_payload
    assert "comparison" in scalp_experiment_direct_payload

    alpha_research = client.get("/validation/alpha-research?universe=usdc_perp_top30&symbol=BTCUSDC&write_report=false")
    assert alpha_research.status_code == 200
    alpha_research_direct_payload = alpha_research.json()
    assert alpha_research_direct_payload["universe"] == "usdc_perp_top30"
    assert "available" in alpha_research_direct_payload
    assert "analysis_symbol" in alpha_research_direct_payload
    assert "summary" in alpha_research_direct_payload
    assert "candidates" in alpha_research_direct_payload
    assert "research_focus_alignment" in alpha_research_direct_payload
    assert "alpha_research_evidence_summary" in alpha_research_direct_payload
    assert "softening_candidate_review" in alpha_research_direct_payload
    assert "promotion_watchlist" in alpha_research_direct_payload

    stress_replay = client.get("/validation/stress-replay-assessment?symbol=BTCUSDC&write_report=false")
    assert stress_replay.status_code == 200
    stress_replay_direct_payload = stress_replay.json()
    assert stress_replay_direct_payload["symbol"] == "BTCUSDC"
    assert "full_replay_ready" in stress_replay_direct_payload
    assert "coverage" in stress_replay_direct_payload

    stress_replay_lineage = client.get("/validation/stress-replay-lineage?symbol=BTCUSDC&write_report=false")
    assert stress_replay_lineage.status_code == 200
    stress_replay_lineage_direct_payload = stress_replay_lineage.json()
    assert stress_replay_lineage_direct_payload["symbol"] == "BTCUSDC"
    assert "runtime_inputs_ready" in stress_replay_lineage_direct_payload
    assert "coverage" in stress_replay_lineage_direct_payload

    stress_replay_runner = client.get("/validation/stress-replay-runner-contract?symbol=BTCUSDC&write_report=false")
    assert stress_replay_runner.status_code == 200
    stress_replay_runner_direct_payload = stress_replay_runner.json()
    assert stress_replay_runner_direct_payload["symbol"] == "BTCUSDC"
    assert "runtime_job_ready" in stress_replay_runner_direct_payload
    assert "runner_contract" in stress_replay_runner_direct_payload

    stress_replay_lineage_writer = client.get("/validation/stress-replay-lineage-writer?symbol=BTCUSDC&write_report=false")
    assert stress_replay_lineage_writer.status_code == 200
    stress_replay_lineage_writer_payload = stress_replay_lineage_writer.json()
    assert stress_replay_lineage_writer_payload["symbol"] == "BTCUSDC"
    assert "artifacts_written" in stress_replay_lineage_writer_payload
    assert "scenario_batches" in stress_replay_lineage_writer_payload

    stress_replay_output_artifacts = client.get("/validation/stress-replay-output-artifacts?symbol=BTCUSDC&write_report=false")
    assert stress_replay_output_artifacts.status_code == 200
    stress_replay_output_artifacts_payload = stress_replay_output_artifacts.json()
    assert stress_replay_output_artifacts_payload["symbol"] == "BTCUSDC"
    assert "available" in stress_replay_output_artifacts_payload
    assert "lineage_summary" in stress_replay_output_artifacts_payload
    assert "scenario_outputs" in stress_replay_output_artifacts_payload
    assert "comparison_to_approximation" in stress_replay_output_artifacts_payload

    stress_replay_prototype_worker = client.post(
        "/validation/stress-replay-worker/prototype?symbol=BTCUSDC&write_report=false"
    )
    assert stress_replay_prototype_worker.status_code == 200
    stress_replay_prototype_worker_payload = stress_replay_prototype_worker.json()
    assert stress_replay_prototype_worker_payload["symbol"] == "BTCUSDC"
    assert "executed" in stress_replay_prototype_worker_payload
    assert "scenario_runs" in stress_replay_prototype_worker_payload

    operations = client.post("/operations/checklist?symbol=BTCUSDC&universe=usdc_perp_top30&limit=5&days=30&write_report=false")
    assert operations.status_code == 200
    ops_payload = operations.json()
    assert ops_payload["symbol"] == "BTCUSDC"
    assert "overall_status" in ops_payload
    assert "deployment_go_no_go" in ops_payload
    assert "deployment_code" in ops_payload
    assert "deployment_message" in ops_payload
    assert "playbook_go_no_go" in ops_payload
    assert "playbook_code" in ops_payload
    assert "playbook_action" in ops_payload
    assert "playbook_message" in ops_payload
    assert "approval_strip_summary" in ops_payload
    assert "approve_value" in ops_payload["approval_strip_summary"]
    assert "align_value" in ops_payload["approval_strip_summary"]
    assert "act_value" in ops_payload["approval_strip_summary"]
    assert "checks" in ops_payload
    portfolio_item = next((item for item in ops_payload["checks"] if item["item_id"] == "portfolio_headroom"), None)
    if portfolio_item is not None:
        assert "deployment_go_no_go" in portfolio_item["evidence"]
        assert "deployment_code" in portfolio_item["evidence"]
        assert "deployment_message" in portfolio_item["evidence"]
        assert "playbook_go_no_go" in portfolio_item["evidence"]
        assert "playbook_code" in portfolio_item["evidence"]
        assert "playbook_action" in portfolio_item["evidence"]
        assert "playbook_message" in portfolio_item["evidence"]
    validation_item = next((item for item in ops_payload["checks"] if item["item_id"] == "validation_alert_delivery"), None)
    if validation_item is not None:
        assert "approval_playbook_go_no_go" in validation_item["evidence"]
        assert "approval_playbook_code" in validation_item["evidence"]
        assert "approval_playbook_action" in validation_item["evidence"]
        assert "approval_playbook_message" in validation_item["evidence"]
    item_ids = {item["item_id"] for item in ops_payload["checks"]}
    assert "health_ready" in item_ids
    assert "validation_report" in item_ids
    assert "alert_test_recent" in item_ids
    assert "risk_gate_open" in item_ids
    assert "session_guidance" in item_ids
    assert "execution_degradation_advisory" in item_ids
    assert "operator_action_priority" in item_ids

    report_no_refresh = client.post("/validation/report?symbol=BTCUSDC&refresh=false")
    assert report_no_refresh.status_code == 200
    assert report_no_refresh.json()["symbol"] == "BTCUSDC"

    fi = client.get("/validation/feature-importance?symbol=BTCUSDC")
    assert fi.status_code == 200
    fi_payload = fi.json()
    assert fi_payload["symbol"] == "BTCUSDC"
    assert "available" in fi_payload

    fc = client.get("/validation/feature-calibration?symbol=BTCUSDC&write_report=false")
    assert fc.status_code == 200
    fc_payload = fc.json()
    assert fc_payload["symbol"] == "BTCUSDC"
    assert "recommended_weights" in fc_payload
    assert "by_regime" in fc_payload

    plans_after_calibration = client.get("/plans/top?symbol=BTCUSDC&tf=5m&limit=5&refresh=true")
    assert plans_after_calibration.status_code == 200
    plans_after_payload = plans_after_calibration.json()
    if fc_payload["available"] and plans_after_payload:
        first_plan_validity = plans_after_payload[0]["validity"]
        assert first_plan_validity["feature_calibration_available"] is True
        assert "feature_weights_active" in first_plan_validity

    legacy_fc = client.get("/validation/importance-calibration?symbol=BTCUSDC&write_report=false")
    assert legacy_fc.status_code == 200
    legacy_fc_payload = legacy_fc.json()
    assert legacy_fc_payload["symbol"] == "BTCUSDC"
    assert "matched_samples" in legacy_fc_payload
