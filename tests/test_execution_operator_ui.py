from __future__ import annotations

from app.services.execution_operator_ui import build_execution_operator_ui


def test_execution_operator_ui_includes_shadow_experiment_panel() -> None:
    html = build_execution_operator_ui(symbol="BTCUSDC", universe="usdc_perp_top30", days=7)

    assert "Decision Summary" in html
    assert "Approval Divergence" in html
    assert "dashboard / checklist / validation / candidate surface가 서로 다른 방향을 가리키고 있습니다." in html or "dashboard / checklist / validation / candidate surface가 같은 방향을 가리키고 있습니다." in html
    assert "Top Opportunity" in html
    assert "Top Blocker" in html
    assert "Current Operating State" in html
    assert "상단 operator surface는 Decision Summary 안의 Top Operator Action을 먼저 확인하고, 이어서 Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤" in html
    assert "대표 플랜과 상세 운영 섹션으로 내려가면 됩니다." in html
    assert "Decision Summary 안의 Top Operator Action을 먼저 확인하고, 이어서 Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤 대표 플랜과 현재 진입 가이드를 봅니다." in html
    assert "Family Execution Advisory" in html
    assert "Family Advisory Coverage" in html
    assert "Top Operator Action" in html
    assert "Next Actions" in html
    assert "A/B Strategy Posture" in html
    assert "A remains anchor인지, B continuation이 research-only인지 guarded activation인지, 현재 mix가 여전히 A 집중인지까지 한 번에 읽습니다." in html
    assert "현재 A/B mix" in html
    assert "Promotion Operating Stack" in html
    assert "승격 review, remediation, clearance, reopen, semi-auto execution, history, research followthrough를 한 번에 읽습니다." in html
    assert "남은 Guardrail Domain" in html
    assert "최근 Promotion Transition" in html
    assert "Promotion Case Inspector" in html
    assert "현재 headline family의 승격 case를 single-family inspector로 다시 압축해, target posture, write scope, remaining guardrails, next move를 바로 읽습니다." in html
    assert "Next Move" in html
    assert "Remaining Guardrails" in html
    assert "Cleared Guardrails" in html
    assert "Validation / Checklist Review Stack" in html
    assert "validation top-level summary와 checklist item status를 같은 표로 압축해서, raw JSON 없이 operator review stack을 읽습니다." in html
    assert "Validation GO/NO_GO" in html
    assert "Checklist GO/NO_GO" in html
    assert "Validation Case Inspector" in html
    assert "현재 symbol validation case를 outcome control, rollout, lifecycle, A/B posture, condition split, capture, allocator 기준으로 다시 압축해 operator가 한 카드로 읽습니다." in html
    assert "Top Condition Split" in html
    assert "Opportunity Capture" in html
    assert "Next Validation Move" in html
    assert "Operator Reading Order" in html
    assert "Runtime Quality Inspector" in html
    assert "최근 validation alert, retry queue, execution quality, reconciliation health를 한 카드로 압축해 runtime 운영 품질을 빠르게 읽습니다." in html
    assert "Runtime Next Move" in html
    assert "Quality Drift Focus" in html
    assert "Signal Funnel Inspector" in html
    assert "현재 hard gate, softening 후보, rollout block, family/regime/session bottleneck을 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Top Family Bottleneck" in html
    assert "Top Regime Bottleneck" in html
    assert "Top Session Bottleneck" in html
    assert "Current Gate Reason" in html
    assert "Softening Priority Queue" in html
    assert "Alpha Research Inspector" in html
    assert "research backlog, 추천 연구 액션, top shadow experiment, softening review, promotion watchlist를 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Research Next Move" in html
    assert "Top Shadow Metrics" in html
    assert "Softening Review Queue" in html
    assert "Promotion Watchlist Queue" in html
    assert "Kill Condition Inspector" in html
    assert "stop review verdict, trigger axis, write scope, manual override, 현재 lock state를 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Stop Review Verdict" in html
    assert "Current Lock State" in html
    assert "Kill Condition Next Move" in html
    assert "Policy / Lock Inspector" in html
    assert "kill switch, close-only, active lock, matching lock, rollout policy를 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Active Lock Queue" in html
    assert "Rollout Policy Queue" in html
    assert "Policy Next Move" in html
    assert "Intent / Exposure Inspector" in html
    assert "최근 intent 흐름, 열린 주문, 열린 포지션, 현재 익스포저 상태를 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Recent Intent Queue" in html
    assert "Live Exposure Queue" in html
    assert "Intent Next Move" in html
    assert "Mode / Deployment Inspector" in html
    assert "execution mode, entry gate, dashboard-checklist-validation 배포 상태, rollout recommendation, mode advisory를 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Entry Gate Reason" in html
    assert "Top Mode Bucket" in html
    assert "Deployment Next Move" in html
    assert "Approval Alignment Inspector" in html
    assert "dashboard, checklist, validation, candidate, operator priority가 같은 배포 방향을 가리키는지 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Deployment Message Stack" in html
    assert "Approval Next Move" in html
    assert "Data Freshness / Source Inspector" in html
    assert "dashboard, validation, checklist, execution-quality source와 generated_at / report path 상태를 홈 섹션에서 바로 확인합니다." in html
    assert "Source Flow" in html
    assert "Freshness Note" in html
    assert "Portfolio Candidate Drilldown" in html
    assert "accepted / blocked 후보를 raw JSON 없이 읽기 위해, cluster, allocated risk, outcome bias, capital allocator, A/B posture를 같은 표로 보여줍니다." in html
    assert "Portfolio Candidate Inspector" in html
    assert "대표 accepted row 1개와 blocked row 1개를 카드로 다시 압축해, risk, allocator, A/B posture, session, reaction evidence를 바로 읽습니다." in html
    assert "Representative Accepted Candidate" in html
    assert "Representative Blocked Candidate" in html
    assert "Why This Row Matters" in html
    assert "Checklist Evidence Drilldown" in html
    assert "WARN / MANUAL / FAIL 체크를 evidence 중심으로 다시 펼쳐서, raw checklist payload 없이 operator review 포인트를 읽습니다." in html
    assert "Report Navigation" in html
    assert "validation / checklist / execution quality 리포트 파일을 raw JSON 없이 바로 열 수 있게 경로와 file link를 같이 보여줍니다." in html
    assert "Validation Report File" in html
    assert "Checklist Report File" in html
    assert "Execution Quality Report File" in html
    assert "지금 신규 진입 가능 여부와 Decision Summary 안의 server-side Top Operator Action을 먼저 보여줍니다. policy mutation이 아니라 reading priority입니다." in html
    assert "Top Operator Action과 Top Opportunity / Top Blocker 다음 순서에서, 포트폴리오, execution, family advisory, mode, research 기준의 server-side 현재 운영 해석과 next actions를 요약합니다." in html
    assert "권장 Shadow Experiment" in html
    assert "operator가 다음으로 돌릴 shadow experiment 절차와 관찰 기준을 보여줍니다." in html
    assert "shadow_experiment_templates" in html
    assert "alpha_research_top_shadow_experiment" in html
    assert "multi_strategy_ab_expansion" in html
    assert "b_continuation_activation" in html
    assert "strategy_cluster_balance" in html
    assert "promotion_governance" in html
    assert "promotion_review_queue" in html
    assert "promotion_remediation_queue" in html
    assert "promotion_clearance_tracker" in html
    assert "promotion_reopen_queue" in html
    assert "promotion_decision_brief" in html
    assert "auto_promotion_rollout_execution" in html
    assert "promotion_lifecycle_history" in html
    assert "research_promotion_operating_loop" in html
    assert "write_scope" in html
    assert "remaining_guardrail_domains" in html
    assert "recent_transitions" in html
    assert "outcome_control_trace_summary" in html
    assert "rollout_recommendation_summary" in html
    assert "strategy_lifecycle_summary" in html
    assert "multi_strategy_ab_summary" in html
    assert "b_continuation_activation_summary" in html
    assert "strategy_cluster_balance_summary" in html
    assert "capital_allocator_summary" in html
    assert "alert_summary" in html
    assert "execution_quality_summary" in html
    assert "recent_reconciliation_summary" in html
    assert "quality_softening_priorities" in html
    assert "family_bottlenecks" in html
    assert "regime_bottlenecks" in html
    assert "session_bottlenecks" in html
    assert "alpha_research_summary" in html
    assert "alpha_research_focus_alignment" in html
    assert "alpha_research_softening_review" in html
    assert "alpha_research_promotion_watchlist" in html
    assert "kill_switch_active" in html
    assert "close_only_active" in html
    assert "active_locks" in html
    assert "rollout_policies" in html
    assert "recent_intents" in html
    assert "open_orders" in html
    assert "open_positions" in html
    assert "mode_advisory_summary" in html
    assert "execution_mode" in html
    assert "new_entries_allowed" in html
    assert "approval_topline_summary_line" in html
    assert "operator_action_priority" in html
    assert "Dashboard Generated" in html
    assert "Validation Generated" in html
    assert "validation_report" in html
    assert "accepted_candidates" in html
    assert "blocked_candidates" in html
    assert "outcome_bias" in html
    assert "capital_allocator" in html
    assert "session_penalty" in html
    assert "reaction_evidence" in html
    assert "location_reference" in html
    assert "session_liquidity_reference" in html
    assert "file://" in html
    assert "/execution/quality" in html
