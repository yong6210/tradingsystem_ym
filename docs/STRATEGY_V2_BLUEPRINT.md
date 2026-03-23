# Trading Strategy v2 Blueprint

최종 갱신: 2026-03-23
상태: Design baseline synchronized with runtime contract (implementation in progress)

## 1. 목적
- 패턴 나열형 전략에서 벗어나 `상태 -> 위치 -> 유동성 -> 반응 -> 실행` 순서로 의사결정한다.
- OB/FVG/트렌드라인을 독립 신호로 보지 않고, 유동성 이벤트 이후 실행 구역으로만 사용한다.
- 신호 추가보다 `no-trade`, `lock`, `thesis dedupe`, `A-only` 운영으로 성능을 개선한다.

## 2. 핵심 원칙
1. `Location first`: HTF extreme, prior session/day/week level, premium/discount가 먼저다.
2. `Liquidity first`: 왜 움직여야 하는지 설명되지 않으면 스킵한다.
3. `Reaction over pattern`: sweep 이후 `acceptance/rejection` 품질이 핵심이다.
4. `Execution zone is secondary`: OB/FVG는 실행 도구이지 전략 자체가 아니다.
5. `No-trade is a valid output`: transition/shock/mixed narrative에서는 적극적으로 스킵한다.
6. `One thesis, one risk`: 같은 thesis cluster에 중복 진입하지 않는다.
7. `Top-down is structural`: HTF 위치와 유동성이 먼저고, LTF 구조는 실행만 정교화한다.
8. `Session reference refines, not overrides`: session box / opening range는 intraday location을 보조할 뿐 HTF 위치와 유동성 narrative를 대체하지 않는다.

문서 해석 규칙:
- 본 문서는 `설계 목표`와 `현재 구현 메모`를 함께 기록한다.
- `현재 구현 메모`가 없는 항목은 설계 기준으로 읽고, 실제 런타임 강제 여부는 코드/테스트를 먼저 본다.
- 운영 가이드와 하드 게이트를 혼동하지 않는다.

## 3. 전략 계층
### Layer 1. Market State
- `trend`
- `range`
- `shock`
- `transition`

### Layer 2. Location
- weekly/daily extreme
- prior day/session high/low
- equal highs/lows
- premium/discount
- session opening range / premarket box (session liquidity reference only)

### Layer 3. Event
- liquidity sweep
- displacement
- rejection
- acceptance
- failed auction

### Layer 4. Execution
- `LIMIT`
- `CONFIRM`
- `SWEEP_CONFIRM`

### Layer 5. Risk
- invalidation clarity
- cost-adjusted EV
- thesis dedupe
- regime lock

## 4. 전략군 우선순위
1. `Sweep Reversal`
2. `Trend Continuation Pullback`
3. `Range Rotation`
4. `Breakout Acceptance`는 연구 전용으로 유지

운영 우선순위:
- `trend`: Trend Continuation Pullback > Sweep Reversal at extreme only
- `range`: Sweep Reversal > Range Rotation
- `shock`: no-trade 기본, exhaustion sweep reversal만 예외
- `transition`: no-trade 기본

현재 구현 메모:
- live family는 현재 `Sweep Reversal`, `Trend Continuation Pullback` 두 개다.
- `Range Rotation`은 `research_only`로 분리돼 live plan으로 승격되지 않는다.
- `Breakout Acceptance`는 아직 별도 family/service로 구현되지 않았다.

## 5. 중요도 체계
핵심 우선순위:
1. `Location`
2. `Liquidity narrative`
3. `Reaction quality`
4. `Invalidation clarity`
5. `HTF alignment`
6. `Execution zone quality`
7. `Session quality`

역할 정의:
- `유동성`: 왜 움직여야 하는가
- `반응 품질`: 실제로 움직였는가
- `OB/FVG`: 어디서 실행할 것인가
- `BOS/CHoCH`: continuation/reaction 해석 보조 증거
- `session box / outside close`: session liquidity reference + acceptance/rejection evidence candidate
- `트렌드라인`: 보조 컨텍스트(0~2 bonus 수준)

## 6. A/B/C 판정표
### Sweep Reversal
점수 항목:
1. `Location` 20
2. `Sweep quality` 20
3. `Reaction quality` 20
4. `Acceptance/Rejection clarity` 15
5. `HTF alignment` 10
6. `Execution zone quality` 10
7. `Session quality` 5

등급:
- `A`: 85+
- `B`: 75~84
- `C`: 68~74
- `<68`: no-trade

### Trend Continuation Pullback
점수 항목:
1. `HTF trend clarity` 20
2. `Impulse quality` 20
3. `Pullback quality` 20
4. `Protected low/high 유지` 15
5. `Execution zone freshness` 10
6. `Liquidity path clarity` 10
7. `Session quality` 5

등급:
- `A`: 85+
- `B`: 75~84
- `C`: 70~74
- `<70`: no-trade

### Range Rotation
점수 항목:
1. `Range definition` 20
2. `Edge proximity` 20
3. `Liquidity grab` 20
4. `Reversal quality` 15
5. `Range width` 10
6. `HTF conflict` 10
7. `Session quality` 5

등급:
- `A`: 83+
- `B`: 74~82
- `C`: 68~73
- `<68`: no-trade

## 7. Acceptance / Rejection 엔진
`Rejection confirmed` 조건:
1. sweep 후 `1~3 bar` 안에 level reclaim
2. 반대 방향 displacement `>= 1.2 x ATR(5m)`
3. reclaim 후 swept level 밖 close가 `1개 이하`
4. 반대 방향 inefficiency/FVG 생성
5. retest hold 성공

`Acceptance confirmed` 조건:
1. sweep 후 level 밖에서 `2 bar 이상 close`
2. retest 후 continuation
3. reclaim 실패
4. breakout 방향 displacement 유지
5. 반대 반응 약함

판정:
- `rejection_confirmed`: rejection 하드 조건 3개 + 보조 조건 1개 이상
- `rejection_tentative`: rejection 하드 조건 2개
- `acceptance_confirmed`: acceptance 하드 조건 3개 + 보조 조건 1개 이상
- `acceptance_tentative`: acceptance 하드 조건 2개
- 그 외는 `mixed = no-trade`

세부 계산/로그 계약:
- `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`

현재 구현 메모:
- generic 경로는 `mixed`, `acceptance_confirmed`, `acceptance_tentative`를 모두 차단한다.
- `rejection_tentative`는 허용하되 `LIMIT`를 금지하고 `CONFIRM only`로 강등한다.

## 8. Entry Model 선택 규칙
- `Sweep Reversal`
  - `A`: `SWEEP_CONFIRM` 우선, clean case면 `LIMIT`
  - `B`: `CONFIRM`
- `Trend Continuation Pullback`
  - `A`: `LIMIT`
  - `B`: `CONFIRM`
- `Range Rotation`
  - 설계 목표: `A/B`는 `CONFIRM`
  - 현재 구현: `research_only`, live entry 없음
  - range center는 금지

현재 구현 메모:
- `Sweep Reversal`: `A clean case -> LIMIT`, `A -> SWEEP_CONFIRM`, `B/C -> CONFIRM`
- `Trend Continuation Pullback`: `A -> LIMIT`, `B/C -> CONFIRM`
- `Range Rotation`: 점수화/등급화는 하지만 live order path에는 연결하지 않는다.

## 9. 포지션 사이징 함수
`final_risk = grade_risk x regime_factor x reaction_factor x thesis_factor x execution_factor`

초기값:
- `grade_risk`: `A=1.00R`, `B=0.50R`, `C=0.25R`
- `regime_factor`: `trend=1.00`, `range=0.80`, `shock=0.40`, `transition=0.00`
- `reaction_factor`: `rejection confirmed=1.00`, `confirm only=0.70`, `mixed=0.00`
- `thesis_factor`: none `1.00`, one active thesis `0.60`, two or more `0.00`
- `execution_factor`: `LIMIT=1.00`, `CONFIRM=0.85`, `SWEEP_CONFIRM=0.75`

## 10. Exit Engine
청산 사유:
1. `Target exit`
2. `Structure failure`
3. `Time failure`
4. `Information failure`

분할:
- `Sweep Reversal`: `40 / 40 / 20`
- `Trend Continuation`: `30 / 30 / 40`
- `Range Rotation`: `50 / 50 / 0` (설계값, 현재 research-only)

Time stop:
- `Sweep Reversal`: `3~5 bars`
- `Trend Continuation`: `5~8 bars`
- `Range Rotation`: `3 bars`

강제 청산:
- thesis가 `rejection -> acceptance`로 변경
- protected high/low 붕괴
- session quality 급락
- slippage/latency 이상 급증

현재 구현 메모:
- `ExitReason` enum과 `POST /internal/execution/fills` 종료 메타데이터 입력 경로가 반영됨
- `execution_fills.payload`와 `plan.validity.final_exit_reason`가 같은 계약을 공유함
- `GET /execution/quality`와 `POST /validation/report`에 exit-quality summary가 노출됨
- 자동 추론되는 종료 사유는 현재 `target`, `stop_loss`, `time_failure`, `information_failure`, `manual_flatten` 중심이다.
- `structure_failure`, `session quality 급락`, `slippage/latency 이상 급증`은 현재 explicit `exit_reason` 입력으로는 지원되지만, 엔진이 독립적으로 추론하진 않는다.

## 11. Lock Rules
### Daily Loss Lock
- `-2R`
- `3연속 손실`
- `A급 2연속 실패`
- 같은 thesis 해석 실수 2회 (설계 규칙, 현재 자동화 전)

### Shock Lock
- jump 급증
- wick/body 비율 악화
- 슬리피지 급증
- level reaction 붕괴

조치:
- `LIMIT 금지`
- `CONFIRM only`
- size `60% 축소`
- continuation 금지

현재 구현 메모:
- `OperatingLockService`가 `daily_realized_r`, `session_realized_r`, `loss_streak`, `A-grade loss streak`를 기준으로 live mode를 잠근다
- 현재 session lock은 `London/NY 활성 세션의 손실 기반 잠금`이며, dead session 일반 하드블록은 별도 규칙이다
- unlock은 `daily -> next UTC day`, `session -> current session end`
- `RESEARCH`는 shadow-only라 lock을 강제하지 않고 보고만 한다
- shock 대응은 현재 `regime=shock` 경로에서 구현된다.
  - `LIMIT -> CONFIRM` 강등
  - sizing `0.40R`
  - `Sweep Reversal`은 `A급 + rejection_confirmed`가 아니면 차단
- wick/body 악화와 슬리피지 급증만으로 별도 `shock lock` 상태를 여는 자동화는 아직 없다.

### Transition Lock
- 양방향 sweep 반복
- acceptance/rejection 혼탁
- FVG/OB 무력화 반복

조치:
- 기본 `no-trade`
- 예외는 `A급 Sweep Reversal`
- `confirm only`

정량 기준:
- `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`

현재 구현 메모:
- `transition_confirmed`는 즉시 `no-trade`다.
- `transition_watch`는 최소 `confirm only`이며, `A`가 아닌 `Sweep Reversal`도 차단된다.

## 12. Thesis Dedupe
같은 thesis로 보는 기준:
1. 같은 direction
2. 같은 regime
3. 같은 liquidity narrative
4. 상관도 높음
5. 발생 시점 유사

운영 규칙:
- 같은 thesis는 `1개만 full size`
- BTC와 ETH가 같으면 BTC 우선 (설계 규칙, 현재 고정 하드코드 없음)
- 알트는 `더 짧은 invalidation + 더 높은 EV`일 때만 승격

세부 fingerprint 계약:
- `docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`

현재 구현 메모:
- 현재 primary symbol 선정은 `짧은 invalidation -> 높은 EV -> 낮은 cost -> 높은 confidence` 우선순위다.
- `BTC 우선`은 명시적 예외 규칙으로 하드코드돼 있지 않다.

## 13. 운영 모드
### Mode A-only
- `A급만`
- London / NY 중심
- `Sweep Reversal` + `Trend Continuation`만
- 하루 최대 `3 trades`
- 동시 총노출 `1.5R`

### Mode A+B
- `B급` half-size 허용
- 하루 최대 `5 trades`
- 현재 구현 기본 cap: 동시 총노출 `2.0R`

### Research Mode
- `C급` 실거래 금지
- shadow log만 유지
- 현재 구현은 `recommended_risk_r = 0.00`으로 고정

현재 구현 메모:
- `London / NY 중심`은 현재 운영 가이드이지 하드 세션 게이트는 아니다.
- `A_ONLY`, `A_PLUS_B`는 family/grade와 risk cap을 강제하고, `RESEARCH`는 `shadow_only`로 남긴다.
- legacy generic plan은 회귀 호환을 위해 mode hard block에서 임시 passthrough다.

## 14. No-Trade State
다음은 명시적으로 스킵:
1. transition
2. mixed narrative
3. dirty reaction
4. dead session
5. portfolio saturation
6. revenge/re-entry impulse
7. OB-only / FVG-only / trendline-led setup

현재 구현 메모:
- 현재 하드 게이트:
  - `transition_confirmed`
  - `mixed`
  - `acceptance_confirmed / acceptance_tentative`
  - `OB-only / FVG-only / trendline-led`
  - `range center`
  - thesis saturation / mode cap / operating lock
- 현재 운영 가이드 또는 후행 자동화 항목:
  - `dead session`
  - `revenge/re-entry impulse`
  - `same thesis 해석 실수 2회`

## 15. 검증 기준
운영 전 확인:
1. `A-only` vs `A+B` 비교
2. shock/transition lock 적용 전후 차이
3. thesis dedupe 적용 전후 max drawdown
4. time stop 적용 전후 EV 변화
5. cost `x1.5`, slippage `x2` stress test
6. `walk-forward`, `Monte Carlo`, `PBO/DSR`

세부 프로토콜:
- `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`
- 현재 구현은 첫 비교 축인 `A-only` vs `A+B`를 `strategy_v2_validation` 템플릿으로 자동 산출한다.
- 현재 구현은 두 번째 비교 축인 `transition/shock lock` 적용 전후도 `strategy_v2_lock_validation` 템플릿으로 자동 산출한다.
- 현재 구현은 네 번째 비교 축인 `cost x1.5 / slippage x2`도 `strategy_v2_stress_validation` 템플릿으로 자동 산출한다.
- 현재 구현은 같은 `strategy_v2_stress_validation` 템플릿 안에 `latency +1 bar`, `partial fills only`, `shock concentration` 시나리오도 추가로 산출한다.
- 현재 구현은 `strategy_v2_stress_replay_assessment`로 stress 근사를 full replay로 대체할 준비도/우선순위를 자동 노출한다.
- 현재 구현은 `strategy_v2_stress_replay_lineage`로 full replay 전환에 필요한 writer/runtime input lineage 준비도와 gap을 자동 노출한다.
- 현재 구현은 `strategy_v2_stress_replay_runner_contract`로 scenario readiness, prototype batching, worker IO contract를 validation 경로에서 바로 노출한다.
- 현재 구현은 `strategy_v2_stress_replay_lineage_writer`로 per-scenario replay lineage batch artifact(JSON)를 validation 경로에서 바로 materialize한다.
- 현재 구현은 세 번째 비교 축인 `thesis dedupe` 적용 전후도 `strategy_v2_thesis_validation` 템플릿으로 자동 산출한다.
- 현재 구현은 `strategy_v2_pbo_dsr_trial_writer`로 `mode/lock/stress` runtime proxy trial/fold lineage와 `scoring_thresholds/transition_threshold/acceptance_rejection_thresholds/sizing_clamps` stored-plan threshold proxy family를 함께 seed한다.
- 현재 구현은 `strategy_v2_pbo_dsr_metrics`로 seeded artifact 기준 PBO/DSR를 계산하고, `strategy_v2_pbo_dsr_artifact_store`/`strategy_v2_pbo_dsr_design`으로 lineage와 설계 상태를 함께 노출한다.
- 현재 구현은 `POST /operations/checklist`로 운영 체크리스트를 단일 API/markdown으로 집계하고, `session_guidance`로 dead-session 경고를 노출한다.
- 현재 구현은 `GET /scanner/top`와 `GET /portfolio/budget` 후보 row에도 `session_guidance`, `session_penalty`를 붙여 candidate-level soft penalty를 노출한다.

## 16. 현재 판단
- 전략의 본질은 `패턴`이 아니라 `상태 기반 운영`
- 성능 개선의 핵심은 `신호 추가`보다 `나쁜 상태 제거`
- 현재 `A-only` vs `A+B` 비교 리포트와 청사진-코드 동기화는 완료됐다
- 현재 `transition/shock lock` 적용 전후 비교도 자동화됐다
- 현재 `thesis dedupe 적용 전후 drawdown 비교`도 자동화됐다
- 현재 `cost x1.5 / slippage x2 stress report`도 자동화됐다
- 현재 `latency +1 bar / partial fills only / shock concentration` stress 축도 같은 validation 경로에 반영됐다
- 현재 `stress full replay replacement assessment`도 자동화돼, stress 근사 유지/대체 우선순위를 validation 경로에서 바로 본다
- 현재 `stress replay writer/runtime lineage contract`도 자동화돼, full replay 전환 입력 준비도와 fallback source를 validation 경로에서 바로 본다
- 현재 `stress replay runner/worker contract`도 자동화돼, full replay prototype job이 어떤 입력/출력과 batch 규칙을 가져야 하는지 validation 경로에서 바로 본다
- 현재 `stress replay lineage writer`도 자동화돼, scenario별 prototype input batch가 어떤 trade rows로 구성되는지 artifact 수준에서 바로 본다
- 현재 `stress replay output artifact reader`도 자동화돼, replay worker output이 있으면 stress approximation payload와 직접 비교한다
- 현재 `stress replay prototype worker`도 자동화돼, lineage batch artifact를 읽어 scenario별 replay output artifact와 markdown을 실제 실행 경로에서 생성한다
- 현재 `strategy_v2_stress_validation.deployment_recommendation`은 replay output artifact가 있는 scenario를 `replay_output` source로 승격해 worst scenario와 stress gate를 재평가한다
- 현재 `strategy_v2_stress_replay_assessment.true_runner_readiness`와 `strategy_v2_stress_replay_runner_contract.true_runner_readiness`가 true market replay runner replacement readiness를 별도 gate로 노출한다
- 현재 `strategy_v2_pbo_dsr_metrics.lineage_audit`가 dual-lineage 상태에서 selected trial source를 audit하고, runtime proxy selected-trial이면 deployment recommendation을 lineage warning으로 내린다
- 현재 `strategy_v2_stress_validation.deployment_recommendation`은 replay-backed scenario의 `divergence_status`까지 정책축으로 반영해, approximation과 차이가 큰 replay output은 별도 warning/fail로 승격한다
- 현재 `strategy_v2_stress_replay_assessment.deployment_recommendation.true_runner_promotion_*`가 true-runner readiness와 threshold lineage audit를 함께 해석해, selected trial이 runtime proxy면 `true_runner_ready=true`여도 `stay_on_prototype`으로 막는다
- 현재 `strategy_v2_pbo_dsr_metrics.selection_universe_summary`와 `strategy_v2_pbo_dsr_artifact_store.selection_universe_summary`가 `combined artifact universe`와 `full parameter-sweep universe`를 분리 기록하고, DSR bias adjustment는 `full_parameter_sweep_universe`가 있으면 그 기준을 우선 사용한다
- 현재 `strategy_v2_stress_replay_output_artifacts.lineage_summary`가 replay output provenance를 집계하고, `strategy_v2_stress_replay_assessment.deployment_recommendation.replay_output_lineage_alignment_*`가 selected-trial lineage audit와 replay output lineage를 같은 승격 계약으로 묶는다
- 현재 `strategy_v2_stress_replay_assessment.deployment_recommendation.approval_cross_display`와 `validation_report.deployment_approval_summary`가 threshold lineage winner와 replay-derived worst scenario를 같은 approval template에서 직접 교차 표시한다
- 현재 `approval_cross_display.approval_warning_locked/code/message`가 runtime proxy winner가 replay-backed worst scenario와 동시에 남는 경우 approval template 경고 문구를 직접 고정한다
- 현재 `deployment_approval_summary.topline_status/code/message`가 replay output lineage alignment warning을 approval template 최상단 승인 문구에 직접 반영한다
- 현재 `deployment_approval_summary.topline_summary_line`가 threshold lineage winner / replay-derived worst scenario / true-runner promotion action을 한 줄로 요약한다
- 현재 `deployment_approval_summary.playbook_go_no_go/code/action/message`가 approval template warning code를 운영 playbook의 `GO / NO_GO / MANUAL_REVIEW` 문구로 직접 매핑한다
- 현재 `deployment_approval_summary.topline_message`, `operations/checklist.deployment_*`, `scanner.top[*].deployment_*`가 같은 `GO / NO_GO / MANUAL_REVIEW` 언어를 사용한다
- 현재 `validation_alert.approval_topline_summary_line`가 approval template one-line summary를 alert payload/메시지까지 그대로 전달한다
- 현재 `validation_alert.approval_playbook_go_no_go/code/action/message`가 approval template playbook mapping을 alert payload/재시도 payload/outbox payload까지 그대로 전달한다
- 현재 `GET /portfolio/budget` top-level `deployment_go_no_go/code/message`와 portfolio markdown summary도 같은 `GO / NO_GO / MANUAL_REVIEW` 언어를 사용한다
- 현재 `validation_alert.deployment_go_no_go/code/message`가 alert payload에 직접 기록되고, `alerts/metrics.latest_validation_alert`, `operations/checklist` evidence도 같은 배포 언어를 직접 노출한다
- 현재 `alerts/metrics.latest_validation_alert.approval_playbook_go_no_go/code/action/message`와 `operations/checklist.alert_channel_slo.evidence.latest_validation_alert`도 같은 playbook mapping을 직접 노출한다
- 현재 `operations/checklist.validation_alert_delivery.evidence.approval_playbook_go_no_go/code/action/message`도 `validation_alert.approval_playbook_*`를 top-level evidence로 직접 노출한다
- 현재 `operations/checklist.portfolio_headroom.evidence.deployment_go_no_go/code/message`도 `/portfolio/budget` top-level 배포 언어를 직접 노출한다
- 현재 `GET /portfolio/budget` top-level `playbook_go_no_go/code/action/message`와 portfolio markdown summary도 runtime deployment code 기반 운영 액션 문구를 직접 노출한다
- 현재 validation alert 채널 메시지도 `playbook_action=<approval_playbook_action>`를 직접 포함해 운영 액션 문구를 단독 메시지에서 확인할 수 있다
- 현재 `POST /alerts/test` 응답도 `deployment_*`, `approval_playbook_*`를 top-level로 직접 반환해 manual alert drill 경로가 같은 contract를 사용한다
- 현재 `POST /alerts/subscribe` 응답도 `deployment_*`, `approval_playbook_*`를 top-level로 직접 반환해 manual subscribe 경로가 same contract를 사용한다
- 현재 `POST /validation/report` top-level도 `deployment_*`, `approval_topline_*`, `playbook_*`를 직접 반환하며, validation summary passthrough가 operations/report contract의 단일 기준이다
- 현재 `operations/checklist.portfolio_headroom.evidence.playbook_go_no_go/code/action/message`도 `/portfolio/budget` top-level playbook 문구를 직접 노출한다
- 현재 `POST /operations/checklist` top-level `playbook_go_no_go/code/action/message`도 validation/report/portfolio와 같은 수준의 운영 액션 문구를 직접 노출한다
- 현재 validation alert 채널 메시지도 `deployment=<go_no_go>/<code>`를 직접 포함해 `approval=` one-line summary와 함께 배포 언어를 노출한다
- 현재 `app/services/deployment_contracts.py`가 alert/report deployment-playbook contract의 공통 helper로 고정되어, alert/test/subscribe/metrics/checklist/message formatter와 validation top-level consumer가 같은 fallback contract를 재사용한다
- 현재 active rollout backlog와 active post-rollout refactor backlog는 모두 비어 있으며, 남은 항목은 첫 라이브 운영 사이클 이후 contract pruning optional hold뿐이다
- 현재 prototype worker는 true market replay가 아니라 deterministic contract-validation worker이며, full replay 대체 자체는 후속 단계다
- 현재 `PBO / DSR runtime proxy trial writer`도 hybrid 형태로 자동화돼, validation 루프가 runtime proxy와 stored-plan threshold proxy trial/fold lineage를 직접 seed한다
- 현재 `strategy_v2_pbo_dsr_threshold_runner`도 연결돼, true threshold-sweep lineage가 runtime proxy lineage와 분리된 `selection_rule`로 같은 artifact store에 seed된다
- 현재 `PBO / DSR 검증 설계 payload`, `runtime artifact store payload`, `metric payload`도 validation 경로에 반영됐고, threshold family coverage도 trial writer payload에서 직접 본다
- 현재 `실전 운영 체크리스트 -> API/리포트 집계`와 `session/dead-session guidance`도 반영됐다
- 현재 `session/dead-session guidance`는 scanner/portfolio 후보 수준까지 승격됐지만, 여전히 hard block이 아니라 soft penalty로만 동작한다
- review-type deployment/playbook backlog는 일단 정리 완료 상태이고, 다음 비검토 포커스는 top-level contract 최종 정리다
