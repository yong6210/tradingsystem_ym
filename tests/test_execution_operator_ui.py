from __future__ import annotations

from app.services.execution_operator_ui import build_execution_operator_ui


def test_execution_operator_ui_includes_shadow_experiment_panel() -> None:
    html = build_execution_operator_ui(symbol="BTCUSDC", universe="usdc_perp_top30", days=7)

    assert "Approval Strip" in html
    assert "dashboard / checklist / validation / candidate surface가 서로 다른 방향을 가리키고 있습니다." in html or "dashboard / checklist / validation / candidate surface가 같은 방향을 가리키고 있습니다." in html
    assert "5-Second Operator Kernel" in html
    assert "operator가 5초 안에 money funnel -> outcome attribution -> outcome control -> rollout 순서로 현재 돈 누수와 승인 방향을 읽도록 압축한 kernel view입니다." in html
    assert "Kernel Verdict" in html
    assert "Kernel Reading Order" in html
    assert "Checklist Trace" in html
    assert "Kernel Next Move" in html
    assert "Top Opportunity" in html
    assert "Top Blocker" in html
    assert "Current Operating State" in html
    assert "상단 operator surface는 5-Second Operator Kernel을 먼저 보고, 이어서 Approval Strip, Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤" in html
    assert "대표 플랜과 상세 운영 섹션으로 내려가면 됩니다." in html
    assert "kernel verdict가 hold/manual_review/watch면 Top Opportunity / Portfolio Candidate surface는 context-only로 읽습니다." in html
    assert "5-Second Operator Kernel에서 money funnel, outcome attribution, outcome control, rollout 순서를 먼저 확인하고, 이어서 Approval Strip, Top Opportunity / Top Blocker, Current Operating State 순서로 읽은 뒤 대표 플랜과 현재 진입 가이드를 봅니다. kernel verdict가 hold/manual_review/watch면 Top Opportunity / Portfolio Candidate surface는 context-only입니다." in html
    assert "Deferred Research / Promotion Stack" in html
    assert "kernel verdict가 hold/manual_review/watch라서 promotion/research stack을 기본 접힘 상태로 둡니다." in html
    assert "id=\"top-opportunity-panel\"" in html
    assert "kernel-muted-surface" in html
    assert "kernel-guard-note" in html
    assert "opportunity/candidate surface는 context-only로 읽고 approval/alignment/checklist를 먼저 확인합니다." in html
    assert "opportunity/candidate surface를 정상 우선순위로 읽되 money funnel과 approval alignment를 먼저 확인한 뒤 drilldown으로 내려갑니다." in html
    assert "Family Execution Advisory" in html
    assert "Family Advisory Coverage" in html
    assert "Top Operator Action" in html
    assert "Next Actions" in html
    assert "5-Second Operator Kernel 바로 아래에서 approve -> align -> act 순서로 신규 진입 허용, surface alignment, server-side Top Operator Action을 한 strip으로 압축합니다. policy mutation이 아니라 reading priority입니다." in html
    assert "1. Approve" in html
    assert "2. Align" in html
    assert "3. Act / Top Operator Action" in html
    assert "Approval Strip Detail" in html
    assert "Approval Strip Next Move" in html
    assert "Approval Strip와 Top Opportunity / Top Blocker 다음 순서에서, portfolio/execution/family/mode/research context를 follow-up으로 읽습니다. strong kernel verdict면 expanded operating context는 접힌 상태로 둡니다." in html
    assert "Expanded Operating Context" in html
    assert "Experiment Routing" in html
    assert "kernel verdict가 monitor라서 expanded operating context를 기본 펼침 상태로 둡니다." in html
    assert "kernel verdict가 hold/manual_review/watch라서 expanded operating context는 approve/align/act 확인 전까지 기본 접힘 상태로 둡니다." in html
    assert "A/B Strategy Posture" in html
    assert "A remains anchor인지, B continuation이 research-only인지 guarded activation인지, 현재 mix가 여전히 A 집중인지까지 한 번에 읽습니다." in html
    assert "현재 A/B mix" in html
    assert "Promotion Operating Stack" in html
    assert "승격 review, remediation, clearance, reopen, semi-auto execution, history, research followthrough를 한 번에 읽습니다." in html
    assert "Live Candidate Review" in html
    assert "Global Live Candidate Review" in html
    assert "Global Headline" in html
    assert "Decision" in html
    assert "Headline Freshness" in html
    assert "Headline Evidence" in html
    assert "Attention Flags" in html
    assert "현재 우선 review 대상 live candidate가 없습니다." in html
    assert "남은 Guardrail Domain" in html
    assert "최근 Promotion Transition" in html
    assert "Promotion Case Inspector" in html
    assert "현재 headline family의 승격 case를 single-family inspector로 다시 압축해, target posture, write scope, remaining guardrails, next move를 바로 읽습니다." in html
    assert "Next Move" in html
    assert "Remaining Guardrails" in html
    assert "Cleared Guardrails" in html
    assert "Validation / Checklist Review Stack" in html
    assert "validation top-level summary와 checklist item status를 같은 표로 압축해서, raw JSON 없이 operator review stack을 읽습니다." in html
    assert "Validation Approve" in html
    assert "Validation Align" in html
    assert "Validation Act" in html
    assert "Checklist Approve" in html
    assert "Checklist Align" in html
    assert "Checklist Act" in html
    assert "Validation Case Inspector" in html
    assert "현재 symbol validation case를 money funnel, outcome attribution, outcome control, rollout, lifecycle, A/B posture, condition split, capture, allocator 기준으로 다시 압축해 operator가 한 카드로 읽습니다." in html
    assert "Approve" in html
    assert "Align" in html
    assert "Act" in html
    assert "Money Funnel" in html
    assert "Outcome Attribution" in html
    assert "Edge Experiment" in html
    assert "Edge Evolution" in html
    assert "Review Followup Ledger" in html
    assert "Edge Split Focus" in html
    assert "Edge Proof Posture" in html
    assert "fail_safe_claim" in html
    assert "post_proof_scale_spec_id" in html
    assert "capital_scale_review_allowed" in html
    assert "loss_driven_rewrite_allowed" in html
    assert "rollout_expansion_allowed" in html
    assert "alpha_generator_review_allowed" in html
    assert "signal_density_control_review_allowed" in html
    assert "execution_strategy_automation_review_allowed" in html
    assert "multi_strategy_expansion_review_allowed" in html
    assert "Recent Review Packet" in html
    assert "Operating Funnel KPIs" in html
    assert "Expected vs Realized R" in html
    assert "Money Leak Focus" in html
    assert "Top Condition Split" in html
    assert "Opportunity Capture" in html
    assert "Next Validation Move" in html
    assert "Operator Reading Order" in html
    assert "Runtime Quality Inspector" in html
    assert "최근 validation alert, retry queue, execution quality, reconciliation health를 한 카드로 압축해 runtime 운영 품질을 빠르게 읽습니다." in html
    assert "Latest Alert Approve" in html
    assert "Latest Alert Act" in html
    assert "Runtime Next Move" in html
    assert "Quality Drift Focus" in html
    assert "Signal Funnel Inspector" in html
    assert "현재 hard gate, softening 후보, rollout block, family/regime/session bottleneck에 money funnel과 outcome attribution까지 묶어서 홈 섹션에서 한 번에 읽도록 압축합니다." in html
    assert "Edge Experiment" in html
    assert "Edge Evolution" in html
    assert "Review Followup Ledger" in html
    assert "Top Family Bottleneck" in html
    assert "Top Regime Bottleneck" in html
    assert "Top Session Bottleneck" in html
    assert "Attribution Focus" in html
    assert "Review Packet History" in html
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
    assert "accepted / blocked 후보를 raw JSON 없이 읽기 위해, cluster, allocated risk, outcome bias, edge focus, capital allocator, A/B posture를 같은 표로 보여줍니다." in html
    assert "Portfolio Candidate Inspector" in html
    assert "대표 accepted row 1개와 blocked row 1개를 카드로 다시 압축해, risk, allocator, A/B posture, edge focus, session, reaction evidence를 바로 읽습니다." in html
    assert "Representative Accepted Candidate" in html
    assert "Representative Blocked Candidate" in html
    assert "Shadow Tilt" in html
    assert "runtime_signal_shadow_tilt unavailable" in html
    assert "apply_live=false" in html
    assert "Why This Row Matters" in html
    assert "Edge Focus" in html
    assert "Checklist Evidence Drilldown" in html
    assert "WARN / MANUAL / FAIL 체크를 evidence 중심으로 다시 펼쳐서, raw checklist payload 없이 operator review 포인트를 읽습니다." in html
    assert "Report Navigation" in html
    assert "validation / checklist / execution quality 리포트 파일을 raw JSON 없이 바로 열 수 있게 경로와 file link를 같이 보여줍니다." in html
    assert "Validation Report File" in html
    assert "Checklist Report File" in html
    assert "Execution Quality Report File" in html
    assert "Approval Strip Carryover" in html
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
    assert "live_candidate_promotion_readiness" in html
    assert "live_candidate_promotion_readiness_global" in html
    assert "promotion_decision" in html
    assert "operator_review_items" in html
    assert "attention_flags" in html
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
    assert "approval_strip_summary" in html
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
    assert "fast=true" in html
    assert "fetchOptionalJson" in html
    assert "source_unavailable" in html
    assert "operator-ui timeout" in html
    assert "/execution/quality" in html
