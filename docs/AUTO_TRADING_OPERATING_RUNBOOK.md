# Auto Trading 운영 절차 (Living)

최종 갱신: 2026-03-25

## 1. 목적
- 자동매매 운영자가 매 세션마다 같은 순서로 상태를 확인하고, 같은 기준으로 신규 진입/중단/복구를 판단하게 만든다.
- source-of-truth를 `차트`가 아니라 `서버 runtime contract`로 고정한다.

## 2. Source Of Truth
- 차트/TradingView: mirror, not authority
- runtime 판단: `GET /execution/operator-dashboard`
- 브라우저 운영 화면: `GET /execution/operator-ui`
- 최종 승인: `POST /validation/report`, `POST /operations/checklist`
- 실행 제어: `GET /execution/safety-state`, `POST /execution/control/*`
- 실제 주문/포지션 truth: Binance + user-stream + reconciliation 결과

TradingView를 triage에 함께 쓴다면, mirror-only 사용법과 chart-side operator-priority 한계는 [docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md](/Users/yumin/Documents/trading/docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md)를 먼저 본다.

## 3. 운영자가 매번 답해야 하는 질문
1. 지금 신규 진입이 가능한가
2. 어떤 family / symbol만 허용되는가
3. block reason이 무엇인가
4. open order / open position / reconciliation mismatch가 건강한가
5. close-only 또는 kill-switch가 켜져 있는가

## 3A. 장중 운영 체크리스트
상단 operator surface는 5-Second Operator Kernel, Approval Strip, Top Opportunity / Top Blocker, Current Operating State 순서로 먼저 읽고, 그다음 대표 플랜, 현재 진입 가이드, 상세 운영 섹션으로 내려간다. promotion/research stack은 `Deferred Research / Promotion Stack` 안에서 kernel verdict가 약할 때만 후순위로 연다. kernel verdict가 `hold`, `manual_review`, `watch`면 Top Opportunity / Portfolio Candidate surface는 context-only로 읽고 approval/alignment/checklist 해석을 먼저 끝낸다. 같은 조건에서 `Current Operating State`는 expanded operating context만 나중에 연다.

1. `5-Second Operator Kernel`
2. `Approval Strip`
3. `Top Opportunity / Top Blocker`
4. `Current Operating State`
5. 그다음 `대표 플랜 / 현재 진입 가이드 / 상세 운영 섹션`

장중에 먼저 확인할 항목:
- `approval_strip_summary.approve_value`
- `approval_strip_summary.align_value`
- `approval_strip_summary.act_value`
- `validation_report.edge_experiment_review_summary.edge_state`
- `validation_report.edge_experiment_review_summary.entry_timing_preferred_variant`
- `validation_report.edge_experiment_review_summary.execution_style_preferred_variant`
- `validation_report.edge_experiment_review_summary.sample_maturity_state`
- `validation_report.edge_experiment_review_summary.next_sample_target_closed_trades`
- `validation_report.edge_experiment_review_summary.remaining_closed_trades_to_next_target`
- `validation_report.edge_experiment_review_summary.regime_dependency_state`
- `validation_report.edge_experiment_review_summary.strongest_regime`
- `validation_report.edge_experiment_review_summary.weakest_regime`
- `validation_report.edge_experiment_review_summary.edge_proof_goal_closed_trades`
- `validation_report.edge_experiment_review_summary.remaining_closed_trades_to_edge_proof_goal`
- `validation_report.edge_experiment_review_summary.edge_proof_posture`
- `validation_report.edge_experiment_review_summary.daily_edge_kpis`
- `validation_report.score_to_outcome_funnel_summary.operating_kpis`
- `validation_report.edge_evolution_rule_summary.evolution_state`
- `validation_report.edge_evolution_rule_summary.recommended_action`
- `validation_report.edge_evolution_rule_summary.recommendation_strength`
- `validation_report.edge_evolution_rule_summary.closed_loop_confirmation_state`
- `validation_report.edge_evolution_rule_summary.regime_guard_state`
- `validation_report.review_followup_ledger_summary.last_status`
- `validation_report.review_followup_ledger_summary.last_decision_status`
- `validation_report.review_followup_ledger_summary.last_effective_status`
- `validation_report.review_followup_ledger_summary.last_action`
- `validation_report.review_followup_ledger_summary.last_followup_command`
- `validation_report.operator_action_priority_summary.experiment_context.entry_timing_target`
- `validation_report.operator_action_priority_summary.experiment_context.execution_style_target`
- `validation_report.operator_action_priority_summary.experiment_execution_policy`
- `validation_report.operator_action_priority_summary.deferred_experiment_actions`
- `new_entries_allowed`
- `execution_degradation_advisory.status`
- `family_execution_degradation_advisory.top_family`
- `mode_advisory.family_top`
- `operator_action_priority.top_action`

장중 운영 규칙:
- `approval_strip_summary.approve_value`가 `approval usable`이 아니면 신규 진입 확장을 열지 않는다.
- 전역 `execution_degradation_advisory.status == "manual_review"`면 신규 확대보다 실행 품질 점검을 우선한다.
- `family_execution_degradation_advisory.top_family.status == "manual_review"`면 해당 family는 확대보다 family execution review를 우선한다.
- `mode_advisory`의 `research_only`와 `promotion_watch`는 운영 해석이다. 실제 mode 변경이나 live permission이 아니다.
- `alpha_research` next step은 research queue다. 실행 승인처럼 읽지 않는다.
- `operator_action_priority.top_action`은 operator reading priority다. live submit instruction이 아니다.
- `operator_action_priority.top_action_followup_command`와 `next_actions[].followup_command`가 비어 있지 않으면, split review는 그 command를 그대로 쓴다.
- `operator_action_priority.dedupe_suppressed_actions`가 비어 있지 않으면, review packet은 추천 자체가 없어진 게 아니라 ledger history 때문에 잠시 억제된 것이다. `fresh READY packet`, 직전 `NO_TARGET`, 최근 3회 연속 동일 packet` 중 어느 경우인지 같이 확인한다.
- `operator_action_priority.experiment_execution_policy.mode == single_active_experiment`면 split 실험은 항상 하나만 active로 해석한다. 동시에 `entry_timing`과 `execution_style`를 둘 다 열지 않는다.
- `operator_action_priority.deferred_experiment_actions`가 비어 있지 않으면 실험 후보가 사라진 게 아니라 다음 sample target까지 보류된 것이다.
- split review target이 있으면 `./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --days 7 --action auto`로 review packet부터 만든다.
- `review_followup_ledger.last_status`가 `NO_TARGET` 또는 `NO_REVIEW_ACTION_AVAILABLE`면 새 실험보다 target contract와 command carryover부터 고친다.
- `review_followup_ledger.last_decision_status`는 packet 생성 이후 사람이 붙인 후속 판단이다. `last_status`보다 늦게 들어온 신호일 수 있으니 둘이 다르면 `last_effective_status`를 최종 상태로 읽는다.
- `edge_evolution_rule.recommendation_strength == confirmed` 또는 `escalated`면 최근 packet 이후 새 closes가 같은 방향으로 누적됐다는 뜻이다. 이때만 `promote / reduce / kill-review` 해석을 강화한다.
- `edge_experiment_review.sample_maturity_state`가 `pre_directional`, `directional_only`, `review_ready`면 아직 edge proof가 아니다. 이 구간에서는 promote/reduce보다 close sample 축적을 우선한다.
- `edge_experiment_review.edge_proof_goal_closed_trades=100`을 넘기기 전에는 구조 완성과 별개로 edge claim을 쓰지 않는다. `remaining_closed_trades_to_edge_proof_goal > 0`이면 research posture를 유지한다.
- `edge_experiment_review.operating_discipline.framework_quality_state == framework_ready`여도 수익 증명과는 별개다. 이 상태는 “구조 평가 종료”가 아니라 “운용/실험 단계 진입”으로 읽는다.
- `edge_experiment_review.operating_discipline.system_mode == operate_and_experiment`면 이번 사이클의 대상은 시스템 개선보다 운영과 표본 축적이다.
- `edge_experiment_review.operating_discipline.primary_goal == find_first_verified_edge`면 이번 사이클의 목표는 구조 개선이 아니라 edge 검증이다.
- `edge_experiment_review.operating_discipline.evaluation_focus == after_cost_edge_only`면 판단 기준은 구조 quality가 아니라 after-cost closed-trade edge다.
- `edge_experiment_review.operating_discipline.minimum_closed_trades_for_edge_evaluation == 100`이면 100 closes 전 결론을 평가로 쓰지 않는다.
- `edge_experiment_review.operating_discipline.profit_claim_allowed == false`면 framework가 좋아 보여도 profitability wording을 쓰지 않는다.
- `edge_experiment_review.operating_discipline.structure_change_review_allowed == false`면 split 실험 중에는 구조 변경을 얼리고 close sample 누적을 우선한다.
- `edge_experiment_review.operating_discipline.early_loss_rewrite_embargo_active == true`면 초기 손실이나 흔들림만으로 전략 구조를 바꾸지 않는다. 최소한 close sample이 더 쌓일 때까지 같은 실험을 유지한다.
- `edge_experiment_review.operating_discipline.loss_driven_rewrite_allowed == false`면 손실을 이유로 한 구조 rewrite는 금지 상태로 읽는다.
- `edge_experiment_review.operating_discipline.rollout_expansion_allowed == false`면 edge가 좋아 보여도 확장하지 않는다. `stable_across_regimes`가 아니면 expansion review를 열지 않는다.
- `edge_experiment_review.operating_discipline.improvement_priority == prove_single_edge_before_density_or_strategy_expansion`이면 지금 단계의 목표는 density tuning이나 multi-strategy 확장이 아니라 단일 edge proof다.
- `edge_experiment_review.operating_discipline.current_system_identity == edge_proof_engine`이면 지금 시스템은 alpha를 새로 만들기보다 first verified edge를 증명하는 단계로 읽는다.
- `edge_experiment_review.operating_discipline.next_system_stage == post_first_verified_edge`면 alpha generator / execution automation / density control / multi-strategy는 proof 뒤의 backlog다.
- `edge_experiment_review.operating_discipline.resilience_claim == harder_to_fail_from_self_deception`이면 이 구조는 착각으로 망하기 어렵게 만든 것이지 fail-safe를 보장하는 것이 아니다.
- `edge_experiment_review.operating_discipline.fail_safe_claim == false`를 유지한다. 구조가 좋아도 성패는 계속 `market_edge`, `execution_quality`, `operating_discipline`에 달려 있다.
- `edge_experiment_review.operating_discipline.alpha_generator_review_allowed == false`면 새 alpha-generation layer 설계는 아직 live 우선순위가 아니다.
- `edge_experiment_review.operating_discipline.capital_scale_review_allowed == false`면 proof 이후 scale curve review도 아직 금지 상태다.
- `edge_experiment_review.operating_discipline.signal_density_control_review_allowed == false`면 target trades/day tuning은 아직 보류한다.
- `edge_experiment_review.operating_discipline.execution_strategy_automation_review_allowed == false`면 passive-vs-market을 자동 선택하는 execution layer도 아직 보류한다.
- `edge_experiment_review.operating_discipline.multi_strategy_expansion_review_allowed == false`면 A_ONLY 탈출이나 전략 다변화 review도 아직 보류한다.
- `edge_experiment_review.operating_discipline.capital_scale_review_allowed == true`가 되면 [EDGE_PROOF_CAPITAL_SCALE_CONTRACT.md](/Users/yumin/Documents/trading/docs/EDGE_PROOF_CAPITAL_SCALE_CONTRACT.md)를 기준으로 review한다.
- `score_to_outcome_funnel_summary.operating_kpis`는 이제 설명용이 아니라 daily 운영 KPI다. 최소한 `runtime_to_accepted`, `submitted_to_filled`, `filled_to_closed`, `closed_to_post_cost_profitable`, `closed_trades_per_day`를 같이 본다.
- `edge_experiment_review.experiment_sequence.state`는 실험 순서를 고정한다. 기본 순서는 `entry_timing -> execution_style -> exit_optimization`이다.
- `edge_experiment_review.experiment_sequence.current_priority_experiment == entry_timing`이면 `early_limit vs reaction_confirmed`를 먼저 잠그고, 그 전에는 exit review를 해석하지 않는다.
- `edge_experiment_review.experiment_sequence.current_priority_experiment == execution_style`이면 `passive_limit vs market`를 잠그는 단계다. 이 구간에서도 exit review는 보류다.
- `edge_experiment_review.experiment_sequence.exit_optimization_allowed == false`면 alpha-research가 `run_shadow_exit_review`나 `run_shadow_exit_timing_review`를 추천해도 sequencing hint로만 읽고 현재 split cycle을 먼저 끝낸다.
- `edge_experiment_review.regime_dependency_state == regime_dependent`면 strongest regime에서 좋아 보여도 weakest regime를 따로 본다. 이 상태에선 promotion을 범용 edge처럼 읽지 않는다.
- `edge_evolution_rule.regime_guard_state == promotion_blocked_by_regime_dependency`면 preferred branch가 좋아 보여도 weakest regime evidence가 모일 때까지 research-only로 유지한다.
- session brief와 stage monitor의 `entry_timing_review_target` / `execution_style_review_target` 줄에도 같은 followup command가 실린다. handoff에서는 그 command를 source-of-truth로 쓴다.
- session brief와 stage monitor의 `review_followup_ledger` 줄은 가장 최근 review packet 이력이다. 추천이 아니라 이미 생성된 packet history로 읽는다.

실제 edge 실험 순서:
1. `operator_action_priority.top_action_followup_command` 또는 `entry_timing_review_target` / `execution_style_review_target` command로 review packet을 만든다.
2. `experiment_execution_policy.active_action`만 이번 사이클의 실험으로 연다. 다른 split 후보는 `deferred_experiment_actions`에 남겨둔다.
3. packet이 가리킨 split을 실제 시장에서 관찰한다. 이 단계는 코드나 backfill로 대체하지 않는다.
4. 새 closed trade를 누적해서 split별 close sample을 늘린다.
5. `next_sample_target_closed_trades`를 넘겼는지 확인한다.
6. 그 다음에만 `edge_experiment_review`를 다시 읽는다.
7. `edge_experiment_review.experiment_sequence`가 아직 `entry_timing_first` 또는 `execution_style_second`면 exit optimization review는 deferred로 유지한다.
8. 이어서 `edge_evolution_rule`를 다시 읽는다.
9. `promote / reduce / kill-review` 해석은 위 순서가 끝난 뒤에만 한다.
10. packet이 실제로 확인되거나 기각됐으면 `scripts/run_split_review_followup.py --transition-status ...`로 같은 ledger에 후속 status를 남긴다.

표본 목표:
- `4 closes`
  - directional read만 가능
- `6 closes`
  - review decision은 가능하지만 아직 약함
- `8 closes`
  - promote/reduce review를 읽기 시작할 수 있는 최소선
- `20 closes`
  - operator sample floor
- `50 / 100 / 300 closes`
  - early / emerging / credible edge 구간

해석 금지 규칙:
- framework completion과 edge proof를 같은 문장으로 묶지 않는다.
- `profit_claim_allowed == false`면 “좋은 시스템” 평가는 가능해도 “돈 버는 edge” 평가는 하지 않는다.
- `structure_change_review_allowed == false`면 실험 중 feature 추가나 구조 리팩터보다 sample 축적을 우선한다.
- `system_mode == operate_and_experiment`면 이 저장소는 더 이상 구조 개선 점수로 평가하지 않고, after-cost edge sample 누적으로 평가한다.

실험 보류 조건:
- `close_only_active == true`면 split 실험 확대를 열지 않는다.
- `validation_report` 또는 `operations/checklist`가 `NO_GO`면 packet generation은 가능해도 실험 해석은 보류한다.
- `edge_experiment_review.edge_state == insufficient_edge_measurement` 또는 `edge_evolution_rule.evolution_state == insufficient_sample`이면 edge 해석보다 close sample 축적을 우선한다.
- `operator_action_priority.experiment_execution_policy.active_action == none`이면 이번 세션은 실험 실행 단계가 아니라 sample 축적 또는 blocker 정리 단계다.
- accepted candidate가 없고 `review_followup_ledger.last_status`가 `NO_REVIEW_ACTION_AVAILABLE`이면, 현재 세션은 실험 실행 단계가 아니라 blocker 정리 단계로 읽는다.

ledger transition 예시:
- `ACKED`
  - packet을 운영자가 확인했고 follow-up을 시작했다.
- `COMPLETED`
  - review packet 기준 조사나 비교가 끝났지만 promote/reduce/kill 방향은 아직 확정하지 않았다.
- `PROMOTE_CONFIRMED`, `REDUCE_CONFIRMED`, `KILL_REVIEW_ESCALATED`
  - 확인된 outcome을 ledger에 닫아서 이후 `edge_evolution_rule`가 closed-loop 강화에 사용할 수 있게 한다.
- `REJECTED`
  - packet 방향이 잘못됐거나 더 이상 유효하지 않아서 닫았다.

chart-side triage 예시:
- 차트가 `CONFIRM`을 보여도 server-side `Top Operator Action`이 `review_execution_drag_before_expansion`이면, 차트는 context only로 두고 서버 review를 먼저 따른다.
- 차트가 `RESEARCH`를 보여도 server-side `Alpha-Research Next Step`이 `softening_review`이면, chart-side triage는 research queue hint일 뿐이고 실제 research progression은 서버에서 이어간다.
- 차트와 서버가 다르면 항상 서버를 따른다.

## 3B. 장마감 리뷰 포맷
장마감에는 아래 순서로 정리한다.

1. 승인 상태
- `deployment_go_no_go`
- `deployment_code`
- `playbook_action`

2. 실행 상태
- `execution_degradation_advisory.status`
- `family_execution_degradation_advisory.top_family`
- `fill_rate`
- `forced_exit_ratio`
- `information_failure_ratio`
- `time_failure_ratio`

3. outcome funnel
- `runtime_candidates`
- `accepted_candidates`
- candidate row `edge_experiment_focus.edge_state`
- candidate row `edge_experiment_focus.entry_timing_preferred_variant`
- candidate row `edge_experiment_focus.execution_style_preferred_variant`
- `submitted`
- `filled`
- `closed`
- `profitable`
- `baseline_cost_profitable`

4. 분해 리뷰
- family별 `baseline_cost_profitable_rate_from_closed`
- regime별 병목
- session별 병목

5. 개선 루프
- `operator_action_priority.top_action`이 실제로 맞는 우선순위였는지
- `softening_candidate_review.top_candidate`
- `promotion_watchlist.watch_items`

## 3C. 주간 전략 리뷰 포맷
주간 리뷰는 `유지 / watch / research-only / promotion-watch` 판단을 위해 쓴다.

전역 리뷰:
- `baseline_cost_profitable` 추세
- `execution_degradation_advisory` 반복 여부
- `deployment_go_no_go` 변화 패턴

family 리뷰:
- `family_execution_degradation_advisory`
- `post_cost_alignment`
- `forced_exit_ratio`
- `information_failure_ratio`
- `time_failure_ratio`

개선 리뷰:
- `alpha_research_evidence_summary`
- `false_negative_suspects`
- `softening_candidate_review`
- `promotion_watchlist`

다음 주 액션:
- `top operator action` 1개
- `next_actions` 2~3개
- 새 hard gate 변경보다 evidence 축적과 review를 우선한다.

## 3D. Authority Boundary Reminder
- 차트/TradingView는 mirror다. approval이나 execution truth가 아니다.
- `operator_action_priority`는 reading priority다. live submit instruction이 아니다.
- `mode_advisory`, `family_execution_degradation_advisory`, `alpha_research`는 모두 advisory-only다.
- 최종 승인 surface는 계속 `POST /validation/report`와 `POST /operations/checklist`다.

## 3E. 실제 돈 기준 Family Edge Review
- A/B edge review는 `설계 평가`가 아니라 `after-cost edge 유지 여부`를 보는 운영 루틴이다.
- daily는 `45d`, weekly는 `90d`, monthly는 `180d` 창으로 본다.
- monthly headline은 아래 combined review로 먼저 본다.
```bash
./.venv/bin/python scripts/run_live_alpha_operating_review.py --days 180
```
- A review:
```bash
./.venv/bin/python scripts/run_strategy_family_edge_review.py \
  --family sweep_reversal \
  --peer-family trend_continuation \
  --days 45 \
  --no-write-report
```
- B review:
```bash
./.venv/bin/python scripts/run_strategy_family_edge_review.py \
  --family trend_continuation \
  --peer-family sweep_reversal \
  --days 45 \
  --no-write-report
```
- cadence와 해석 규칙은 [docs/LIVE_ALPHA_OPERATING_ROUTINE.md](/Users/yumin/Documents/trading/docs/LIVE_ALPHA_OPERATING_ROUTINE.md)를 따른다.

## 4. 세션 시작 전 점검
### 4.1. 프로세스/헬스
```bash
curl -s "http://127.0.0.1:8000/health/live" | jq
curl -s "http://127.0.0.1:8000/health/ready" | jq
```

### 4.2. 운영 요약
```bash
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?universe=usdc_perp_top30&portfolio_limit=10&intent_limit=10&reconcile_limit=10&days=7" | jq
```

```bash
open "http://127.0.0.1:8000/execution/operator-ui?symbol=BTCUSDC&universe=usdc_perp_top30&days=7"
```

반드시 확인:
- `new_entries_allowed`
- `blocking_reason_code`, `blocking_reason_message`
- `kill_switch_active`
- `close_only_active`
- `recent_reconciliation_summary`
- `rollout_policies`

브라우저 홈 화면 점검 순서는 [docs/OPERATOR_UI_HOME_INSPECTION_CHECKLIST.md](/Users/yumin/Documents/trading/docs/OPERATOR_UI_HOME_INSPECTION_CHECKLIST.md)를 따른다.

### 4.3. 승인/배포 체크
```bash
curl -s -X POST "http://127.0.0.1:8000/validation/report?symbol=BTCUSDC" | jq '{
  deployment_go_no_go,
  deployment_code,
  deployment_message,
  playbook_go_no_go,
  playbook_action
}'

curl -s -X POST "http://127.0.0.1:8000/operations/checklist?symbol=BTCUSDC" | jq '{
  deployment_go_no_go,
  deployment_code,
  deployment_message,
  playbook_go_no_go,
  playbook_action
}'
```

규칙:
- `deployment_go_no_go != "GO"`면 신규 진입을 열지 않는다.
- `playbook_go_no_go == "NO_GO"`면 수동 override 없이 중단한다.

surface divergence를 다시 수집할 때:
```bash
./.venv/bin/python scripts/collect_operator_surface_divergence_snapshot.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7
```

운영 handoff용 brief를 남길 때:
```bash
./.venv/bin/python scripts/generate_operator_session_brief.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7
```

brief를 Discord handoff message로 바꿔 볼 때:
```bash
./.venv/bin/python scripts/notify_operator_session_brief.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7 \
  --channel system \
  --brief-mode shift-start \
  --dry-run
```

장 종료 handoff는:
```bash
./.venv/bin/python scripts/notify_operator_session_brief.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7 \
  --channel system \
  --brief-mode shift-end \
  --dry-run
```

반복 실행은 [docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md](/Users/yumin/Documents/trading/docs/OPERATOR_SESSION_BRIEF_AUTOMATION.md)를 따른다.
macOS `launchd`로 분리 실행하려면 `shift-start`와 `shift-end` 전용 plist 두 개를 쓴다.
운영 중에는 아래 health check로 두 agent exit code와 latest artifact freshness를 같이 본다.

```bash
./.venv/bin/python scripts/check_operator_session_brief_automation.py --strict
```

전송 채널 준비 상태는 아래 preflight로 따로 점검한다.

```bash
./.venv/bin/python scripts/check_operator_session_brief_delivery_preflight.py --strict
```

실제 외부 전송 전환은 `dry_run` 해제만으로는 안 되고, 아래처럼 live-send guard도 같이 켠다.

```bash
launchctl unsetenv OPERATOR_BRIEF_DRY_RUN
launchctl setenv OPERATOR_BRIEF_ALLOW_LIVE_SEND 1
```

해석 규칙:
- `deployment_alignment == "DIVERGED"`면 dashboard와 validation/checklist를 다시 같은 시점으로 읽는다.
- `playbook_alignment == "DIVERGED"`면 wording drift 여부를 먼저 확인한다.
- divergence snapshot 안의 `Dashboard / Validation / Checklist` 구간은 per-surface `approve / align / act` 줄로 읽는다.
- `operator_ui_sections.missing_sections`가 비어 있지 않으면 UI regression으로 본다.

## 5. 후보 검토 절차
### 5.1. 스캐너
```bash
curl -s "http://127.0.0.1:8000/scanner/top?universe=usdc_perp_top30&limit=10" | jq
```

우선순위:
1. `deployment_go_no_go`
2. `strategy_family`
3. `recommended_risk_r`
4. `expected_ev_at_recommended_size_r`
5. `block_reason_message`

### 5.2. 계획 상세
```bash
curl -s "http://127.0.0.1:8000/plans/top?symbol=BTCUSDC&tf=5m&limit=5&refresh=true" | jq
```

보는 항목:
- `entry_model`
- `entry_price / sl / tp1 / tp2 / tp3`
- `expected_win_prob`
- `expected_ev_r`
- `recommended_risk_r`
- `strategy_family`
- `strategy_mode`

### 5.3. PAPER lineage drill
`MICRO_LIVE` 직전 blocker가 `threshold_lineage_winner_unresolved`일 때는 수동으로 family를 찾기보다 아래 helper를 먼저 돌린다.

```bash
./.venv/bin/python scripts/run_paper_candidate_drill.py --submit-paper
```

의미:
- universe sync
- scanner에서 `trend_continuation` / `sweep_reversal` family만 추림
- top eligible candidate에 대해 `preview -> approve -> order-intents`
- `--submit-paper`가 있으면 `live=false` PAPER submit까지 수행

규칙:
- `legacy_zone_plan`은 lineage 축적 대상이 아니므로 PAPER lineage drill 성공으로 보지 않는다.
- `eligible_candidate_found=FAIL`이면 세션 문제이므로 London/New York에 다시 돌린다.
- `approval_for_paper=FAIL` 또는 `intent_submit_ready=FAIL`이면 rollout/approval block reason부터 해결한다.
- drill payload의 `approval_strip_summary`를 먼저 읽고, 그다음 `candidate_edge_experiment_focus`와 `approval_state / allowed_execution_mode`로 submit 가능 여부와 split-test focus를 확인한다.

### 5.4. PAPER lineage watcher
세션이 올 때까지 사람이 반복 실행하지 않으려면 watcher helper를 쓴다.

```bash
./.venv/bin/python scripts/watch_paper_candidate_drill.py \
  --interval-seconds 900 \
  --max-attempts 8 \
  --submit-paper
```

의미:
- 내부적으로 `scripts/run_paper_candidate_drill.py --no-write-report`를 주기적으로 반복 호출한다.
- `trend_continuation` / `sweep_reversal` family candidate가 처음 뜨는 시점까지 감시한다.
- `--submit-paper`를 주면 eligible candidate가 잡힌 첫 시점에 `live=false` PAPER submit까지 이어진다.
- 최종 watcher payload는 top-level `edge_experiment_review`와 `candidate_edge_experiment_focus`를 같이 싣기 때문에 nested final_result를 열지 않아도 현재 split-test focus를 바로 읽을 수 있다.

해석:
- `FOUND_ELIGIBLE_CANDIDATE`: lineage 축적용 family 후보가 잡혔고, 필요 시 PAPER submit까지 진행됐다.
- `NO_ELIGIBLE_CANDIDATE`: 현재 세션/시장 상태에서 lineage 대상 family가 뜨지 않았다.

규칙:
- watcher는 live 승격 도구가 아니라 lineage 축적 자동화 도구다.
- `legacy_zone_plan`은 여전히 lineage 성공으로 계산하지 않는다.
- 결과는 `reports/operations/paper_candidate_watch/*`에 저장한다.

## 6. 실행 절차
### 6.1. 실행용 preview
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/plans/preview" \
  -H "Content-Type: application/json" \
  -d '{"plan_id":"<PLAN_ID>"}' | jq
```

### 6.2. 승인 확인
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/approve-plan" \
  -H "Content-Type: application/json" \
  -d '{"plan_id":"<PLAN_ID>"}' | jq
```

반드시 확인:
- `approval_state`
- `allowed_execution_mode`
- `deployment_go_no_go`
- `playbook_action`
- `approval_reasons`

### 6.3. intent 생성
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/order-intents" \
  -H "Content-Type: application/json" \
  -d '{"plan_id":"<PLAN_ID>","execution_mode":"PAPER"}' | jq
```

반드시 확인:
- `submit_decision`
- `decision_reason_code`
- `allowed_execution_mode`
- `deployment_*`
- `playbook_*`

### 6.4. 제출
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/submit" \
  -H "Content-Type: application/json" \
  -d '{"intent_id":"<INTENT_ID>","live":false}' | jq
```

규칙:
- `MICRO_LIVE` 전까지는 기본 `live=false`
- `live=true`는 `BINANCE_TRADE_LIVE_ENABLED=true`와 approval/rollout/safety 조건이 모두 맞을 때만 사용

## 7. 제출 후 모니터링
### 7.1. operator dashboard
```bash
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?symbol=BTCUSDC&days=7" | jq
```

확인:
- `recent_intents`
- `open_orders`
- `open_positions`
- `recent_reconciliation_events`
- `execution_quality_summary`

### 7.2. 실행 품질
```bash
curl -s "http://127.0.0.1:8000/execution/quality?symbol=BTCUSDC&days=30&write_report=false" | jq
```

### 7.3. 포트폴리오 상태
```bash
curl -s "http://127.0.0.1:8000/portfolio/budget?universe=usdc_perp_top30&limit=20&write_report=false" | jq
```

## 8. 이상 상황 대응
### 8.1. reconciliation 이상
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/reconcile?auto_resolve=true&apply_lock=true" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDC"}' | jq
```

규칙:
- `healthy == false`면 신규 진입 중단
- `lock_applied == true`면 close-only 전환 여부를 즉시 판단

### 8.2. kill-condition dry-run / explicit-arm
proposal-only dry-run:

```bash
./.venv/bin/python scripts/run_kill_condition_automation.py \
  --symbol BTCUSDC \
  --universe usdc_perp_top30 \
  --days 7
```

explicit-arm live apply 절차는 [docs/KILL_CONDITION_AUTOMATION_LIVE_RUNBOOK.md](/Users/yumin/Documents/trading/docs/KILL_CONDITION_AUTOMATION_LIVE_RUNBOOK.md)를 따른다.

### 8.3. close-only
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/close-only" \
  -H "Content-Type: application/json" \
  -d '{"active":true,"reason_message":"Manual close-only during incident.","updated_by":"operator"}' | jq
```

### 8.4. kill-switch
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/kill-switch" \
  -H "Content-Type: application/json" \
  -d '{"active":true,"reason_message":"Manual global kill-switch.","updated_by":"operator"}' | jq
```

## 9. 세션 종료 후 확인
1. `GET /execution/operator-dashboard`로 open order / open position / active lock 확인
2. `GET /execution/quality`로 slippage, fill-rate, forced exit 비율 확인
3. `POST /validation/report`로 최신 deployment language와 stress 상태 확인
4. 필요한 경우 `GET /alerts/metrics`로 validation alert / retry queue / channel SLO 확인
5. 첫 실제 live 세션 종료 후 pruning 재평가:
```bash
./.venv/bin/python scripts/run_post_live_pruning_review.py --symbol BTCUSDC --days 7
```
   생성되는 pruning review는 `Approval Surfaces` 섹션에서 `dashboard / validation / checklist`를 같은 `approve -> align -> act` vocabulary로 다시 요약하고, `Edge Experiment` 섹션에서 현재 split-test focus를 advisory-only로 함께 보여준다.

## 10. 운영 원칙
- 차트는 mirror다. 서버 승인보다 우선하지 않는다.
- 신규 진입은 `approval -> intent -> submit` 순서를 건너뛰지 않는다.
- mismatch, stale stream, missing stop 같은 runtime 이상은 “나중에 보기”가 아니라 즉시 lock/close-only 판단 대상이다.
- live 문제를 paper에서 재현 가능하게 유지하는 것이 운영 안정성의 핵심이다.
