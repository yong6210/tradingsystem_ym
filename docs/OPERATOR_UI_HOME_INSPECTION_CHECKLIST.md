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
1. `Decision Summary`
2. `Approval Divergence`
3. `Top Operator Action`
4. `Top Opportunity / Top Blocker`
5. `Current Operating State`
6. `Mode / Deployment Inspector`
7. `Approval Alignment Inspector`
8. `Validation / Checklist Review Stack`
9. `Validation Case Inspector`
10. `Signal Funnel Inspector`
11. `Runtime Quality Inspector`
12. `Kill Condition Inspector`
13. `Policy / Lock Inspector`
14. `Intent / Exposure Inspector`
15. `A/B Strategy Posture`
16. `Promotion Operating Stack`
17. `Promotion Case Inspector`
18. `Alpha Research Inspector`
19. `Data Freshness / Source Inspector`
20. `Portfolio Candidate Drilldown`
21. `Portfolio Candidate Inspector`
22. `Checklist Evidence Drilldown`
23. `Report Navigation`

## 4. 첫 번째 판단
- `Approval Divergence`가 있으면 surface alignment를 먼저 본다.
- `dashboard`만 `GO`고 `validation / checklist`가 `NO_GO`면 신규 진입 허용으로 읽지 않는다.
- `Top Operator Action`은 reading priority다. 승인 명령이 아니다.
- `Mode / Deployment Inspector`에서 `new_entries_allowed=false`면 아래 기회 카드보다 gate reason을 우선 본다.

## 5. 수동 점검 항목
### 5.1 배포 정합성
- `dashboard deployment_go_no_go`
- `validation deployment_go_no_go`
- `checklist deployment_go_no_go`
- `dashboard playbook_action`
- `validation playbook_action`
- `checklist playbook_action`

합격 기준:
- `dashboard / validation / checklist`가 같은 방향을 가리키거나,
- 다르면 `Approval Divergence` 배너가 홈 최상단에 바로 보인다.

### 5.2 홈 inspector 존재 여부
- `Validation Case Inspector`
- `Runtime Quality Inspector`
- `Signal Funnel Inspector`
- `Alpha Research Inspector`
- `Kill Condition Inspector`
- `Policy / Lock Inspector`
- `Intent / Exposure Inspector`
- `Mode / Deployment Inspector`
- `Approval Alignment Inspector`
- `Data Freshness / Source Inspector`
- `Portfolio Candidate Inspector`

합격 기준:
- 위 패널이 모두 홈 화면에서 제목으로 바로 보인다.
- `Kill Condition Inspector`에는 최소 `Stop Review Verdict`, `Current Lock State`, `Kill Condition Next Move`가 같이 보여야 한다.

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
- `operator_ui_sections`
- `signal_funnel_snapshot`
- `next_steps`

우선 해석 규칙:
- `deployment_alignment == "DIVERGED"`면 rollout 판단을 다시 연다.
- `playbook_alignment == "DIVERGED"`면 operator action wording drift를 먼저 본다.
- `operator_ui_sections.missing_sections`가 비어 있지 않으면 UI regression으로 본다.

## 7. 실제 1차 dry-run에서 확인한 포인트
- 한 샘플에서 `dashboard=GO`, `validation/checklist=NO_GO`가 확인됐다.
- 그 상태는 버그 확정이 아니라, 현재 엔진이 `runtime candidate review 계속`과 `rollout 금지`를 동시에 말하는 상황으로 읽어야 한다.
- 그래서 홈 화면에는 `Approval Divergence` 배너가 반드시 바로 보여야 한다.

## 8. 산출물
- 수동 점검 기준 문서: 이 문서
- dry-run snapshot 스크립트: [collect_operator_surface_divergence_snapshot.py](/Users/yumin/Documents/trading/scripts/collect_operator_surface_divergence_snapshot.py)
- handoff brief 스크립트: [generate_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/generate_operator_session_brief.py)
- handoff notifier 스크립트: [notify_operator_session_brief.py](/Users/yumin/Documents/trading/scripts/notify_operator_session_brief.py)
- tick wrapper / cron 가이드: [OPERATOR_SESSION_BRIEF_AUTOMATION.md](/Users/yumin/Documents/trading/docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md)
- 기본 리포트 경로: `reports/operations/operator_surface_divergence/`
