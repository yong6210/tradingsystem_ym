# Trading Engine v1 전략 운영 매뉴얼

최종 갱신: 2026-03-23

## 1. 목적
이 문서는 현재 구현된 전략 엔진을 운영/튜닝할 때 기준이 되는 단일 참조 문서다.
핵심 목표는 다음 3가지다.
- 신호 남발 억제
- 레짐 적응
- 검증 가능한 성능 개선

## 2. 전략 파이프라인
1. `candles(5m/15m)` 수집
2. `ZoneEngine`에서 LP/OB/FVG/FLIP 생성 및 병합
3. `ContextEngine`에서 F/V/A, Jump/Friction, `regime_label` 계산
4. `PlanGenerator`에서 레짐별 프로파일로 컨플루언스 점수 산출
5. 하드 게이트 통과 신호만 EV/RR/Cost 계산 후 플랜 생성
6. 메타 필터(2차 게이트)로 저품질 신호 차단
7. `RiskGate` 상태를 반영해 신규 플랜 허용/차단
8. `zone_outcomes` 기반 학습 업데이트 및 검증 리포트 생성
9. 실체결 이벤트(`execution_fills`)로 포지션 상태머신 전이(`TRIGGERED -> ENTERED -> PARTIAL_EXIT -> CLOSED`)
10. `ExecutionQualityService`에서 `execution_fills` 기반으로 슬리피지/latency/fee/stage coverage와 `strategy_version` 비교 리포트 생성

## 3. 레짐 분리 규칙
- `trend`: 방향성 강하고 점프/마찰이 통제된 구간
- `range`: 중립 구간
- `shock`: 점프율 또는 마찰이 과열된 구간

레짐 프로파일(코드 기준):
- `trend`
  - `min_confluence = base + 4`
  - `rr_floor = max(min_rr, 1.30)`
  - `ev_floor = 0.00`
- `range`
  - `min_confluence = base`
  - `rr_floor = min_rr`
  - `ev_floor = 0.00`
- `shock`
  - `min_confluence = base + 10`
  - `rr_floor = max(min_rr, 1.45)`
  - `ev_floor = 0.05`
  - `LIMIT` 진입 제한(확인형 진입 우선)

## 4. 컨플루언스/중요도 체계
컨플루언스 구성 요소:
- 유동성 (`liquidity`)
- FVG/변위 (`fvg_displacement`)
- 상위TF 정렬 (`htf_alignment`)
- OB 신선도 (`ob_freshness`)
- 트렌드 프록시 (`trend_proxy`)

기본 중요도(설정값):
- liquidity 0.35
- fvg_displacement 0.25
- htf_alignment 0.20
- ob_freshness 0.15
- trend_proxy 0.05

주의:
- 레짐별로 위 중요도는 동적으로 재가중된다.
- Zone 타입(OB/FVG/LP/FLIP)도 별도 multiplier를 가진다.

## 5. 신호 차단 정책
### 5.1 하드 게이트
다음 중 하나면 진입 스킵:
- confluence 미달
- 마찰 과열(`friction_hard_gate` 이상)
- 점프 과열(`jump_hard_gate` 이상)
- 강추세 역방향(비 range 레짐)
- shock 레짐에서 FLIP 타입

### 5.2 자동 비활성화
표본이 충분(`auto_disable_min_samples`)한데 아래 조건이면 셋업 비활성화:
- `ev_r <= auto_disable_ev_r_threshold`
- 또는 `p1r/p2r` 동시 저조

### 5.3 중복 억제
동일 심볼/동일 방향/근접 엔트리(ATR 기준)는 1개만 유지한다.

## 6. 학습 루프
`LearningService.summarize`에서 계산:
- `p1r`, `p2r`, `p3r` (베이지안 스무딩)
- `avgMFE`, `avgMAE`
- `sweep_success_rate`
- `ev_r` (기대 R)

`update_zone_quality`는 `base_strength`와 학습 품질을 블렌딩하며,
표본 수가 적은 구간에서 과신을 줄이도록 샘플 팩터를 사용한다.

피처 중요도(Ablation):
- 기준 플랜 대비 `liquidity/fvg_displacement/htf_alignment/ob_freshness/trend_proxy`를
  하나씩 0으로 둔 시나리오를 비교해 중요도를 계산한다.
- API: `GET /validation/feature-importance?symbol=...`

중요도 온라인 캘리브레이션:
- 최근 `plan.validity.confluence_components`와 `zone_outcomes`를 매칭해 실현 R 기준 feature signal을 계산하고, 이를 EWMA로 스무딩해 레짐별 중요도 가중치를 재조정한다.
- `feature_importance.baseline.generated_plans`는 runtime 적용 최소 기준 검사에 사용한다.
- 한 번의 업데이트는 `feature_calibration_max_delta` 범위 내에서만 허용한다.
- zone type(`OB/FVG/LP/FLIP`)도 최근 성과에 따라 bounded multiplier를 별도로 조정한다.
- 최신 snapshot이 있으면 플랜 생성 시 `feature_weights_active`로 runtime 반영된다.
- API: `GET /validation/feature-calibration?symbol=...`

운영 확인 포인트:
- `matched_samples`
- `baseline_generated_plans`
- 상위 weight delta 3개
- `zone_type_multipliers`

## 7. 리스크 운용 규칙
`RiskGate` 상태:
- `OPEN`: 신규 진입 허용
- `THROTTLED`: 신규 진입 제한
- `CLOSED`: 신규 진입 차단

차단 트리거:
- 연속 손실 한도 초과
- 점프율 한도 초과
- 인프라 비정상

포트폴리오 오버레이(스캐너):
- 고상관(`portfolio_overlay_high_corr_threshold`) 동방향 노출이 `portfolio_overlay_max_cluster_exposure` 이상이면 후보 차단
- 총 노출(`portfolio_overlay_max_total_exposure`) 및 방향별 노출(`portfolio_overlay_max_directional_exposure`) 상한 적용
- 고상관 정도에 비례한 점수 패널티를 반영해 과집중 후보의 우선순위를 자동 하향
- v2에서는 5m realized volatility와 후보 `regime`를 합산해 `risk_budget_score`를 계산한다.
- `shock` 후보는 동적 cap이 더 작아지며, `trend/range/shock`별로 total/directional/cluster cap이 달라진다.
- 운영 확인 필드: `risk_budget_score`, `portfolio_volatility`, `portfolio_total_cap`, `portfolio_directional_cap`, `portfolio_cluster_cap`
- 통합 확인 경로: `GET /portfolio/budget` 또는 `scripts/generate_portfolio_budget_report.py`

## 8. 검증/배포 정책
필수 확인 항목:
1. 테스트 전체 통과
2. `/validation/report` 결과 PASS 또는 허용 가능한 WARN
3. WARN/FAIL 발생 시 자동 알림(`validation.warn`/`validation.fail`) 확인
4. `validation_alert.delivery` 상태(`delivered/skipped/failed`) 확인
5. 운영 시작 전 `POST /alerts/test`로 채널(`telegram/discord/push/system`) 연결 확인
6. Outbox 백로그/재시도 상태 정상
7. 리스크 게이트가 운영 시작 시 OPEN

권장 배포 순서:
1. demo/bootstrap 환경 검증
2. REST 백필 기반 페이퍼 운용
3. WS 상시 수집 연결 후 소규모 반자동

### 8.1 포지션 상태머신 운영 규칙
- 체결 이벤트는 `POST /internal/execution/fills`로 인입한다.
- `fill_id`는 멱등 키이며, 동일 `fill_id` 재주입 시 상태 변경 없이 `duplicate_fill_id`로 처리된다.
- 상태 전이는 단방향만 허용한다. (`ENTRY` 이후 `TRIGGERED` 같은 역전이는 적용되지 않음)
- plan 미존재 이벤트는 404로 거절한다.

### 8.2 실행 품질 리포트 운영 규칙
- `GET /execution/quality`와 스크립트 리포트는 `execution_fills`를 1차 데이터 소스로 사용한다.
- 체결 원장이 없는 과거 기간만 `zone_outcomes` 기반 fallback을 허용한다.
- 운영 판단에 사용하는 핵심 지표는 `fill_sources`, `stage_counts`, `slippage_bps`, `entry_latency_seconds`, `fees`, `unfilled_reason_details`, `by_strategy_version`, `version_comparison`이다.
- 버전 롤아웃 전에는 `timed_out_after_trigger`, `order_rejected`, `expired_after_touch_confirmation`이 특정 `strategy_version`에 편중되는지 먼저 확인한다.

### 8.3 알림 채널 메트릭 운영 규칙
- `GET /alerts/metrics`와 스크립트 리포트로 채널별 `success_rate`, `failure_rate`, `latency_ms.p95`, `circuit_state`, `error_budget`, `retry_queue`를 확인한다.
- leaf 채널 기준 `overall` SLO를 운영 기준으로 보고, `system` 채널은 fanout 집계 상태를 별도로 본다.
- `circuit_open_count > 0` 또는 `slo.status=FAIL`이면 라이브 운영 전 채널 복구와 `/alerts/test` 재검증이 필요하다.

### 8.4 알림 재시도 큐 운영 규칙
- 실패 전송 중 재시도 가능한 건(`http_429`, `http_5xx`, `exception:*`, `circuit_open`)만 `alert_retry_queue`에 적재한다.
- dead-letter로 이동한 항목은 자동 복구 대상이 아니며, `/internal/alerts/retry-queue/dead-letter/requeue` 또는 `scripts/process_alert_retry_queue.py --requeue-dead-letter`로만 수동 재전송한다.
- 운영 점검 순서:
  1. `GET /alerts/metrics`에서 `retry_queue.counts.dead_letter`
  2. `GET /internal/alerts/retry-queue/status`
  3. 필요 시 `POST /internal/alerts/retry-queue/process`
  4. dead-letter만 별도 requeue

### 8.4a Subscription 기반 lifecycle 알림 운영 규칙
- `POST /alerts/subscribe`는 현재 `near`, `touch`, `confirm`, `entry`, `tp`, `sl`, `partial_exit`, `closed` 타입을 지원한다.
- `refresh_symbol()` live refresh 경로는 active plan에 대해 아래 pre-entry alert를 평가한다.
  - `near`: 현재 가격이 `entry_price`에서 `ATR5 * signal_alert_near_atr_multiple` 이내
  - `touch`: 최신 5m candle range가 `entry_price`를 포함
  - `confirm`: `touch` 상태이면서 `entry_model != LIMIT`
- `POST /tv/webhook`는 external `near/touch/confirm` event를 그대로 matching subscription으로 fanout할 수 있다.
- `POST /internal/execution/fills`는 fill stage 기준 lifecycle alert를 자동 fanout한다.
  - `ENTRY` -> `entry`
  - `PARTIAL_EXIT` -> `partial_exit` (`target_tp*`면 `tp`도 추가)
  - `CLOSED` -> `closed` (`target_tp*`면 `tp`, `stop_loss`면 `sl`도 추가)
- 동일 `plan/channel/type` 조합은 `signal_alert_cooldown_seconds` 동안 cooldown 처리한다.
- subscription row와 emitted alert row는 같은 `alerts` 테이블을 쓰지만, `payload.subscription_active=true` marker로 구분한다.
- 운영 점검 경로:
  1. `POST /alerts/subscribe`
  2. `POST /internal/binance/sync` 또는 live refresh
  3. `POST /tv/webhook` 또는 `POST /internal/execution/fills`
  4. `GET /alerts/metrics` / `POST /operations/checklist`

### 8.5 포트폴리오 통합 버짓 리포트 운영 규칙
- `GET /portfolio/budget`와 스크립트 리포트는 현재 노출(`current_exposure`)과 후보 평가(`accepted_candidates`, `blocked_candidates`)를 같은 기준으로 본다.
- 운영 판단에 사용하는 핵심 필드는 `headroom_by_regime`, `blocked_reason_counts`, `current_positions`, `risk_state`, `risk_reason`이다.
- `blocked_reason_counts`가 `total_cap_reached` 중심이면 총노출 축소 또는 포지션 정리가 우선이고, `directional_cap_reached` 중심이면 방향 편중 완화가 우선이다.
- `cluster_cap_reached`가 누적되면 같은 thesis/상관 클러스터 과집중으로 보고 신규 진입보다 기존 익스포저 정리를 먼저 검토한다.
- `thesis_duplicate_blocked`가 누적되면 동일 thesis 중복 배치가 원인이고, `thesis_active_cap_reached`가 누적되면 active thesis cluster cap이 병목이다.
- 운영 점검 시 `current_exposure.active_thesis_clusters`, `current_positions[].thesis_cluster_id`, `accepted_candidates[].thesis_primary_symbol`을 같이 본다.

### 8.6 Transition State Engine 운영 규칙
- `transition_score`, `transition_state`, `transition_features`, `transition_lock_reason`는 `ContextSnapshot`과 plan `validity`에 함께 남긴다.
- `transition_confirmed`면 현재 엔진은 신규 플랜을 생성하지 않는다. 운영 해석은 `no-trade`다.
- `transition_watch`면 현재 엔진은 `LIMIT`를 허용하지 않고 `CONFIRM`으로 강등한다.
- 운영 점검 시에는 `transition_features`에서 `bidirectional_sweep_churn`, `reaction_failure_cluster`, `wick_dominance`, `zone_invalidation_churn`이 어떤 조합으로 점수를 만들었는지 먼저 본다.

### 8.7 Acceptance/Rejection Classifier 운영 규칙
- classifier 입력 계약은 `ATR(5m)`, `reclaim_bars`, `outside_close_count`, `dwell_time_bars`, `inefficiency_created`, `retest_hold`를 기본 필드로 사용한다.
- `reaction_classification=mixed`면 현재 엔진은 신규 플랜을 만들지 않는다.
- `reaction_classification in {acceptance_confirmed, acceptance_tentative}`면 reversal 성격 후보를 차단한다.
- `reaction_classification=rejection_tentative`면 `LIMIT`를 허용하지 않고 `CONFIRM`으로 강등한다.
- 운영 점검 시에는 plan `validity`의 `reaction_classification`, `reaction_rejection_score`, `reaction_acceptance_score`, `reaction_input`을 함께 본다.

### 8.7A External Vocabulary Translation
- 외부 방법론의 `BOS/CHoCH`는 운영 해석상 독립 신호가 아니라 `reaction evidence`로만 읽는다.
- 외부 방법론의 `FVG/OB`는 독립 알파가 아니라 `execution zone`으로만 읽는다.
- 외부 방법론의 `session box / opening range / premarket range`는 `session liquidity reference`로만 읽는다.
- `1m close outside level`은 `acceptance/rejection evidence candidate`일 수는 있지만 standalone approval 근거는 아니다.
- `failed outside close / return inside session box`는 `rejection evidence candidate`일 수 있지만, 여전히 HTF 위치와 liquidity narrative 아래에서만 해석한다.
- `mechanical execution`은 별도 실행 권한이 아니라 `operator checklist compliance`를 뜻한다.
- session box vocabulary는 별도 execution authority를 만들지 않으며, `approval`, `risk`, `sizing` source-of-truth를 우회하지 않는다.
- runtime source-of-truth는 계속 `reaction_classification`, `reaction_input`, `strategy_family`, `strategy_grade`, `recommended_risk_r`다.

### 8.8 Strategy Sizing v2 운영 규칙
- sizing 공식은 `grade_risk x regime_factor x reaction_factor x thesis_factor x execution_factor`를 사용한다.
- 운영 판단의 기준 필드는 `validity.strategy_sizing`와 `validity.recommended_risk_r`다.
- 후보 설명의 기준 필드는 `expected_win_prob`, `expected_ev_r`, `expected_tp1_prob`, `expected_tp2_prob`, `expected_tp3_prob`, `expected_summary`다.
- `expected_win_prob`는 이제 `expected_win_prob_base + expected_win_prob_adjustment` 구조를 가지며, `expected_win_prob_components`로 `grade/reaction/entry_model/confluence/regime/friction/near_lp` 기여도를 확인할 수 있다.
- 현재 구현에서 `transition_watch`, `transition_confirmed`, `reaction_classification=mixed`, `active thesis cluster >= 2`는 모두 `recommended_risk_r = 0.00`으로 본다.
- `GET /scanner/top`과 `GET /portfolio/budget`은 같은 `strategy_sizing` 계약을 공유해야 하며, 서로 다른 수치가 나오면 버그로 본다.

### 8.9 Strategy Mode 운영 규칙
- 현재 구현 모드는 `A_ONLY`, `A_PLUS_B`, `RESEARCH`다.
- 기본 운영 모드는 `A_ONLY`다.
- mode 기본값:
  - `A_ONLY`: `A급`만, `daily_trade_limit=3`, `max_total_risk_r=1.5`
  - `A_PLUS_B`: `A/B급`, `daily_trade_limit=5`, `max_total_risk_r=2.0`
  - `RESEARCH`: `shadow-only`, `recommended_risk_r=0.00`
- `GET /portfolio/budget`의 `mode_policy`, `mode_stats`로 현재 모드의 cap과 사용량을 함께 본다.
- 현재 구현은 v2 family-tagged plan에는 mode grade/family 제한을 직접 적용하고, legacy generic plan은 회귀 호환을 위해 임시 passthrough로 남긴다.

### 8.10 Exit Engine 운영 규칙
- 종료 사유 계약은 `docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`를 따른다.
- 현재 구현은 `POST /internal/execution/fills`에서 `exit_reason`, `held_bars`, `classification_before_exit`, `classification_after_exit`, `trigger_detail`를 함께 받을 수 있다.
- family time stop은 plan `validity.strategy_family_time_stop_max_bars`를 기준으로 적용한다.
  - `sweep_reversal`: `3~5 bars`
  - `trend_continuation`: `5~8 bars`
  - `range_rotation`: `3 bars` (현재 research-only)
- `rejection -> acceptance` 또는 `mixed` 반전으로 닫히는 최종 청산은 `information_failure`로 기록한다.
- 운영 점검 필드:
  - `plan.validity.final_exit_reason`
  - `plan.validity.final_exit_trigger_detail`
- `GET /execution/quality`의 `final_exit_reasons`, `target_exit_ratio`, `forced_exit_ratio`, `information_failure_ratio`, `time_failure_ratio`, `by_strategy_family`
- `POST /validation/report`의 `execution_quality` 요약과 `GET /execution/quality` 수치가 다르면 먼저 체결 원장/집계 경로 불일치를 의심한다.

### 8.11 Daily / Session Lock 운영 규칙
- 현재 구현은 `OperatingLockService`가 live mode(`A_ONLY`, `A_PLUS_B`)에서만 강제한다. `RESEARCH`는 shadow-only라 block하지 않는다.
- 현재 session lock은 `London/NY 활성 세션의 손실 기반 잠금`이며, `dead session` 일반 하드블록은 별도 규칙으로 유지된다.
- daily lock 조건:
  - `daily_realized_r <= -2.0R`
  - `3연속 손실`
  - `A급 2연속 실패`
- session lock 조건:
  - London/NY 세션에서 `session_realized_r <= -1.5R`
  - London/NY 세션에서 `2연속 손실`
- unlock 정책:
  - daily lock: `다음 UTC day`
  - session lock: `현재 세션 종료`
- 운영 점검 필드:
  - `GET /metrics/strategy`의 `risk_reason`, `operating_lock`
  - `GET /scanner/top`의 row-level `risk_reason`, `operating_lock`
  - `GET /portfolio/budget`의 `risk_reason`, `operating_lock`, `mode_stats`
- `risk_state=CLOSED`인데 `operating_lock.active=false`면 기존 infra/jump/consecutive-loss gate를 우선 의심하고, `operating_lock.active=true`면 당일 손실 통계를 먼저 확인한다.

### 8.12 Strategy v2 Validation 비교 규칙
- `POST /validation/report`는 현재 기본 validation markdown 외에 `strategy_v2_validation` 템플릿을 함께 생성한다.
- 비교 기준은 현재 `A_ONLY` vs `A_PLUS_B` 한 축이며, 집계 소스는 `closed v2 plans`의 `strategy_family`, `strategy_grade`, `final_exit_realized_r`, `final_exit_reason`, `final_exit_held_bars`다.
- 운영 점검 필드:
  - `strategy_v2_validation.mode_metrics.A_ONLY`
  - `strategy_v2_validation.mode_metrics.A_PLUS_B`
  - `strategy_v2_validation.comparison`
  - `strategy_v2_validation.deployment_recommendation`
- 해석 순서:
  - `p5 EV`
  - `max_drawdown`
  - `ulcer_index`
  - `forced_exit_ratio`
  - `information_failure_ratio`
- 현재 기본 배포 권고는 여전히 `A_ONLY`다. `A_PLUS_B`는 incremental B 샘플이 충분하고 하방 손상이 확인되지 않기 전까지 연구 모드 해석으로 본다.

### 8.13 Transition / Shock Lock 비교 규칙
- `POST /validation/report`는 현재 `strategy_v2_lock_validation` 템플릿도 함께 생성한다.
- 비교 기준은 `before_lock` vs `after_lock` 한 축이며, 집계 소스는 `closed v2 plans`의 `regime`, `transition_state`, `strategy_family`, `strategy_grade`, `reaction_classification`, `final_exit_*` 메타데이터다.
- 현재 근사 규칙:
  - `transition_confirmed`, `transition_watch`, `regime=transition` trade는 after에서 제거
  - `regime=shock` trade는 current shock regime factor만큼 계정 영향 기준으로 clamp
  - `shock + sweep_reversal`인데 `A + rejection_confirmed`가 아니면 after에서 제거
- 운영 점검 필드:
  - `strategy_v2_lock_validation.lock_metrics.before_lock`
  - `strategy_v2_lock_validation.lock_metrics.after_lock`
  - `strategy_v2_lock_validation.impact_counts`
  - `strategy_v2_lock_validation.deployment_recommendation`
- 해석 순서:
  - `p5 EV`
  - `max_drawdown`
  - `ulcer_index`
  - `blocked_transition_trades`
  - `shock_clamped_trades`

### 8.14 Thesis Dedupe 비교 규칙
- `POST /validation/report`는 현재 `strategy_v2_thesis_validation` 템플릿도 함께 생성한다.
- 비교 기준은 `before_dedupe` vs `after_dedupe` 한 축이며, 집계 소스는 글로벌 `closed v2 plans`의 `thesis_fingerprint`, `thesis_cluster_id`, `final_exit_*`, `valid_from`/ENTRY fill 메타데이터다.
- 현재 근사 규칙:
  - later overlapping same-thesis trade는 after에서 제거
  - distinct thesis cluster가 `thesis_max_active_clusters`를 넘기면 after에서 제거
  - open time은 ENTRY fill 우선, 없으면 `valid_from` 폴백
- 운영 점검 필드:
  - `strategy_v2_thesis_validation.thesis_metrics.before_dedupe`
  - `strategy_v2_thesis_validation.thesis_metrics.after_dedupe`
  - `strategy_v2_thesis_validation.impact_counts`
  - `strategy_v2_thesis_validation.deployment_recommendation`
- 해석 순서:
  - `max_drawdown`
  - `ulcer_index`
  - `p5 EV`
  - `blocked_duplicate_trades`
  - `blocked_active_cluster_cap_trades`

### 8.15 Stressed Cost 비교 규칙
- `POST /validation/report`는 현재 `strategy_v2_stress_validation` 템플릿도 함께 생성한다.
- 비교 기준은 `baseline_cost`, `stressed_cost`, `latency_plus_1_bar`, `partial_fills_only`, `shock_concentration` 다섯 축이다.
- 집계 소스는 `closed v2 plans`의 `final_exit_realized_r`, `entry_model`, `cost_est`, `regime`, `valid_from`과 `execution_fills`, `5m candles` 메타데이터다.
- 현재 근사 규칙:
  - `execution_fills`가 있으면 actual fee + entry slippage 사용
  - 없으면 `plan.cost_est`를 fee/slippage component로 분해해 사용
  - stress multiplier는 현재 고정값 `cost x1.5`, `slippage x2`
  - `latency +1 bar`: next 5m candle open 기준 directional adverse move만 penalty
  - `partial fills only`: `50% fill ratio` 고정 근사
  - `shock concentration`: `shock` 레짐 trade 손실 영향 확대, 이익 영향 축소
- 운영 점검 필드:
  - `strategy_v2_stress_validation.stress_metrics.baseline_cost`
  - `strategy_v2_stress_validation.stress_metrics.stressed_cost`
  - `strategy_v2_stress_validation.scenario_metrics`
  - `strategy_v2_stress_validation.scenario_comparison`
  - `strategy_v2_stress_validation.cost_summary`
  - `strategy_v2_stress_validation.scenario_summary`
  - `strategy_v2_stress_validation.deployment_recommendation`
- 해석 순서:
  - `max_drawdown`
  - `ulcer_index`
  - `p5 EV`
  - `worst_scenario`
  - `execution_data_trades`
  - `latency_reference_trades`

### 8.15-2 Stress Replay Assessment 규칙
- `GET /validation/stress-replay-assessment`로 단독 조회할 수 있고, `POST /validation/report`에도 `strategy_v2_stress_replay_assessment`가 포함된다.
- 현재 단계는 full replay 구현이 아니라, 기존 stress 근사를 대체할 준비도와 우선순위를 판정하는 단계다.
- 운영 점검 필드:
  - `strategy_v2_stress_replay_assessment.full_replay_ready`
  - `strategy_v2_stress_replay_assessment.replacement_recommended`
  - `strategy_v2_stress_replay_assessment.coverage.execution_fill_coverage`
  - `strategy_v2_stress_replay_assessment.coverage.latency_candle_coverage`
  - `strategy_v2_stress_replay_assessment.coverage.estimate_only_share`
  - `strategy_v2_stress_replay_assessment.scenario_evidence.worst_scenario`
  - `strategy_v2_stress_replay_assessment.deployment_recommendation`
  - `strategy_v2_stress_replay_assessment.blocked_by`
  - `strategy_v2_stress_replay_assessment.next_steps`
- 해석 규칙:
  - `full_replay_ready=true`: lineage와 표본이 full replay 대체 논의를 할 수 있는 수준
  - `replacement_recommended=true`: degraded/catastrophic scenario가 누적되어 full replay 우선순위를 올려야 함
  - `full_replay_ready=false`: execution fill 또는 latency candle lineage가 아직 부족하므로 현재 근사 유지가 맞음
- `replacement_recommended=false`: 현재 근사가 아직 충분하거나, 데이터 lineage 부족으로 우선순위 판단을 미루는 상태
- 이 항목은 현재 배포 승인 hard block이 아니라, stress validation 후속 구현 우선순위 판단용이다.

### 8.15-3 Stress Replay Lineage 규칙
- `GET /validation/stress-replay-lineage`로 단독 조회할 수 있고, `POST /validation/report`에도 `strategy_v2_stress_replay_lineage`가 포함된다.
- 현재 단계는 full replay runner가 아니라, `writer/runtime input lineage`가 얼마나 준비됐는지 평가하는 단계다.
- 운영 점검 필드:
  - `strategy_v2_stress_replay_lineage.available`
  - `strategy_v2_stress_replay_lineage.runtime_inputs_ready`
  - `strategy_v2_stress_replay_lineage.coverage.execution_fill_coverage`
  - `strategy_v2_stress_replay_lineage.coverage.latency_candle_coverage`
  - `strategy_v2_stress_replay_lineage.coverage.candle_path_coverage`
  - `strategy_v2_stress_replay_lineage.fill_path.entry_anchor_sources`
  - `strategy_v2_stress_replay_lineage.fill_path.exit_anchor_sources`
  - `strategy_v2_stress_replay_lineage.candle_path.required_nodes`
  - `strategy_v2_stress_replay_lineage.gap_counts`
  - `strategy_v2_stress_replay_lineage.blocked_by`
  - `strategy_v2_stress_replay_lineage.next_steps`
- 해석 규칙:
  - `available=true`: closed v2 trades 기준으로 lineage 평가 표본이 있다는 뜻
  - `runtime_inputs_ready=true`: execution fill / latency candle / candle path coverage가 최소 임계값을 넘었다는 뜻
  - `available=true`이지만 `runtime_inputs_ready=false`: lineage가 보이기는 하지만 writer/runtime 전환에는 아직 부족한 상태
  - `entry_anchor_source`, `exit_anchor_source` fallback은 lineage gap을 숨기지 않기 위한 계약이며, 자동 승격 신호가 아니다

### 8.15-4 Stress Replay Runner Contract 규칙
- `GET /validation/stress-replay-runner-contract`로 단독 조회할 수 있고, `POST /validation/report`에도 `strategy_v2_stress_replay_runner_contract`가 포함된다.
- 현재 단계는 replay queue/worker 실행이 아니라, prototype batch와 worker IO contract를 공통 payload로 고정하는 단계다.
- 운영 점검 필드:
  - `strategy_v2_stress_replay_runner_contract.available`
  - `strategy_v2_stress_replay_runner_contract.runtime_job_ready`
  - `strategy_v2_stress_replay_runner_contract.implementation_status`
  - `strategy_v2_stress_replay_runner_contract.readiness.ready_scenarios`
  - `strategy_v2_stress_replay_runner_contract.readiness.blocked_scenarios`
  - `strategy_v2_stress_replay_runner_contract.readiness.suggested_total_jobs`
  - `strategy_v2_stress_replay_runner_contract.runner_contract.batching`
  - `strategy_v2_stress_replay_runner_contract.scenario_contract`
  - `strategy_v2_stress_replay_runner_contract.worker_input_contract`
  - `strategy_v2_stress_replay_runner_contract.worker_output_contract`
  - `strategy_v2_stress_replay_runner_contract.blocked_by`
  - `strategy_v2_stress_replay_runner_contract.next_steps`
- 해석 규칙:
  - `runtime_job_ready=true`: lineage/assessment 기준으로 prototype replay batch를 만들 수 있다는 뜻
  - `runtime_job_ready=false`: contract는 정해졌지만, lineage gap 또는 replay upgrade 우선순위 부족으로 job 생성이 아직 이르다는 뜻
  - `runner_contract.batching.suggested_jobs`: 현재 closed trade 표본 기준의 prototype batch 제안값일 뿐, live worker throughput 계약은 아니다
  - `worker_output_contract`는 future writer/validation 연결을 위한 IO 약속이며, 현재 DB writeback이 이미 구현됐다는 뜻은 아니다

### 8.15-5 Stress Replay Lineage Writer 규칙
- `GET /validation/stress-replay-lineage-writer`로 단독 조회할 수 있고, `POST /validation/report`에도 `strategy_v2_stress_replay_lineage_writer`가 포함된다.
- 현재 단계는 replay worker 실행이 아니라, scenario별 replay input batch artifact(JSON)를 materialize하는 단계다.
- 운영 점검 필드:
  - `strategy_v2_stress_replay_lineage_writer.available`
  - `strategy_v2_stress_replay_lineage_writer.artifacts_written`
  - `strategy_v2_stress_replay_lineage_writer.runtime_job_ready`
  - `strategy_v2_stress_replay_lineage_writer.implementation_status`
  - `strategy_v2_stress_replay_lineage_writer.sample_counts`
  - `strategy_v2_stress_replay_lineage_writer.writer_contract`
  - `strategy_v2_stress_replay_lineage_writer.scenario_batches`
  - `strategy_v2_stress_replay_lineage_writer.blocked_by`
  - `strategy_v2_stress_replay_lineage_writer.next_steps`
- 해석 규칙:
  - `artifacts_written=true`: future replay worker가 읽을 input batch artifact가 생성됐다는 뜻
  - `artifacts_written=false`이면서 `runtime_job_ready=true`: contract는 준비됐지만, scenario filter나 표본 부족으로 이번 루프에서 실제 batch가 생성되지 않았다는 뜻
  - `scenario_batches.<scenario>.batches[*].artifact_path`: JSON input artifact 경로이며, replay output artifact 경로가 아니다

### 8.16 stress replay output artifact 규칙
- `GET /validation/stress-replay-output-artifacts`는 latest scenario별 replay worker output artifact를 읽는 단일 조회 endpoint다.
- 현재 단계는 replay worker 실행 자체가 아니라, worker가 쓴 결과 artifact가 있으면 `strategy_v2_stress_validation`과 같은 payload 언어로 바로 비교하는 단계다.
- 운영 점검 필드:
  - `strategy_v2_stress_validation.replay_output_artifacts.available`
  - `strategy_v2_stress_validation.replay_output_artifacts.comparison_ready`
  - `strategy_v2_stress_validation.replay_output_artifacts.summary_counts`
- `strategy_v2_stress_validation.replay_output_comparison`
- `strategy_v2_stress_validation.deployment_recommendation.replay_gate_applied`
- `strategy_v2_stress_validation.deployment_recommendation.worst_scenario_source`
- `strategy_v2_stress_validation.deployment_recommendation.divergence_gate_applied`
- `strategy_v2_stress_validation.deployment_recommendation.divergence_problem_scenarios`
- `strategy_v2_stress_validation.deployment_recommendation.worst_divergence_scenario`
- 해석 규칙:
  - `available=false`: replay worker output artifact가 아직 없다는 뜻이며, 현재 단계에서는 정상 상태일 수 있다.
  - `comparison_ready=true`: 최소 1개 scenario에서 replay output과 approximation delta를 계산할 수 있다는 뜻이다.
  - `comparison_to_approximation`: replay output minus approximation 기준 delta다.
  - replay output summary가 있는 scenario는 `deployment_recommendation.scenario_statuses[*].source=replay_output`로 승격된다.
  - replay output summary가 있는 scenario는 `divergence_status`도 같이 계산되며, divergence가 threshold를 넘으면 scenario 자체가 PASS여도 `WARN/FAIL`로 승격될 수 있다.
  - replay output이 없는 scenario는 기존 approximation 기준을 유지한다.

### 8.17 stress replay prototype worker 규칙
- `POST /validation/stress-replay-worker/prototype`는 lineage batch artifact를 읽어 scenario별 replay output artifact를 실제로 쓰는 단일 실행 endpoint다.
- 현재 worker mode는 `prototype_from_lineage_batches`이며, true market replay가 아니라 deterministic contract-validation worker다.
- 운영 점검 필드:
  - `strategy_v2_stress_replay_prototype_worker.available`
  - `strategy_v2_stress_replay_prototype_worker.executed`
  - `strategy_v2_stress_replay_prototype_worker.runtime_job_ready`
  - `strategy_v2_stress_replay_prototype_worker.sample_counts`
  - `strategy_v2_stress_replay_prototype_worker.scenario_runs`
- 해석 규칙:
  - `executed=true`: 최소 1개 scenario에서 input batch를 읽어 output artifact와 markdown을 썼다는 뜻
  - `executed=false`이면서 `runtime_job_ready=true`: batch artifact는 있지만 readable input row가 부족하거나 scenario filter 결과가 비어 있다는 뜻
  - `scenario_runs.<scenario>.output_artifact_path`: replay output artifact JSON 경로다

### 8.18 true market replay runner readiness 규칙
- `strategy_v2_stress_replay_assessment.true_runner_readiness`와 `strategy_v2_stress_replay_runner_contract.true_runner_readiness`가 true market replay runner replacement readiness의 단일 기준이다.
- 운영 점검 필드:
  - `true_runner_ready`
  - `stage`
  - `critical_scenarios`
  - `critical_scenarios_with_outputs`
  - `gates`
  - `blocked_by`
- 해석 규칙:
  - `runtime_job_ready=true`는 prototype runner contract 준비 상태일 뿐이고, true runner 교체 준비와 동일하지 않다.
  - `true_runner_ready=true`가 되려면 stronger lineage threshold와 critical scenario replay-output coverage를 동시에 만족해야 한다.
  - `replacement_recommended=false`면 lineage가 좋아도 true runner 교체는 아직 열지 않는다.

### 8.19 PBO / DSR runtime 규칙
- `POST /validation/report`는 현재 `strategy_v2_pbo_dsr_trial_writer`, `strategy_v2_pbo_dsr_artifact_store`, `strategy_v2_pbo_dsr_design`, `strategy_v2_pbo_dsr_metrics`를 함께 생성한다.
- 전용 조회 endpoint:
  - `GET /validation/pbo-dsr/trial-writer`
  - `GET /validation/pbo-dsr/threshold-runner`
  - `GET /validation/pbo-dsr/artifact-store`
  - `GET /validation/pbo-dsr`
- 현재 단계는 runtime proxy writer와 separated true threshold runner가 각자 trial/fold lineage를 seed하고, 그 위에서 combined metric을 계산하는 혼합 단계다.
- 운영 점검 필드:
  - `strategy_v2_pbo_dsr_trial_writer.available`
  - `strategy_v2_pbo_dsr_trial_writer.implementation_status`
  - `strategy_v2_pbo_dsr_trial_writer.sample_counts`
  - `strategy_v2_pbo_dsr_trial_writer.selected_trial_run_id`
  - `strategy_v2_pbo_dsr_trial_writer.threshold_parameter_families_present`
  - `strategy_v2_pbo_dsr_trial_writer.candidate_trials_by_family`
  - `strategy_v2_pbo_dsr_threshold_runner.available`
  - `strategy_v2_pbo_dsr_threshold_runner.selection_rule`
  - `strategy_v2_pbo_dsr_threshold_runner.lineage_namespace`
  - `strategy_v2_pbo_dsr_artifact_store.artifact_store_ready`
  - `strategy_v2_pbo_dsr_artifact_store.available`
  - `strategy_v2_pbo_dsr_artifact_store.metrics_available`
  - `strategy_v2_pbo_dsr_artifact_store.selection_rule_counts`
  - `strategy_v2_pbo_dsr_artifact_store.implementation_status`
  - `strategy_v2_pbo_dsr_design.design_ready`
  - `strategy_v2_pbo_dsr_design.available`
  - `strategy_v2_pbo_dsr_design.implementation_status`
- `strategy_v2_pbo_dsr_metrics.available`
- `strategy_v2_pbo_dsr_metrics.metrics_complete`
- `strategy_v2_pbo_dsr_metrics.pbo`
- `strategy_v2_pbo_dsr_metrics.dsr`
- `strategy_v2_pbo_dsr_metrics.lineage_audit`
- `strategy_v2_pbo_dsr_metrics.deployment_recommendation`
- 현재 고정 계약:
  - `PBO`: `CSCV`, pass/warn/fail=`0.20/0.35/0.35`
  - `DSR`: `deflated_sharpe_ratio`, min threshold=`0.0`
- 해석 규칙:
- `strategy_v2_pbo_dsr_trial_writer.available=true`는 runtime proxy writer가 현재 validation 루프에서 proxy trial/fold row를 자동 seed했다는 뜻이다.
- `strategy_v2_pbo_dsr_trial_writer.available=false`는 보통 closed v2 trade 표본 부족 또는 fold 수 부족을 뜻한다.
- `threshold_parameter_families_present`와 `candidate_trials_by_family`는 현재 proxy threshold coverage를 뜻하며, true parameter rerun coverage가 아니다.
- `strategy_v2_pbo_dsr_threshold_runner.available=true`는 true threshold family가 proxy lineage와 분리된 `selection_rule`로 seed됐다는 뜻이다.
- combined lineage 해석은 `strategy_v2_pbo_dsr_artifact_store.selection_rule_counts`와 `strategy_v2_pbo_dsr_metrics.selected_trial.writer_source`를 같이 본다.
- `strategy_v2_pbo_dsr_metrics.lineage_audit.audit_status=WARN`이면 dual-lineage 상태에서 runtime proxy selected-trial이 남아 있다는 뜻이며, 배포 승인 전에 source audit이 필요하다.
  - `strategy_v2_pbo_dsr_artifact_store.artifact_store_ready=true`는 schema/조회 계약 준비 완료를 뜻한다.
  - `strategy_v2_pbo_dsr_artifact_store.available=true`는 artifact row가 있다는 뜻이다.
  - `strategy_v2_pbo_dsr_artifact_store.metrics_available=true`는 latest snapshot 기준 PBO/DSR 두 축이 모두 계산됐다는 뜻이다.
  - `strategy_v2_pbo_dsr_metrics.metrics_complete=true`일 때만 `PBO < 0.35`, `DSR > 0` gate 해석을 붙인다.
  - `strategy_v2_pbo_dsr_metrics.deployment_recommendation.lineage_audit_applied=true`이면 base PBO/DSR gate 위에 lineage warning이 덮여 있다는 뜻이다.
  - `strategy_v2_pbo_dsr_design.available=true`는 design/runtime 동기화 상태를 뜻하며, design payload 자체가 승인 수치인 것은 아니다.

### 8.18 Operational Checklist 규칙
- `POST /operations/checklist`는 현재 운영 체크리스트의 단일 집계 API다.
- 현재 집계 항목:
  - `health_ready`
  - `validation_report`
  - `validation_alert_delivery`
  - `alert_channel_slo`
  - `alert_test_recent`
  - `retry_queue`
  - `event_outbox`
  - `risk_gate_open`
  - `session_guidance`
  - `portfolio_headroom`
  - `execution_quality_coverage`
  - `pbo_dsr_design`
- 상태 해석:
  - `PASS`: 현재 기준 충족
  - `WARN`: 비차단 경고, 운영자 검토 필요
  - `FAIL`: 차단 항목 실패
  - `MANUAL`: 자동 검증이 아니라 운영자가 직접 실행해야 하는 항목
- overall 규칙:
  - blocking item이 `FAIL` 또는 `MANUAL`이면 overall은 `FAIL`
  - blocking 실패가 없고 `WARN`만 있으면 overall은 `WARN`
- 최근 알림 테스트:
  - 자동으로 `POST /alerts/test`를 호출하지 않는다.
  - configured leaf channel에 최근 테스트 이력이 없으면 `MANUAL`
  - configured channel이 아예 없으면 `FAIL`
- `session_guidance` 해석 규칙:
  - `london` / `new_york` 활성 세션: `PASS`
  - `dead session`(`current_session.active=false`): `WARN`
  - `session lock active`: `WARN`
  - 이 항목은 운영 가이드용이며, hard block은 아니다.
- scanner / portfolio 후보 반영:
  - `GET /scanner/top`와 `GET /portfolio/budget` 후보 row는 `session_guidance`, `session_penalty`를 함께 노출한다.
  - `dead session`, `session lock active`는 ranking-only soft penalty만 반영한다.
  - 실제 차단은 계속 `risk_gate_open`과 `operating_lock`만 담당한다.
- 운영 점검 필드:
  - `checks[item_id=session_guidance].evidence.current_session`
  - `checks[item_id=session_guidance].evidence.dead_session`
  - `checks[item_id=session_guidance].evidence.preferred_windows_utc`
  - `checks[item_id=session_guidance].evidence.session_lock_active`
- 통합 점검 경로:
  - API: `POST /operations/checklist`
  - 스크립트: `scripts/generate_operational_checklist_report.py`

## 9. 운영 명령어
개발 환경:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

테스트:
```bash
pytest -q
```

실연결 통합 테스트(옵트인):
```bash
RUN_BINANCE_LIVE=1 pytest -q tests/test_binance_live_integration.py
```

파라미터 changelog 수동 생성:
```bash
python scripts/generate_parameter_changelog.py --trigger manual
```

Timescale 부하/장기보관 벤치마크:
```bash
python scripts/benchmark_timescale_retention.py \
  --database-url postgresql+psycopg://user:pass@localhost:5432/trading \
  --symbol-count 20 --candle-days 90 --outcome-days 220 --outcomes-per-symbol 1500 --query-repeats 20 --reset-target
```

주문 실행 품질 리포트:
```bash
python scripts/generate_execution_quality_report.py --symbol BTCUSDC --days 30
```

알림 채널 메트릭 리포트:
```bash
python scripts/generate_alert_metrics_report.py --days 30
```

중요도 캘리브레이션 리포트:
```bash
python scripts/generate_feature_calibration_report.py --symbol BTCUSDC --refresh
```

워커(once):
```bash
python scripts/run_worker.py --mode once --sync-universe --symbol-concurrency 4 --reprocess-events --validate
```

워커(loop):
```bash
python scripts/run_worker.py --mode loop --sync-universe --symbol-concurrency 4 --interval-seconds 300
```

알림 채널 테스트:
```bash
curl -X POST "http://127.0.0.1:8000/alerts/test" \
  -H "Content-Type: application/json" \
  -d '{"channel":"discord","symbol":"BTCUSDC","message":"ops channel check"}'
```

`channel=system`은 설정된 채널(telegram/discord/push)로 fanout 전송한다.

실체결 이벤트 주입(반자동/시뮬레이터 연동):
```bash
curl -X POST "http://127.0.0.1:8000/internal/execution/fills" \
  -H "Content-Type: application/json" \
  -d '{"fill_id":"sim_btc_001","plan_id":"BTCUSDC_xxx","symbol":"BTCUSDC","stage":"ENTRY","fill_ts":"2026-03-04T12:30:00Z","price":62000.5,"qty":0.01,"fee":0.02}'
```

알림 채널 장애 격리(기본값):
- `alert_retry_attempts=3`
- `alert_retry_backoff_seconds=0.4` (지수 백오프)
- `alert_circuit_breaker_failures=3`
- `alert_circuit_breaker_cooldown_seconds=90`
- 서킷브레이커가 열린 채널은 `reason=circuit_open`으로 즉시 스킵되며, 쿨다운 후 자동 복귀한다.

WS 스트림 ingest(단일 심볼):
```bash
python scripts/run_worker.py --ws-stream --symbol BTCUSDC --ws-intervals 5m,15m
```

WS 스트림 ingest(유니버스):
```bash
python scripts/run_worker.py --ws-stream --sync-universe --limit-symbols 30 --ws-intervals 5m,15m
```

Binance REST backfill/sync는 기존 최신 candle보다 오래된 overlap history를 자동 skip한다. 즉, 이미 demo/bootstrap 또는 이전 sync가 있으면 겹치는 과거 구간은 건너뛰고 최신 tail만 이어받는다.

## 10. 튜닝 원칙
1. 한 번에 하나의 파라미터 그룹만 조정한다.
2. 조정 후 WF/MC 리포트를 반드시 재생성한다.
3. `/validation/report` 실행으로 `reports/params/PARAM_CHANGELOG.md` 변경 이력을 남긴다.
4. 표본 수가 적은 구간에서 가중치 급변을 금지한다.
5. 성능 개선 판단은 단일 수익률이 아니라 EV/하방(p5)/일관성으로 평가한다.
6. 피처 중요도에서 음수 기여가 반복되는 항목은 우선적으로 감점/가중치 축소한다.
7. 캘리브레이션은 결과 기반 후행 보정이므로, `matched_samples`가 얕은 구간에서는 수동 가중치 변경보다 표본 축적을 우선한다.

## 11. 헬스체크 기준
- `/health/ready`는 `db`, `binance_rest`, `event_backend`를 동시에 점검한다.
- 하나라도 실패하면 상태는 `degraded`이며 신규 라이브 진입을 보류한다.

## 12. vNext 기획 기준
- 기준 문서: `docs/UPGRADE_ROADMAP_VNEXT.md`
- 구현 착수 규칙:
  1. Epic별 설계 승인 후 착수
  2. Epic 완료는 `코드 + 테스트 + 리포트 + 문서` 동시 충족
  3. 다음 Epic은 이전 Epic 운영 검증 완료 후 진행

## 13. Strategy v2 기준선
- 최신 전략 설계 청사진은 `docs/STRATEGY_V2_BLUEPRINT.md`를 기준으로 한다.
- 실전 운영 플레이북은 `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`를 기준으로 한다.
- signal 분류 세부 계약은 `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`를 기준으로 한다.
- transition 정량 규칙은 `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`를 기준으로 한다.
- thesis fingerprint 계약은 `docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`를 기준으로 한다.
- exit reason/event 계약은 `docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`를 기준으로 한다.
- validation/PBO/DSR 프로토콜은 `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`를 기준으로 한다.
- 구현 항목 추적은 `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`를 기준으로 한다.
- 핵심 해석 순서:
  1. `Market state`
  2. `Location`
  3. `Liquidity narrative`
  4. `Acceptance / Rejection`
  5. `Execution`
- 기본 운영 모드:
  - `A-only`
  - `transition no-trade`
  - `thesis dedupe`
  - `daily -2R lock`
- 본 문서에는 운영 요약만 남기고, 전략군별 A/B/C 판정표와 lock rule 상세는 청사진 문서를 단일 기준으로 본다.
- 전략 v2 기획은 문서 기준 완료 상태이며, 청사진 문구는 현재 런타임 계약 기준으로 동기화됐다.
- 현재 `strategy_v2_stress_replay_assessment.deployment_recommendation.true_runner_promotion_*`가 true runner 승격 action의 단일 기준이며, `true_runner_ready=true`여도 threshold lineage audit가 WARN이면 `stay_on_prototype`으로 남는다.
- 현재 `strategy_v2_pbo_dsr_metrics.selection_universe_summary`가 `combined artifact universe`와 `full parameter-sweep universe`를 분리 기록하고, DSR bias adjustment도 `full_parameter_sweep_universe`가 있으면 그 기준을 우선 사용한다.
- `strategy_v2_pbo_dsr_metrics.dsr.legacy_combined_benchmark_sharpe`와 `benchmark_sharpe_delta_vs_legacy_combined`는 운영 회귀 점검용 비교값이며, 실제 승인 판단은 `selection_universe_basis`가 가리키는 active benchmark를 따른다.
- 현재 `strategy_v2_stress_replay_output_artifacts.lineage_summary`가 replay output provenance를 묶어 보여주고, `strategy_v2_stress_replay_assessment.deployment_recommendation.replay_output_lineage_alignment_*`가 selected-trial source audit와 직접 결합된 운영 판단을 제공한다.
- 현재 `validation_report.deployment_approval_summary`와 `strategy_v2_stress_replay_assessment.deployment_recommendation.approval_cross_display`가 threshold lineage winner와 replay-derived worst scenario를 같은 승인 템플릿에서 직접 교차 표시한다.
- 현재 `approval_cross_display.approval_warning_locked/code/message`가 runtime proxy winner가 replay-backed downside와 함께 남아 있으면 승인 템플릿에 직접 경고 문구를 고정한다.
- 현재 `deployment_approval_summary.topline_status/code/message`가 replay output lineage alignment warning을 approval template 최상단 승인 문구에 직접 연결한다.
- 현재 `deployment_approval_summary.topline_summary_line`가 threshold lineage winner / replay-derived worst scenario / true-runner promotion action을 최상단 승인 문구에서 한 줄로 요약한다.
- 현재 `deployment_approval_summary.playbook_go_no_go/code/action/message`가 approval template warning code를 운영 playbook의 `GO / NO_GO / MANUAL_REVIEW` 문구로 직접 매핑한다.
- 현재 `deployment_approval_summary.topline_message`, `POST /operations/checklist`의 `deployment_*`, `GET /scanner/top` row의 `deployment_*`가 같은 `GO / NO_GO / MANUAL_REVIEW` 언어로 정렬된다.
- 현재 `validation_alert.approval_topline_summary_line`가 `deployment_approval_summary.topline_summary_line`를 alert payload/재시도 payload/채널 메시지까지 그대로 전달한다.
- 현재 `validation_alert.approval_playbook_go_no_go/code/action/message`가 `deployment_approval_summary.playbook_go_no_go/code/action/message`를 alert payload/재시도 payload/outbox payload까지 그대로 전달한다.
- 현재 `GET /portfolio/budget` top-level `deployment_go_no_go/code/message`와 portfolio markdown summary도 같은 `GO / NO_GO / MANUAL_REVIEW` 언어를 사용한다.
- 현재 `validation_alert.deployment_go_no_go/code/message`가 alert payload에 직접 기록되고, `GET /alerts/metrics`의 `latest_validation_alert`, `POST /operations/checklist`의 `validation_alert_delivery`/`alert_channel_slo` evidence도 같은 필드를 직접 노출한다.
- 현재 `GET /alerts/metrics`의 `latest_validation_alert.approval_playbook_go_no_go/code/action/message`와 `POST /operations/checklist`의 `alert_channel_slo.evidence.latest_validation_alert`도 같은 playbook mapping을 직접 노출한다.
- 현재 `POST /operations/checklist`의 `portfolio_headroom.evidence.deployment_go_no_go/code/message`도 `/portfolio/budget` top-level 배포 언어를 직접 노출한다.
- 현재 validation alert 채널 메시지는 `approval_strip: approve / align / act`를 먼저 보여주고, 그다음 `approval=` one-line summary와 `contract_trace: deployment=... | playbook_action=...` raw debug를 붙인다.
- 현재 `POST /operations/checklist`의 `validation_alert_delivery.evidence.approval_playbook_go_no_go/code/action/message`도 `validation_alert.approval_playbook_*`를 top-level로 직접 노출한다.
- 현재 `GET /portfolio/budget` top-level `playbook_go_no_go/code/action/message`와 portfolio markdown summary도 runtime deployment code 기반 운영 액션 문구를 직접 노출한다.
- 현재 `GET /indicators/pine-script`와 `scripts/tradingview/trading_engine_v1_mirror.pine`가 TradingView native mirror를 제공하며, 이는 최근 zone 중심의 chart-side approximation일 뿐 실행 source-of-truth를 대체하지 않는다.
- 현재 validation alert 채널 메시지도 `playbook_action=<approval_playbook_action>`를 raw debug에 포함해 운영 액션 문구를 메시지 단독으로 확인할 수 있다.
- 현재 `POST /alerts/test` 응답도 `deployment_*`, `approval_playbook_*` top-level raw contract와 함께 `approval_strip_summary`를 반환해 manual alert drill 경로가 operator surface와 같은 판단 vocabulary를 공유한다.
- 현재 `POST /alerts/subscribe` 응답도 `deployment_*`, `approval_playbook_*`를 top-level로 직접 반환해 manual subscribe 경로가 same contract를 공유한다.
- 현재 `POST /validation/report` top-level도 `deployment_*`, `approval_topline_*`, `playbook_*`를 직접 반환하며, `POST /operations/checklist`는 validation deployment/playbook 해석 시 이 top-level contract를 우선 소비한다.
- 현재 `app/services/deployment_contracts.py`가 alert/report deployment-playbook contract의 공통 helper이며, 운영 경로는 이 helper 기준의 같은 필드명/같은 fallback 규칙을 따라야 한다.
- 현재 `POST /operations/checklist`의 `portfolio_headroom.evidence.playbook_go_no_go/code/action/message`도 `/portfolio/budget` top-level playbook 문구를 직접 노출한다.
- 현재 `POST /operations/checklist` top-level `playbook_go_no_go/code/action/message`도 validation/report/portfolio와 같은 수준의 운영 액션 문구를 직접 노출한다.
- 현재 rollout-blocking backlog와 active post-rollout refactor backlog는 모두 비어 있으며, 첫 라이브 운영 사이클 이후 contract pruning 필요성만 optional hold로 재평가한다.
- review-type deployment/playbook backlog는 정리 완료 상태이고, 현재 남은 비검토 backlog는 rollout blocker가 아닌 post-rollout refactor 성격으로 관리한다.
- 현재 `POST /internal/binance/order`, `GET /internal/binance/order`, `DELETE /internal/binance/order`가 signed REST 기반 Binance 주문 어댑터 1차를 제공한다.
- 현재 `POST /internal/binance/user-stream/listen-key`, `PUT /internal/binance/user-stream/listen-key`, `DELETE /internal/binance/user-stream/listen-key`, `POST /internal/binance/user-stream/process`, `POST /internal/binance/user-stream/event`, `POST /internal/binance/positions/sync`, `GET /internal/binance/positions`가 완전자동매매 2차의 user-stream/position sync 계약을 제공한다.
- 현재 Binance futures user-stream의 기본 이벤트는 `ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`이며, 엔진은 이를 기존 `execution_fills`/position state machine source-of-truth에 연결한다.
- 현재 Binance 주문 어댑터는 기본이 `test order`이며, 실제 live submit/cancel은 `BINANCE_TRADE_LIVE_ENABLED=true`와 요청의 `live=true`를 동시에 만족해야만 열린다.
- 현재 live websocket user-stream processing은 optional dependency `websockets`가 필요하다. 미설치 상태에서는 listen-key 관리와 REST position sync는 가능하지만 `POST /internal/binance/user-stream/process`는 runtime dependency missing으로 종료될 수 있다.
- 현재 구현은 user-stream/position sync 2차까지 완료됐고, background keepalive daemon / 장기 상시 러너는 optional hold 후속으로 본다.
- 현재 서버 스캘핑 기본값은 `24h` old-zone hard filter + `90m` baseline validity + preferred live session bias다.
- `POST /validation/report`의 `strategy_v2_validation`는 이제 `family_metrics/family_summary`, `session_metrics/session_summary`를 포함하며, family/session별 EV와 승률을 분리해서 본다.
- `GET /validation/scalp-experiment`와 `POST /validation/report`의 `strategy_v2_scalp_experiment`는 `15m zone / 5m execution` baseline과 `5m zone / 1m execution` experiment를 compare-only로 비교한다.
- `5m zone / 1m execution` branch는 아직 live source-of-truth가 아니며, baseline branch가 계속 실행 기준이다.
- dead session / active session lock은 여전히 hard block이 아니라 plan score / probability penalty와 portfolio/session guidance penalty로만 먼저 반영한다.
- 현재 엔진은 `sweep_reversal` family를 1차 구현했고, plan/scanner 응답의 `strategy_family`, `strategy_grade`로 라우팅 결과를 직접 확인할 수 있다.
- 현재 엔진은 `trend_continuation` family도 1차 구현했고, `protected level hold`가 깨지면 generic plan으로 우회하지 않고 즉시 차단한다.
- 현재 엔진의 `range_rotation`은 `research_only`로만 분리되어 있으며, live plan으로는 승격하지 않는다.
- 현재 엔진은 family 밖에 남은 generic 후보 중 `OB-only`, `FVG-only`, `trendline-led`를 runtime에서 차단한다.
- 현재 엔진은 `thesis_fingerprint`를 plan/scanner/portfolio overlay가 공유하며, 같은 thesis는 `full-size 1개`만 허용하고 active thesis cluster `2개`를 넘기지 않는다.
- 현재 엔진은 `strategy_scorecard`를 family score 단일 계약으로 사용하며, `buckets.location/liquidity/reaction/invalidation/session`과 `raw_components`를 함께 남긴다.
- `trendline_bonus`는 현재 `0.0` 고정 placeholder이며, 별도 trendline detector 도입 전까지 primary score에 영향 주지 않는다.
- `transition_watch`에서 `sweep_reversal`이더라도 `A`가 아니면 신규 플랜을 만들지 않는다.
- 현재 엔진은 `strategy_v2_validation` 템플릿으로 `A_ONLY` vs `A_PLUS_B` 비교를 자동 생성하며, validation report 본문에도 같은 요약을 함께 남긴다.
- 현재 엔진은 `strategy_v2_lock_validation` 템플릿으로 `transition/shock lock` 적용 전후 비교를 자동 생성하며, validation report 본문에도 같은 요약을 함께 남긴다.
- 현재 엔진은 `strategy_v2_stress_validation` 템플릿으로 `cost x1.5 / slippage x2` 비교를 자동 생성하며, validation report 본문에도 같은 요약을 함께 남긴다.
- 현재 엔진은 `strategy_v2_thesis_validation` 템플릿으로 `thesis dedupe` 적용 전후 비교를 자동 생성하며, validation report 본문에도 같은 요약을 함께 남긴다.
