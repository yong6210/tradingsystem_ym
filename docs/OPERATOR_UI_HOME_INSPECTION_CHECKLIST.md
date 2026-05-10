# Operator UI Home Inspection Checklist

최종 갱신: 2026-03-24

## 1. 목적
- `GET /execution/operator-ui` 홈 화면을 브라우저에서 같은 순서로 읽게 만든다.
- `dashboard / validation / checklist` 사이의 surface divergence를 별도 dry-run snapshot으로 다시 수집하게 만든다.
- UI wording, source freshness, report navigation이 실제 운영에 충분한지 빠르게 점검하게 만든다.

## 2. 사전 준비
```bash
open "http://127.0.0.1:8000/execution/operator-ui?symbol=BTCUSDC&universe=usdc_perp_top30&days=7"
```

dry-run divergence snapshot:
```bash
./.venv/bin/python scripts/collect_operator_surface_divergence_snapshot.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7
```

handoff brief 생성:
```bash
./.venv/bin/python scripts/generate_operator_session_brief.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7
```

handoff message dry-run:
```bash
./.venv/bin/python scripts/notify_operator_session_brief.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7 \
  --channel system \
  --brief-mode shift-start \
  --dry-run
```

shift-end handoff message dry-run:
```bash
./.venv/bin/python scripts/notify_operator_session_brief.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7 \
  --channel system \
  --brief-mode shift-end \
  --dry-run
```

## 3. 홈 화면 읽는 순서
1. `5-Second Operator Kernel`
2. `Approval Strip`
3. `Top Opportunity / Top Blocker`
4. `Current Operating State`
5. `Mode / Deployment Inspector`
6. `Approval Alignment Inspector`
7. `Validation / Checklist Review Stack`
8. `Validation Case Inspector`
9. `Signal Funnel Inspector`
10. `Runtime Quality Inspector`
11. `Kill Condition Inspector`
12. `Policy / Lock Inspector`
13. `Intent / Exposure Inspector`
14. `Deferred Research / Promotion Stack`
15. `A/B Strategy Posture`
16. `Promotion Operating Stack`
17. `Live Candidate Review`
18. `Global Live Candidate Review`
19. `Promotion Case Inspector`
20. `Alpha Research Inspector`
21. `Data Freshness / Source Inspector`
22. `Portfolio Candidate Drilldown`
23. `Portfolio Candidate Inspector`
24. `Checklist Evidence Drilldown`
25. `Report Navigation`

## 4. 첫 번째 판단
- `5-Second Operator Kernel`에서 `money funnel -> outcome attribution -> outcome control -> rollout` 순서를 먼저 읽는다.
- `Validation / Checklist Review Stack`, `Validation Case Inspector`, `Signal Funnel Inspector`에서는 `edge_experiment_review`가 `watch/fragile`이면 entry timing / execution style split을 먼저 읽고 구조 변경은 뒤로 미룬다.
- 같은 위치에서 `edge_evolution_rule`가 `reduce_candidate`나 `edge_kill_review`면 split hint보다 먼저 allocation/kill review 언어를 본다.
- `Portfolio Candidate Drilldown`과 `Portfolio Candidate Inspector`에서는 row-level `edge_experiment_focus`가 있으면 `edge_state -> entry_timing_preferred_variant -> execution_style_preferred_variant` 순서로 보고, candidate attractiveness보다 split-test hint를 먼저 읽는다.
- 여기서 `Money Leak`, `Drag Source`, `approval_penalty_tier`, `rollout recommendation`이 동시에 악화되면 아래 promotion stack보다 먼저 rollout 보수화 해석을 본다.
- `Approval Strip`에서 `Approve -> Align -> Act`를 읽고, 진입 허용 여부와 surface drift를 같은 줄에서 끝낸다.
- `Deferred Research / Promotion Stack`이 기본 접힘 상태면, kernel verdict가 `hold`, `manual_review`, `watch` 중 하나라는 뜻으로 읽고 core runtime/approval 해석을 먼저 끝낸다.
- kernel verdict가 `hold`, `manual_review`, `watch`면 `Top Opportunity`, `Portfolio Candidate Drilldown`, `Portfolio Candidate Inspector`는 context-only surface로 읽고 `Approval Alignment Inspector`와 `Validation / Checklist Review Stack`을 먼저 끝낸다.
- `Current Operating State`는 `Expanded Operating Context`로 읽고, 접혀 있으면 approval strip과 기회/차단 해석을 끝낸 뒤에만 연다.
- `Current Operating State`와 `Approval Alignment Inspector`의 `Experiment Routing`이 보이면 `entry/execution split -> symbol/status/family` 순서로 읽고, 추상 실험 제안이 아니라 row-level target으로 해석한다.
- `dashboard`만 `GO`고 `validation / checklist`가 `NO_GO`면 신규 진입 허용으로 읽지 않는다.
- `Top Operator Action`은 reading priority다. 승인 명령이 아니다.
- `Mode / Deployment Inspector`에서 `new_entries_allowed=false`면 아래 기회 카드보다 gate reason을 우선 본다.
- `Live Candidate Review`는 선택 심볼 상태이고 `Global Live Candidate Review`는 전역 승격 상태다. 선택 심볼이 `WAIT`여도 global이 `BLOCKED`면 live 승격 판단은 global block을 우선한다.

## 5. 수동 점검 항목
### 5.1 배포 정합성
- `dashboard approval_strip_summary.approve_value`
- `validation approval_strip_summary.approve_value`
- `checklist approval_strip_summary.approve_value`
- `dashboard approval_strip_summary.act_value`
- `validation approval_strip_summary.act_value`
- `checklist approval_strip_summary.act_value`

합격 기준:
- `dashboard / validation / checklist`가 같은 방향을 가리키거나,
- 다르면 `Approval Strip`의 `Align` 요약에 drift와 next move가 바로 보인다.
- `Mode / Deployment Inspector`와 `Approval Alignment Inspector`도 raw `deployment_go_no_go / playbook_action` 조합이 아니라 `approve -> align -> act` wording을 그대로 보여준다.
- `Validation / Checklist Review Stack`, `Validation Case Inspector`, `Runtime Quality Inspector`에서도 같은 wording이 반복되어야 한다.
- `Validation / Checklist Review Stack`에는 `Edge Experiment Review`가 보여야 하고 `edge_state`, `entry_timing_preferred_variant`, `execution_style_preferred_variant`를 raw JSON 없이 읽을 수 있어야 한다.
- 같은 위치에서 `Review Followup Ledger`도 보여야 하고 `last_status`, `last_action`, `last_followup_command`를 raw JSON 없이 읽을 수 있어야 한다.

### 5.2 홈 inspector 존재 여부
- `Validation Case Inspector`
- `Runtime Quality Inspector`
- `Signal Funnel Inspector`
- `Deferred Research / Promotion Stack`
- `Alpha Research Inspector`
- `Kill Condition Inspector`
- `Policy / Lock Inspector`
- `Intent / Exposure Inspector`
- `Mode / Deployment Inspector`
- `Approval Alignment Inspector`
- `Data Freshness / Source Inspector`
- `Portfolio Candidate Inspector`
- `Live Candidate Review`
- `Global Live Candidate Review`

합격 기준:
- 위 패널이 모두 홈 화면에서 제목으로 바로 보인다.
- `Kill Condition Inspector`에는 최소 `Stop Review Verdict`, `Current Lock State`, `Kill Condition Next Move`가 같이 보여야 한다.
- `Live Candidate Review`에는 `Decision`, `Global Decision`, `Global Headline`이 보여야 한다.
- `Global Live Candidate Review`에는 전역 `operator_review_items`가 표로 보여야 한다.
- 자세한 해석은 [LIVE_CANDIDATE_READINESS_CONTRACT.md](/Users/yumin/Documents/trading/docs/LIVE_CANDIDATE_READINESS_CONTRACT.md)를 따른다.

### 5.3 근거 문서 이동
- `Report Navigation`
- `Validation Report File`
- `Checklist Report File`
- `Execution Quality Report File`

합격 기준:
- 경로가 비어 있지 않거나, 비어 있을 때도 source endpoint fallback이 같이 보인다.

### 5.4 freshness / source
- `Dashboard Generated`
- `Validation Generated`
- `Checklist Generated`
- `Execution Quality Generated`
- `Source Flow`
- `Freshness Note`

합격 기준:
- generated timestamp 또는 `missing` 상태가 명시된다.
- source/report path가 둘 다 비어 있는 silent blank 상태가 없어야 한다.

## 6. divergence snapshot 해석
스크립트는 다음을 같이 보여준다.
- `deployment_alignment`
- `playbook_alignment`
- `dashboard_summary`
- `validation_summary`
- `checklist_summary`
- `dashboard_summary.approval_strip_summary`
- `validation_summary.approval_strip_summary`
- `checklist_summary.approval_strip_summary`
- `operator_ui_sections`
- `signal_funnel_snapshot`
- `next_steps`

우선 해석 규칙:
- `deployment_alignment == "DIVERGED"`면 rollout 판단을 다시 연다.
- `playbook_alignment == "DIVERGED"`면 operator action wording drift를 먼저 본다.
- `Dashboard / Validation / Checklist` 구간은 raw `deployment_go_no_go / playbook_action` 덤프가 아니라 per-surface `approve / align / act` 줄로 읽는다.
- `operator_ui_sections.missing_sections`가 비어 있지 않으면 UI regression으로 본다.

## 7. 실제 1차 dry-run에서 확인한 포인트
- 한 샘플에서 `dashboard=GO`, `validation/checklist=NO_GO`가 확인됐다.
- 그 상태는 버그 확정이 아니라, 현재 엔진이 `runtime candidate review 계속`과 `rollout 금지`를 동시에 말하는 상황으로 읽어야 한다.
- 그래서 홈 화면에는 `Approval Strip`의 `Align` 요약이 반드시 바로 보여야 한다.

## 8. 산출물
- 수동 점검 기준 문서: 이 문서
- dry-run snapshot 스크립트: [collect_operator_surface_divergence_snapshot.py](/Users/yumin/Documents/trading/scripts/collect_operator_surface_divergence_snapshot.py)
- handoff brief 스크립트: [generate_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/generate_operator_session_brief.py)
- handoff notifier 스크립트: [notify_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/notify_operator_session_brief.py)
- tick wrapper / cron 가이드: [OPERATOR_SESSION_BRIEF_AUTOMATION.md](/Users/yumin/Documents/trading/docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md)
- 기본 리포트 경로: `reports/operations/operator_surface_divergence/`
