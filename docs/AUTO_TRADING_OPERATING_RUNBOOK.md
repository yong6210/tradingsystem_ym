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
- `Trading entry surface alert`는 그 자체가 주문 트리거가 아니다. 메시지의 `live_order_candidates`, `blocked_live_candidates`, `operator_action.state`를 먼저 본다. `live_order_candidates=0`이고 `operator_action.state=context_only_outside_live_route`면 live route 밖 context row가 보인다는 뜻이다. count가 없는 legacy entry surface payload는 `[모니터링] ... 진입 표면 상태`로 표시되어야 한다.
- no-order 판단은 current runtime window와 lookback을 분리한다. 현재 window가 `live_intents=0/submit_ready=0/submissions=0`이면 아직 submit 경로 실패는 아니다. 다만 lookback에 후보가 있었고 모두 차단됐다면 `sir_pre_restart_expected_orders_advisory`를 historical context로 남기고, 알림성 `WATCH`로 반복 호출하지 않는다. 다음 fresh 후보가 `submit_ready`까지 가는지 확인한다.
- 주문 가능 여부의 운영 truth는 `live_candidate_promotion_readiness`다. 이 리포트는 런타임에서 주기 생성되고 ops heartbeat가 freshness를 감시해야 한다. 파일 timestamp가 오래됐으면 그 파일만 보고 후보 상태를 판단하지 말고 API/`check_runtime_stack.sh` 또는 갱신된 runtime report를 다시 본다.
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
일반 상태 확인은 통합 점검 스크립트를 우선 사용한다. `~/Library/Application Support/trading` durable 런타임이 있으면 이 스크립트가 durable Python/소스를 자동으로 사용한다.

```bash
cd /Users/yumin/Documents/trading
./scripts/check_runtime_stack.sh
```

기존 단일 API LaunchAgent는 `com.yumin.trading.api`다. 워크스페이스 파일 읽기가 느려졌거나 API/워커 전체를 함께 복구해야 하면 `com.yumin.trading.runtime-stack` LaunchAgent가 `~/Library/Application Support/trading` durable 런타임 watchdog 역할을 한다.

```bash
launchctl print gui/$(id -u)/com.yumin.trading.api | sed -n '1,80p'
launchctl print gui/$(id -u)/com.yumin.trading.runtime-stack | sed -n '1,80p'
```

```bash
curl -s "http://127.0.0.1:8000/health/live" | jq
curl -s "http://127.0.0.1:8000/health/ready" | jq
```

수동 복구:

```bash
./scripts/bootstrap_durable_runtime.sh
./scripts/restart_runtime_stack_tmp.sh
TRADING_RUNTIME_WATCHDOG_ONCE=1 ./scripts/watch_runtime_stack_tmp.sh
```

`restart_runtime_stack_tmp.sh`는 재시작 전에 `trading_api.log`, `trading_worker_loop.log`, `trading_worker_ws.log`가 `TRADING_LOG_ROTATE_MAX_BYTES`를 넘으면 회전한다. 기본값은 `104857600` bytes이고, `TRADING_LOG_ROTATE_KEEP` 기본값은 `5`다.

`restart_runtime_stack_tmp.sh`는 같은 런타임에 대해 단일 실행 lock을 잡고 시작한다. 기본 lock은 `~/Library/Application Support/trading/locks/restart_runtime_stack_tmp.lock`이고, 다른 재시작이 이미 진행 중이면 최대 `TRADING_RUNTIME_RESTART_LOCK_WAIT_SECONDS` 기본 `300`초까지 기다린다. 이 lock은 watchdog 재시작과 수동 재시작이 겹쳐 API/worker kill, source refresh, post-restart report refresh가 서로 섞이는 상황을 막기 위한 hardening이다.

`restart_runtime_stack_tmp.sh`는 `/health/ready`가 뜬 직후 current-runtime 운영 리포트도 자동으로 다시 만든다. 대상은 `runtime_guard`, `no_order_watchdog`, `live_candidate_promotion_readiness`, `live_replay_parity`, `session_impulse_retest_runtime_audit`, `entry_surface`, `boot_check`, `ops_heartbeat`다. 따라서 재시작 직후 오래된 latest 파일 때문에 `report_before_current_runtime_start`가 남아 있으면 안 된다. post-restart `no_order_watchdog`는 lock을 오래 잡지 않도록 기본 `TRADING_POST_RESTART_NO_ORDER_DAYS=1`, `TRADING_POST_RESTART_NO_ORDER_LIMIT=80`의 짧은 current-runtime refresh로 돌고, 깊은 7일 lookback은 scheduled no-order job이 맡는다. 복구 속도를 최우선으로 두고 리포트 refresh를 건너뛰려면 `TRADING_POST_RESTART_REFRESH_REPORTS=0 ./scripts/restart_runtime_stack_tmp.sh`를 쓴다.

runtime-stack watchdog는 재시작 직후 `loop` worker의 첫 `sync_universe`가 길어질 수 있음을 감안해 `heartbeat_starting`을 바로 hard failure로 보지 않는다. `TRADING_RUNTIME_WATCHDOG_STARTING_GRACE_SECONDS` 기본값은 `900`초이며, 이 grace 안에서는 `starting_grace`로 보고 재시작하지 않는다. loop worker가 실제 universe 동기화에 들어가면 heartbeat phase는 `syncing_universe`로 갱신되어 `/health/ready`에서 죽은 starting 상태와 구분된다. 이 warming phase 안에서 `/health/ready`의 유일한 약점이 market-data freshness면 watchdog는 `market_data_warmup_grace`로 보고 실패 카운트를 초기화한다. `restart_runtime_stack_tmp.sh`의 ready 대기는 `TRADING_RUNTIME_READY_WAIT_SECONDS`로 조정하며 기본값은 `600`초다.

`/health/ready`의 market-data freshness는 단일 BTC probe가 아니라 live symbol quorum으로 본다. MICRO_LIVE symbols를 우선 보고, 1m/5m 각 timeframe에서 최대 12개 probe 중 최소 `min(3, probe_count)`개가 freshness threshold 안에 있으면 health는 통과한다. 개별 심볼 stale은 detail의 `stale=...`에 남으며, 해당 심볼의 전략 생성은 자체 candle 상태로 계속 제한된다.

`restart_runtime_stack_tmp.sh`는 workspace의 `reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_*.json`도 runtime reports로 동기화한다. MICRO_LIVE contract guard, replay parity, dashboard baseline, replay validation bridge, safety drag audit, compare-only research searches는 복사 시각이나 단순 최신 파일명이 아니라 현재 MICRO_LIVE 심볼 계약과 정확히 맞는 최신 regular backtest를 사용해야 한다. `unseen`/`top*` variant report와 broader universe experiment report는 live contract baseline이 아니다. 연구 스크립트에서 의도적으로 다른 universe를 보고 싶으면 `--backtest-path` 또는 `--baseline-backtest-path`를 명시한다.

코드 반영 목적의 재시작은 `launchctl kickstart gui/$(id -u)/com.yumin.trading.runtime-stack`만으로 끝내지 않는다. `runtime-stack` LaunchAgent는 watchdog wrapper이고, `/health/ready`가 이미 `ready`면 내부 `uvicorn`/worker 프로세스를 그대로 둘 수 있다. 실제 API/worker 코드 교체가 필요하면 `~/Library/Application Support/trading/runtime_src/scripts/restart_runtime_stack_tmp.sh` 또는 workspace의 `./scripts/restart_runtime_stack_tmp.sh`를 실행한 뒤 `./scripts/check_runtime_stack.sh`로 새 PID와 `/health/ready`를 확인한다. 구형 `./scripts/restart_runtime_stack.sh`는 독자 재시작 경로가 아니라 동일한 durable runtime restart로 위임되는 compatibility wrapper다. 재시작 스크립트의 post-restart refresh 로그는 `~/Library/Application Support/trading/logs/post_restart_report_refresh.log`에 남는다.

LaunchAgent 재설치:

```bash
./scripts/install_runtime_stack_launchd.sh
```

이 설치 스크립트는 `com.yumin.trading.runtime-stack`을 설치하고, `com.yumin.trading.api`, `com.yumin.trading.stage-monitor`, `com.yumin.trading.paper-lineage-watch`의 사용자 LaunchAgent plist를 `~/Library/LaunchAgents.disabled/...`로 옮긴다.

Live 후보 승격 상태 확인:

```bash
./scripts/run_live_candidate_promotion_readiness.py --compact --no-write-report
./scripts/run_live_candidate_promotion_readiness.py --symbol ADAUSDC --compact --no-write-report
```

해석 계약은 [LIVE_CANDIDATE_READINESS_CONTRACT.md](/Users/yumin/Documents/trading/docs/LIVE_CANDIDATE_READINESS_CONTRACT.md)를 따른다.

이 리포트는 기존 런타임 audit과 order intent blocker만 읽어 `GATE_BLOCKED`, `SHADOW_SIGNAL_ONLY`, `SUBMIT_READY_GAP`, `NO_FRESH_LIVE_CANDIDATE` 같은 compare-only 상태로 압축한다. latest JSON은 top-level `status/overall_status/state/reason/status_detail`도 같이 쓴다. `WAIT/no_promotable_live_candidate`는 정상 대기라 `PASS`, `BLOCKED`/`WATCH` headline은 운영 관찰이라 `WATCH`, `SUBMIT_READY_GAP` 같은 `FAIL` headline은 hard failure로 읽는다. 기본 headline은 현재 WS worker `started_at` 이후를 active runtime scope로 보며, 재시작 전 24시간 blocker는 `lookback_context`로만 표시한다. 과거 전체 window를 의도적으로 headline에 반영하려면 `--lookback-only`를 붙인다. `--symbol`을 주면 해당 심볼의 승격 상태만 분리해서 보고, 후보별 `latest_evidence_at`, `age_seconds`, `fresh`/`recent`/`stale`/`old` 라벨로 차단 근거의 최신성을 확인한다. 전역 `latest_evidence_at`과 headline을 만든 후보만의 `headline_evidence_at`은 분리해서 읽는다. blocker는 `headline_top_blockers`/`top_live_blockers`를 현재 live 해석 기준으로 먼저 보고, `top_all_blockers`와 `top_auxiliary_blockers`는 보조/비-live 심볼 context로만 본다. `promotion_decision`, `attention_flags`, `operator_review_items`는 먼저 볼 blocker와 심볼을 지정하는 운영 힌트일 뿐이고, live allowlist, sizing, approval, 주문 제출 권한은 바꾸지 않는다.

`/execution/operator-ui`는 이 live 후보 섹션을 dashboard `fast=true` 경로에서 먼저 렌더한다. validation/checklist/scanner 같은 무거운 보조 surface가 느리면 해당 섹션만 `source_unavailable` fallback으로 표시하고, live candidate readiness 전체 화면을 loading 상태로 묶지 않는다.

심볼을 선택한 화면에서는 선택 심볼 readiness와 전역 `live_candidate_promotion_readiness_global`을 같이 읽는다. 예를 들어 `BTCUSDC`가 `WAIT`여도 전역 headline이 `BLOCKED / validation_do_not_deploy`이면 승격 판단은 전역 차단을 우선한다.

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
위 수동 명령은 workspace 개발 검증용이다. 실제 로그인 세션에서 반복 실행되는 operator brief launchd는 durable runtime 배포본을 authority로 삼아 `/Users/yumin/Library/Application Support/trading/runtime_venv/bin/python`과 `/Users/yumin/Library/Application Support/trading/runtime_src/scripts/notify_operator_session_brief.py --quiet`를 실행한다. 운영 중에는 아래 health check로 두 agent exit code와 runtime latest artifact freshness를 같이 본다. workspace report가 최신이어도 runtime report가 오래됐으면 운영 truth는 오래된 것이다.

```bash
'/Users/yumin/Library/Application Support/trading/runtime_venv/bin/python' \
  '/Users/yumin/Library/Application Support/trading/runtime_src/scripts/check_operator_session_brief_automation.py' \
  --strict
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
- validation이 `GO`, checklist가 `manual review first`, `act=proceed_with_configured_rollout`, `blocking_failures=0`, `manual_actions=0`인 조합은 advisory-only manual review다. 이때 operator brief는 `ALIGNED_MONITOR`로 읽고, `DEPLOYMENT_REVIEW_REQUIRED`처럼 hard divergence로 읽지 않는다.
- 5-second kernel이 `manual_review`와 `candidate_surface=context_only`를 말하는 것은 "지금 live order candidate가 없다"는 운영 관찰이다. validation/checklist hard blocker와 다르다.
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
- drill payload의 `family_cluster_guard_summary`는 same-window family cluster와 recent family loss cooldown을 같이 보여준다.
- `active_families`가 비어 있지 않으면, 그 family는 지금 PAPER 표본도 추가하지 않는다. 이 상태에서 억지로 sample을 더 쌓으면 signoff truth를 악화시킬 가능성이 높다.
- 기본 guard는 `60분 same-family open >= 1` 또는 `최근 90분 같은 family 손실 >= 2`일 때 동작한다.
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

자동 반복 감시가 필요하면:
- `/Users/yumin/Documents/trading/scripts/paper_lineage_watch_tick.py`
- `/Users/yumin/Documents/trading/docs/PAPER_LINEAGE_WATCH_AUTOMATION.md`

이 tick은 `NO_ELIGIBLE_CANDIDATE`를 정상 idle 상태로 처리하고, launchd에서 15분 간격으로 universe-wide `sweep_reversal` lineage 표본 축적만 담당한다.

### 5.5. MICRO_LIVE runtime readiness helpers
`MICRO_LIVE` 직전에는 dashboard/checklist만 보지 말고, 설정 drift와 live order lifecycle도 별도로 확인한다.

현재 live route/pacing의 짧은 기준 문서는 [MICRO_LIVE Current State](/Users/yumin/Documents/trading/docs/MICRO_LIVE_CURRENT_STATE.md)다. 이 문서를 먼저 보고, 세부 운영 절차가 필요할 때 아래 helper들을 따른다.

완성도 하드닝 기준은 [MICRO_LIVE Near-100 Hardening Plan](/Users/yumin/Documents/trading/docs/MICRO_LIVE_NEAR_100_HARDENING_PLAN.md)을 따른다. 여기서 `100%에 가까움`은 무손실이 아니라 fail-closed, auditability, stable latest report, alert delivery confirmation, replay/live 증거 분리를 뜻한다.

```bash
./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDC --days 7
./.venv/bin/python scripts/run_micro_live_runtime_guard.py --days 30
./.venv/bin/python scripts/run_micro_live_synthetic_canary.py --no-network
./.venv/bin/python scripts/run_live_order_lifecycle_report.py --days 30
./.venv/bin/python scripts/run_micro_live_no_order_watchdog.py --days 3 --no-fail-exit
./.venv/bin/python scripts/run_live_reconciliation_watchdog.py --days 3 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_boot_check.py --days 3 --limit 200 --no-fail-exit
./.venv/bin/python scripts/run_live_replay_parity_audit.py --all-live-symbols --days 3 --no-fail-exit
./.venv/bin/python scripts/run_replay_validation_bridge.py --all-live-symbols --no-fail-exit
./.venv/bin/python scripts/run_micro_live_safety_drag_audit.py --backtest-report reports/validation/micro_main_usdt_proxy_backtests/micro_main_usdt_proxy_backtest_20260515T175711Z.json --include-samples
./.venv/bin/python scripts/run_session_impulse_retest_runtime_audit_report.py --hours 3 --no-fail-exit
./.venv/bin/python scripts/run_micro_live_ops_heartbeat.py --no-fail-exit
./.venv/bin/python scripts/run_micro_live_failure_drill.py --no-fail-exit
```

용도:
- `run_micro_live_preflight.py`: API surface, validation, checklist, scanner, alert 상태를 한 번에 읽는다. Validation이 `GO`이고 checklist의 `blocking_failures=0`, `manual_actions=0`이면, checklist가 advisory warning 때문에 `approve=manual review first`를 표시하더라도 preflight는 이를 hard `NOT_READY`로 보지 않는다. 이 경우는 “자동 주문 경로 차단”이 아니라 운영 관찰 경고다. Validation 자체가 manual review/no-go이거나 checklist에 blocking/manual item이 있으면 계속 `NOT_READY`다.
- `run_micro_live_runtime_guard.py`: `.env` allowlist, worker universe, SIR live rollout window, macro blackout horizon, fail-closed liquidity gate, recent live intent funnel을 빠르게 확인한다. `micro_live_backtest_contract_alignment`는 현재 MICRO_LIVE 심볼/패밀리/entry model/session/direction 계약이 `session_impulse_retest` 11심볼 백테스트 계약과 같은지 직접 비교한다. 이 항목이 `FAIL`이면 일반 allowlist 정합성이 맞아 보여도 백테스트와 다른 live route이므로 먼저 계약을 복구한다. `session_impulse_retest_live_rollout_window`는 raw `rollout_priority`가 아니라 core 심볼끼리의 순위로 `SESSION_IMPULSE_RETEST_CORE_LIVE_SLOTS`를 해석한다. blocking check 실패는 `FAIL`, warning check 실패는 `WATCH`로 top-level에 드러나야 하며, 내부 check의 `FAIL`이 top-level `PASS` 밑에 숨으면 안 된다.
- `run_micro_live_synthetic_canary.py`: 실제 주문 없이 stop-distance sizing과 liquidity gate submit 경로를 dry-run한다.
- `run_live_order_lifecycle_report.py`: intent, submission, fill, Binance ledger를 연결해 `no signal / approval blocked / submit skipped / submitted without fill / rejected-error / open / closed`를 분리한다.
- `run_micro_live_no_order_watchdog.py`: live intent가 쌓였는데 live submission이 없는 구간을 감지한다. WS worker가 재시작된 뒤에는 active alert 판단을 `runtime_started_at` 이후로 제한해 예전 차단 이력을 새 runtime 장애처럼 띄우지 않는다. 대신 `lookback_lifecycle_summary`에 전체 `--days` 구간 intent/submission/context를 같이 담아 “현재 런타임은 깨끗함”과 “최근 3일에는 어떤 intent가 있었는가”를 분리해서 본다. live intent가 0이면 `candidate_generation_context`에 `session_impulse_retest` runtime audit 요약을 붙여, 후보 자체가 없었는지(`no_live_route_candidate_plan`), WS 중복 route 억제인지(`ws_stream_active_route_suppressed`), 실제 order-blocking audit가 있는지를 같은 리포트에서 확인한다. 또한 `session_impulse_retest_opportunity_context`에 현재 SIR 백테스트 조건 재생 요약을 붙인다. `summary.expected_order_count`는 runtime 재시작 이후 기대 주문이고, `lookback_summary.expected_order_count`는 전체 `--days` 구간 기대 주문이다. runtime 이후 기대 주문이 있는데 live intent가 0이면 `sir_backtest_opportunity_without_live_intent` WARN으로 올려, “백테스트 조건이면 주문이어야 하는데 live plan/intent가 누락된 상태”를 별도 모순으로 잡는다. 반대로 기대 주문이 모두 재시작 전 차단 이력이면 `sir_pre_restart_expected_orders_advisory`를 `OK/INFO`와 `historical_advisory=true`로 표시해 현재 submit 장애와 구분하고 반복 알림은 보내지 않는다. 알림은 `micro_live_no_order_watchdog` 타입으로 `intent/제출/후보/백테스트조건/원인/상세/다음`만 짧게 보내며, `WATCH` 상태는 `[모니터링] MICRO_LIVE 주문 흐름 관찰` 제목으로 보낸다. 알림을 보낼 때만 `--notify`를 붙인다. timestamp 리포트와 함께 `latest.md/latest.json`을 쓰고, 알림 cooldown state는 실제 전송 성공 후에만 기록한다.
- `run_micro_live_ops_heartbeat.py`: scheduled guard들의 fresh/content 상태를 묶는다. `FAIL/WATCH`만 운영 알림 대상이며, `historical_advisory=true`나 `lookback_advisory=true`는 `advisory_count`와 `참고` 라인에 남기되 top-level `PASS`를 깨지 않는다. 즉 “현재 조치할 장애”와 “과거/룩백에서 관찰된 흐름 차이”를 분리한다.
- validation payload cache는 운영 preflight의 read-only approval surface에 쓰인다. 기본 TTL은 6시간이다. 이 값은 주문 승인 logic을 완화하기 위한 것이 아니라, 무거운 `validation/report` 재계산이 매 15분마다 비어 preflight를 `validation unavailable`로 흔드는 것을 막기 위한 운영 캐시다.
- `run_live_reconciliation_watchdog.py`: stale open submission, ledger terminal mismatch, user-stream stale, fresh critical reconciliation event를 감지한다. 알림은 `live_reconciliation_watchdog` 타입을 사용하고, 알림을 보낼 때만 `--notify`를 붙인다.
- `process_alert_retry_queue.py`: Discord/API 장애로 발송 실패한 알림을 재처리한다. trading alert는 시간 민감하므로 queued 상태가 `alert_retry_queue_max_age_seconds` 기본값 `86400`초를 넘으면 재발송하지 않고 `expired/stale_retry_task_expired`로 닫는다. 이렇게 해야 며칠 전 `validation_warn`나 miss 알림이 나중에 살아나 현재 주문 상태처럼 보이는 일을 막는다.
- `run_micro_live_boot_check.py`: worker 시작 전 runtime guard, reconciliation watchdog, synthetic canary, failure-contract drill을 한 번에 묶어 확인한다. 실제 주문은 보내지 않는다.
- `run_live_replay_parity_audit.py --all-live-symbols`: 11개 live symbol 전체의 replay 기대 빈도 대비 live intent 빈도를 한 번에 보고, 심볼별 `flow_diagnosis.stage`로 signal/plan 생성 공백, approval 차단, intent->submission 공백, exchange reject/error를 분리한다. WS worker `started_at`이 있으면 active headline은 `runtime_since_ws_start`이고, 재시작 전 `--days` 전체 결과는 `lookback_evaluation_summary`로만 남긴다. 과거 window를 headline으로 보고 싶으면 `--lookback-only`를 쓴다. 런타임 이후 기대 후보가 2건 미만이고 live intent/submission이 없으면 flow shortfall 경고가 아니라 fresh 후보 대기로 본다. 이때 lookback이 `WATCH/ALERT`여도 현재 runtime이 판단 evidence floor 미만이면 headline은 `PASS`로 유지하고 `lookback_advisory=true`로만 남긴다. 후보 빈도는 충분하지만 모든 intent가 승인 차단이면 `PASS`가 아니라 `WATCH`로 본다. `blocked=0`이어도 `by_decision=SKIP_SHADOW_ONLY`이고 `top_block_reasons`가 있으면 주문 flow는 제출 불가였던 것으로 보고 `WATCH`로 본다. 짧은 non-runtime 심볼별 창에서 replay 기대 후보가 2건 미만이면 flow shortfall은 `ALERT`가 아니라 `WATCH`로 두고, aggregate flow와 반복 여부를 함께 본다. 포트폴리오 `WATCH` reason은 thin live flow(`portfolio_symbol_live_flow_watch_thin_window`), order gate 대기(`portfolio_symbol_order_flow_blocked_or_waiting`), 혼합(`portfolio_symbol_live_flow_and_order_gate_watch`)으로 나눠 읽는다. timestamp 리포트와 함께 `latest.md/latest.json`도 쓴다.
- `run_replay_validation_bridge.py --all-live-symbols`: replay cache가 보수적 bridge 기준을 넘는지 audit-only로 확인한다. 평균 EV뿐 아니라 `ev_r_lower_95`가 음수가 아닌지 보고, `direction/strategy_family/entry_model`별 material slice가 약하면 `ELIGIBLE_FOR_MANUAL_BRIDGE_REVIEW_WITH_SLICE_WARNINGS`로 낮춘다. timestamp 리포트와 함께 `latest.md/latest.json`도 쓴다. 이 스크립트는 live approval을 변경하지 않는다.
- `run_micro_live_safety_drag_audit.py`: 현재 `.env` MICRO_LIVE 계약과 재현 가능한 safety gate를 `session_impulse_retest` 백테스트 trade list에 적용해 진입 수/총 R/EV drag를 계산한다. 계약 필터, position cap, family cluster window, same-direction exposure, loss cooldown, Saturday risk multiplier를 분리해 본다. liquidity depth/spread/slippage는 historical orderbook snapshot이 백테스트 artifact에 없으면 이 리포트에서 정확히 계산하지 않고, synthetic canary와 live submission snapshot으로 별도 추적한다.
- `run_micro_live_safety_grid_search.py`: live-canary deployable 범위의 pacing 조합을 같은 백테스트 trade list에 전수 적용해 `recommended`, `recommended_cap2`, `raw_top_20`을 분리한다. raw top은 safety off/unlimited exposure가 섞일 수 있으므로 진단용이고, 실제 적용 후보는 `deployable_filter`를 통과한 `recommended`만 본다. 같은 timestamp 후보 순서는 `run_micro_live_safety_drag_audit.py`와 동일하게 보존해야 하므로 별도 재정렬을 넣지 않는다.
- `run_session_impulse_retest_runtime_audit_report.py`: DB에 남은 `session_impulse_retest` refresh/auto_route audit row를 요약한다. 기본 headline은 WS worker `started_at` 이후 `runtime_since_ws_start` scope이고, 전체 `--hours` 결과는 `lookback_summary`로만 남긴다. 과거 window를 headline으로 보고 싶으면 `--lookback-only`를 쓴다. `signal_generated`, `no_fresh_candidates`, `intent_blocked`, `submitted`, `ws_stream_active_route_suppressed`, `intent_creation_failed`, `submit_error`를 한 리포트에서 본다. 상단의 `order_blocking_status_counts`는 실제 주문 차단/제출 실패 쪽이고, `non_blocking_status_counts`는 WS duplicate-route suppression 같은 비차단 context이며, `no_candidate_status_counts`는 fresh 후보 없음이다. timestamp 리포트와 함께 `latest.md/latest.json`도 쓴다.
- `run_micro_live_ops_heartbeat.py`: launchd/수동 스케줄이 실제로 최신 리포트를 계속 만들고 있는지 확인한다. 가능한 리포트는 내부 `overall_status/status/evaluation.status`까지 읽어서, 최신 파일이어도 `ALERT/WATCH/DRIFT/FAIL`이면 heartbeat에 노출한다. live/replay parity도 감시 대상이므로 replay 대비 live flow 괴리가 `WATCH/ALERT`로 남으면 운영 heartbeat에 같이 드러난다. runtime-scoped 리포트(`runtime_guard`, `no_order_watchdog`, `boot_check`, `live_candidate_promotion_readiness`, `live_replay_parity`, `session_impulse_retest_runtime_audit`, `entry_surface`)는 파일 age만 보지 않고 현재 WS worker `started_at` 이후 생성됐는지도 확인한다. 리포트가 방금 만든 것처럼 보여도 current runtime 시작 전이면 `WATCH/report_before_current_runtime_start`로 올려, 재시작 전 truth를 현재 상태로 읽지 않게 한다. entry surface의 `latest_entry_alert_run.json`도 감시 대상이므로 stale file, snapshot missing, `/portfolio/budget` timeout 같은 `source_request_failed`가 최신 상태로 남으면 heartbeat가 FAIL로 드러낸다. 이전 tick이 아직 실행 중인 `entry_surface_tick_already_running`은 WATCH로 남긴다. 정상적인 `no_alertable_rows`도 heartbeat `status_detail`에 `operator_action_summary.state`, `next_action`, top route mismatch reason을 붙여 `context_only_outside_live_route` 같은 정상 대기 상태를 바로 읽을 수 있게 한다. 이때 하위 리포트의 `evaluation.reason/status_detail/message`를 heartbeat의 `report_reason/status_detail`로 승격하므로, `live_replay_parity=WATCH`는 `portfolio_symbol_live_flow_and_order_gate_watch`처럼 실제 확인 이유를 같이 보여야 한다. Discord 운영 알림은 `micro_live_ops_heartbeat` 타입으로 보내며 `상태`, `긴급`, `주의` 라인을 우선 노출하므로 generic `확인 필요`만 보이고 원인을 못 보는 상태가 되면 안 된다. `fail=0`인 WATCH-only heartbeat는 `[모니터링] ... 운영 관찰`로 표시하고 `WATCH는 자동 관찰; 반복/악화 시 해당 리포트 확인`으로 안내한다. failure-contract drill 최신성도 같이 감시해 드릴이 stale 되면 운영 heartbeat에서 바로 보이게 한다. 리포트 job은 `state.json` 같은 상태 파일이 아니라 실제 report 파일을 보고, 읽어야 하는 status가 없으면 failure로 처리한다. macro blackout 계약은 파일 존재만 보지 않고 `windows`의 future horizon도 직접 검증한다. 이때 glob 최신 파일보다 `.env`의 `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`를 우선해 live approval이 실제로 쓰는 계약을 감사한다. blackout 파일 mtime이 오래됐지만 horizon이 충분하면 `WATCH`, horizon 부족/만료는 hard failure로 본다. 알림 메시지는 `긴급(FAIL)`과 `주의(WATCH)`를 분리해 보여주고, 같은 issue 조합은 cooldown으로 반복 발송을 억제한다. 단, cooldown state는 실제 전송 성공이 확인된 뒤에만 기록한다. timestamp 리포트와 함께 `latest.md/latest.json`도 써서 운영 화면이나 수동 확인은 고정 경로를 볼 수 있고, timestamp/latest/state 쓰기는 atomic replace로 처리한다.
- `run_micro_live_failure_drill.py`: 실제 주문/실 DB/control switch를 건드리지 않는 failure-contract drill이다. missing/stale/malformed report, 짧은 macro horizon, 알림 전송 실패, stale submission, submit-ready gap, runtime audit hard failure가 `PASS`로 숨지 않는지 한 번에 확인하고 timestamp/latest 리포트를 atomic replace로 남긴다.

운영 launchd는 runtime 배포본 기준으로 설치되어 있다. 따라서 자동 스케줄이 생성하는 MICRO_LIVE 운영 truth는 보통 `~/Library/Application Support/trading/runtime_src/reports/operations/...` 아래의 `latest.md/latest.json`과 `launchd/logs/*.log`다. workspace의 `reports/operations/...`는 수동 실행이나 개발 검증 결과일 수 있으므로, live 운영 상태를 판단할 때는 runtime_src 리포트를 우선 본다. entry surface launchd도 runtime_src의 `scripts/notify_entry_surface.py`를 직접 실행하고 `runtime_src/reports/operations/entry_surface/latest_entry_alert_run.json`을 쓴다. macOS launchd가 Documents 아래 bash wrapper를 실행할 때 권한 이슈가 날 수 있어서, entry surface launchd는 runtime_src Python 직접 호출에 `--quiet`, `--lock-file`, `--output-file`을 명시한다. 주기 실행 guard와 entry surface launchd는 quiet 모드로 설치해 stdout 로그 폭증을 막고, 운영 truth는 stdout이 아니라 `latest.md/latest.json` 또는 `latest_entry_alert_run.json`에 남긴다.

entry surface의 `BLOCKED_SETUP`은 전체 portfolio blocked context이고, 실제 주문 후보 차단은 `blocked_live_order_candidates` 또는 `blocked_setup_breakdown.live_routable`로 판단한다. `blocked_context_only_setups`는 current live route 밖의 blocked context라서 주문 submit 실패로 읽지 않는다.
`route_mismatch_summary`는 context-only row가 live route 밖으로 빠진 이유를 reason/family/entry model/symbol별로 집계한다. 현재 runtime 계약은 `session_impulse_retest + CONFIRM + 11개 MICRO_LIVE 심볼 + dead_session/london/new_york`이고, `.env.example`도 이 계약과 맞춰 둔다.
entry surface의 `counts/source_counts`는 전체 source row 수이고, `display_counts`는 `--max-per-status`로 잘려 실제 message에 표시된 row 수다. `truncated_entry_counts`가 0보다 크면 compact display에 일부 row가 생략된 것이므로, 주문 후보 유무는 `live_order_candidates/blocked_live_order_candidates` 같은 source count를 기준으로 판단한다.
entry surface의 `operator_action_summary`는 operator가 먼저 읽어야 하는 상태다. `live_order_candidate_present`면 intent/submission/fill을 확인하고, `live_order_candidate_blocked`면 validation/portfolio/risk blocker를 확인한다. `context_only_outside_live_route`면 후보처럼 보이는 surface 활동이 현재 live route 밖이라는 뜻이므로 주문 미발생을 정상으로 읽고, live route를 바꾸려면 의도적으로 계약을 변경해야 한다. `no_surface_candidates`는 fresh 후보 대기 상태다.
entry surface의 saved result는 Discord가 나가지 않는 `no_alertable_rows`에서도 top-level `generated_at/status/overall_status/status_detail`와 rendered `message`를 보존한다. `live_order_candidates=0`이고 `operator_action_summary.state=context_only_outside_live_route`이면 `status=PASS`로 읽는다. `live_order_candidate_present` 또는 `live_order_candidate_blocked`이면 `status=WATCH`로 남겨 intent/submission/fill 또는 blocker 확인 대상으로 둔다. 따라서 최신 artifact 하나만 열어도 headline, route mismatch, operator action, counts/display/truncated context를 같은 형식으로 확인할 수 있다.

Signal subscription 알림의 `near/touch/confirm`은 pre-entry 관측 알림이다. payload에 `order_submission_expected=false`, `order_truth=pre_entry_signal_only`가 들어가며, Discord confirm 제목은 `[모니터링] ... 주문 전 관찰 알림(주문 아님)`으로 표시된다. 원본 payload message도 `signal-only no-order ...`로 시작해야 한다. 실제 주문 truth는 `LIVE_ORDER_CANDIDATE`, order intent, submission, fill이다. 반대로 `entry/partial_exit/tp/sl/closed`는 execution fill truth이며 Discord 중요 알림으로 보낸다. execution fill truth 알림의 가격 표시는 실제 체결가인 `fill_price`를 포함해야 하며, fallback 순서는 `event_price/price/fill_price/entry_price`다.

`AUTO_TRADING_EXECUTION_MODE`가 `MICRO_LIVE` 또는 `LIVE`이면 `run_worker.py`는 시작 전에 boot check를 먼저 실행한다. 실패하면 worker는 live routing을 시작하지 않는다. `--skip-boot-check`는 운영자가 의도적으로 우회할 때만 사용한다.

`validation_do_not_deploy`가 주문을 막으면 `validation_block_detail.primary_cause/root_causes`를 먼저 본다. 대표 원인은 `validation_sample_missing`, `validation_expectancy_non_positive`, `validation_win_rate_missing_or_zero`, `validation_score_below_deploy_floor`, `risk_gate_not_open`, `runtime_candidate_blocked`다.

blackout horizon이 runtime guard에서 막히면 먼저 계약 파일을 갱신한다.

```bash
./.venv/bin/python scripts/build_micro_live_event_blackouts.py \
  --years 2026,2027 \
  --symbols BTCUSDC \
  --families sweep_reversal \
  --entry-models LIMIT \
  --output reports/validation/contracts/micro_live_event_blackouts_major_us_macro_auto.json
```

새 파일을 만들었으면 `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`를 해당 출력 경로로 맞춘 뒤 다시 guard를 돌린다.

이 스크립트들은 live authority가 아니다. 실패하면 제출을 멈추고 설정/계약/게이트를 맞춘 뒤 다시 `preflight -> runtime guard -> synthetic canary` 순서로 확인한다.

macOS에서 반복 점검을 자동화하려면 먼저 plist만 생성한다.

```bash
./.venv/bin/python scripts/install_micro_live_ops_launchd.py
```

실제 등록은 운영자가 확인한 뒤 `--install --load`를 붙인다. 이 스케줄은 runtime guard, no-order watchdog, reconciliation watchdog, synthetic canary, boot check, live candidate promotion readiness, ops heartbeat, replay validation bridge, live replay parity, session impulse retest runtime audit, failure-contract drill, Binance rule drift, macro calendar refresh를 분리 실행한다. 자주 도는 runtime-scoped guard와 live replay parity는 quiet mode로 설치해 stdout 로그가 JSON 본문으로 커지지 않게 한다. macro calendar refresh는 `.env` 또는 `--env-file`의 `AUTO_TRADING_MICRO_LIVE_EVENT_BLACKOUT_PATH`가 있으면 그 live 계약 파일을 직접 갱신하고, 값이 없을 때만 기본 auto output을 쓴다.

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
- `MICRO_LIVE` 진입 전 확인 기준은 `runtime_decision_band == AMBER_CONDITIONAL`, `runtime_effective_action == conditional_micro_live_signoff`, `runtime_allowed_reopen_scope == MICRO_LIVE_ONLY`다.
- `MICRO_LIVE` 직전 surface는 `runtime_preflight_summary.status == READY_FOR_MICRO_LIVE`와 `runtime_operator_signoff_summary.status == ready_for_manual_micro_live_signoff`를 같이 보여줘야 한다. 이 단계 의미는 “기술 gate는 통과했고, 운영자가 MICRO_LIVE만 수동 서명할 수 있다”이다.
- 현재 기본 `MICRO_LIVE` 계약은 `session_impulse_retest + CONFIRM + 11개 core USDC 심볼(BTC/ETH/SOL/LINK/BNB/XRP/ADA/AVAX/BCH/LTC/NEAR) + dead_session/london/new_york`이다. legacy `sweep_reversal`, `SWEEP_CONFIRM`, live 심볼 밖 row는 context-only로 읽는다.
- `trend_continuation + LIMIT`는 별도 `trend proof lane`으로만 추적한다. 이 lane은 상승장/추세장 proof를 따로 쌓는 용도고, proof가 쌓이기 전까지는 live submit 계약에 포함하지 않는다.
- `historical execution contract proof`는 현재 `BTCUSDC + sweep_reversal + LIMIT` 계약의 장기 closed-plan context를 advisory-only로 보여준다. 빠르게 참고할 수 있지만 live gate source로 직접 쓰지 않는다.
- `historical walk-forward execution proof`는 같은 계약을 과거 5m/15m 캔들에 대해 candle-by-candle로 순차 재생한 advisory lane이다. `simulation_start_ts`, `simulation_end_ts`, `latest_source_ts`를 같이 보고 시뮬레이션 구간이 실제로 어디까지 반영됐는지 확인한다.
- `historical walk-forward strategy proof`는 현재 `BTCUSDC` 중심 raw candle strategy-level replay lane이다. 이 lane은 과거에 저장된 plan row가 아니라 과거 캔들에서 신호를 직접 재생성해서 large-sample 전략 적합성을 보는 용도다. live execution gate와는 별도 advisory evidence로만 해석한다.
- `MICRO_LIVE`는 `live_eligible_post_patch_closed_trade_count >= 15`, `live_eligible_post_patch_sample_summary.replay_max_drawdown_r < 4.5`, `live_eligible_post_patch_sample_summary.replay_p5_r >= -1.05`, `live_eligible_post_patch_sample_summary.stop_loss_share < 0.45`, `live_eligible_post_patch_sample_summary.worst_loss_streak < 5`를 동시에 만족할 때만 검토한다.
- `actual execution subset`이 `5 distinct plans`를 넘기기 전까지는 gate proof가 bootstrap 단계다. 이 구간에선 `runtime_live_contract_scope.proof_source`가 가리키는 `live_eligible_post_patch_sample_summary`를 gate truth로 쓴다.
- live submit approval은 최근 알트 reversal cluster를 같이 본다. `live_family_cluster_window_cap_reached`가 뜨면 같은 family 신규 진입을 동시 다발로 받지 말고, `live_family_loss_cooldown_active`가 뜨면 최근 family 손실 파동이 가라앉을 때까지 신규 live entry를 멈춘다.
- 현재 tuned pacing은 `family_cluster_window=30m`, `max_same_family_entries_per_window=3`, `max_same_family_direction_exposures=3`, `recent_loss_cooldown=60m`, `recent_loss_trigger_count=4`, `max_concurrent_positions=3`, `saturday_risk_multiplier=1.0`이다. 이 값은 live-canary deployable 범위의 7,683개 조합 백테스트에서 고른 최고 조합이며, replayable safety gate 적용 후 baseline 대비 total-R drag는 약 2.53%다. safety를 끈 raw 최고 조합은 진단용으로만 보고 live 설정으로 쓰지 않는다.
- 현재 canary pacing rule은 `1 daily new entry`가 아니라 `max 3 concurrent positions`다. 새 신호는 매번 approval / safety / reconciliation 기준으로 다시 평가한다.
- `AUTO_TRADING_MICRO_LIVE_MAX_DAILY_NEW_ENTRIES=0`은 일일 신규 진입 상한을 끈 상태를 의미한다. 이때도 무제한 추격 진입이 아니라 `current_exposure_count`, safety locks, reconciliation, family cluster guard, event blackout, symbol priority guard가 다음 진입을 다시 심사한다.
- 현재 canary는 major U.S. macro blackout (`FOMC`, `CPI`, `NFP`) 동안 신규 `MICRO_LIVE` 진입을 막는다. 운영자는 blackout 자체를 news 해석기로 읽지 말고, replay blind spot을 줄이는 execution-risk 가드로 이해해야 한다.
- `MICRO_LIVE_ONLY`가 열렸을 때 운영 순서는 고정한다. `run_micro_live_preflight.py` 재확인 -> `run_micro_live_runtime_guard.py` 재확인 -> `run_micro_live_synthetic_canary.py` dry-run -> `run_runtime_signoff_review.py` 재확인 -> `APPROVED_*` + `session_impulse_retest CONFIRM` plan으로 `POST /execution/order-intents` (`execution_mode=MICRO_LIVE`) -> `POST /execution/submit` (`live=true`) 순서만 허용한다.
- 이 단계에서 live 제출 후보는 current MICRO_LIVE contract(`session_impulse_retest + CONFIRM + live core symbols`)를 따라야 한다. legacy `SWEEP_CONFIRM`/`LIMIT` sweep rows는 별도 계약 변경 없이는 live submit 대상이 아니다.
- `FULL LIVE` 확대는 별도 gate다. `runtime_effective_action == conditional_full_live_signoff` 또는 `proceed_to_operator_signoff`, `runtime_allowed_reopen_scope == MICRO_LIVE_OR_LIVE`, `runtime_operator_signoff_summary.status == ready_for_manual_full_live_signoff` 또는 `ready_for_operator_signoff`를 확인하고, `live_eligible_post_patch_closed_trade_count >= 30`, `live_eligible_post_patch_sample_summary.replay_p5_r >= -1.05`, `live_eligible_post_patch_sample_summary.stop_loss_share < 0.40`, `live_eligible_post_patch_sample_summary.worst_loss_streak < 5`, `live_execution_post_patch_closed_trade_count >= 5`까지 충족될 때만 검토한다.

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
- `runtime_self_heal_summary`
- `trend_proof_post_patch_sample_summary`
- `trend_proof_candidate_summary`

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
- 테스트는 항상 temp DB에서 돌아야 한다. `pytest`와 drill/watch 스크립트는 `DATABASE_URL`을 존중해야 하고, 실 [trading.db](/Users/yumin/Documents/trading/trading.db)를 테스트로 오염시키면 안 된다.
- `legacy` 전체 replay와 full `post-patch` close-fill cohort는 advisory truth로 유지한다. 실제 live go/no-go는 현재 `session_impulse_retest + CONFIRM + 11 core symbols` route와 safety/grid audit을 별도로 본다.
- `BTCUSDC + sweep_reversal + LIMIT`는 benchmark/legacy lens이며 현재 live allowlist가 아니다.
- `trend_continuation + LIMIT`는 운영 계약이 아니라 `trend proof lane`이다. lane count가 작을 때는 장 적합성 진단용으로만 본다.
- historical proof lane은 advisory context다. 이 값이 좋아도 live fill quality, order queue, reconciliation, liquidity, runtime parity를 대체하지 않는다.
- `MICRO_LIVE` 설정 변경은 `run_micro_live_safety_drag_audit.py`와 `run_micro_live_safety_grid_search.py` 결과를 같이 남긴 뒤 적용한다.
- `FULL LIVE`는 live fills/closes, reconciliation, slippage, forced exit, runtime parity가 충분해진 뒤에만 검토한다.
- `runtime_self_heal_summary`는 관측성 필드다. repeated stale cleanup / stale duplicate unblock이 반복되면 기능적으로는 통과여도 운영 품질 이슈로 취급한다.
- `MICRO_LIVE_ONLY`와 `MICRO_LIVE_OR_LIVE`는 같은 단계가 아니다. 전자는 검증용 제한 재개고, 후자는 추가 운영 확대를 검토할 수 있다는 뜻이다.
