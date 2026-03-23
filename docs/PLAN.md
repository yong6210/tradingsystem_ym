# Trading Engine v1 실행 계획서 (Living)

최종 갱신: 2026-03-09

## 1. 목표
- 15m Zone Map + 5m Context 기반 사전 플랜(Entry/SL/TP/EV) 생성
- Edge > Cost 필터를 통과한 기회만 랭킹/알림/반자동 실행
- zone_outcomes 학습 + Walk-forward/Monte Carlo 검증 리포트 자동화
- Binance USDC Perp 기준 운영 가능한 검증 우선(verification-first) 체계 유지

## 2. 현재 아키텍처 결정
- 거래소/상품: Binance USDC Perp (USD-M API)
- 실행 모드: 알림 + 반자동
- 유니버스: 거래대금 상위 30개 (`usdc_perp_top30`)
- 코어 언어: Python
- 저장소: 로컬 SQLite 부트스트랩, 운영 목표는 Postgres + Timescale + Redis
- 이벤트 파이프라인: Outbox 기반(중복/지연/재처리 정책 포함)
- 시간 규칙: 내부 저장 UTC 고정, 표시 계층에서만 로컬 변환

## Auto Trading Phase 1 착수 원칙
1. Auto Trading Phase 1은 전면 디렉토리 재구성이 아니라 additive implementation으로 진행한다.
2. source-of-truth는 기존 runtime contract다. 새 execution layer는 새 판단 엔진이 아니라 기존 deployment/playbook/operating_lock/portfolio/risk/thesis 결과를 번역한다.
3. Phase 1 범위는 `ExecutablePlan -> Approval -> OrderIntent`까지로 제한한다. exchange submit, reconciliation hard gate, restart recovery, live order sync는 Phase 2 이후로 미룬다.
4. `allowed_execution_mode`는 `AUTO_TRADING_EXECUTION_MODE`, strategy-mode cap, deployment-state cap의 교집합으로 결정하고, approval response와 intent ledger에 함께 남긴다.
5. Phase 1 stale 판정은 시간 및 plan validity 상태 기준으로만 제한한다. context drift/replay-level stale 판정은 포함하지 않는다.
6. Phase 1 duplicate thesis 판정은 execution-layer 기준의 열린 intent 충돌만 본다. closed intent는 duplicate source에서 제외한다.
7. order_intents는 최소 decision ledger이지만 `allowed_execution_mode`, deployment/playbook top-level contract snapshot을 함께 저장한다.
8. Phase 1 acceptance criteria는 기존 plans/scanner/validation 회귀 없음, approval 재현 가능성, intent decision 일관성, duplicate/stale/lock/manual/shadow 경로 테스트 커버, exchange submit 미발생으로 고정한다.
9. Phase 1B/1C route contract는 현재 활성 상태다. `POST /execution/plans/preview`는 실제 `ExecutablePlan`, `POST /execution/approve-plan`는 실제 `ExecutionApproval`을 반환하고, 이후 phase는 이를 additive로만 확장한다.
10. Phase 1D 현재 구현은 duplicate thesis를 execution-layer open intent/submission 기준으로 먼저 판정하고, runtime active-plan dedupe는 fallback으로만 사용한다.
11. `POST /execution/order-intents` 응답은 nested snapshot 외에도 `allowed_execution_mode`, `deployment_*`, `playbook_*`, `source_of_truth_hint=execution_approval_snapshot`를 top-level로 직접 노출한다.

## 3. 구현 상태 (코드 기준)
### Phase A. 데이터 인입/정합성
- 상태: 완료(강화)
- 구현: Binance REST 백필, OHLCV 품질 게이트, 심볼/타임프레임 적재
- 추가: Binance WS 스트림 ingest 루프(5m/15m), 재연결 백오프, worker 실행 경로 연결

### Phase B. Zone Map 엔진
- 상태: 완료(기본)
- 구현: LP/OB/FVG/FLIP 후보 생성, 병합/만료/정리

### Phase C. Context/Dynamics
- 상태: 완료(강화)
- 구현: Feature + Kalman F/V/A + Jump/Friction/Regime
- 추가: `regime_label(trend/range/shock)` 분류

### Phase D. Plan Generator + Entry Router
- 상태: 완료(강화)
- 구현: EV/Cost, RR 필터, 분할익절, LIMIT/CONFIRM/SWEEP_CONFIRM
- 추가:
  - anti-overtrading 하드 게이트
  - 메타 필터(2차 실행 게이트, meta score/threshold)
  - 레짐별 프로파일(최소 confluence/RR/EV)
  - 동적 가중치(셋업 성과 반영)
  - 자동 비활성화(음수 EV 셋업)
  - 중복 신호 억제(dedupe)

### Phase E. 실행/리스크/이벤트
- 상태: 완료(강화)
- 구현: RiskGate, EventOutbox, dedupe/late/retry/reprocess, 상태 조회 API
- 추가:
  - Gate CLOSED 시 신규 플랜 생성 억제
  - Validation Report `WARN/FAIL` 자동 알림(`validation.warn`/`validation.fail`)
  - 운영 알림 채널 실배선(`telegram`/`discord`/`push`) + `system` fanout + 전송 결과 추적(`validation_alert.delivery`)
  - 운영 채널 점검용 `POST /alerts/test` API

### Phase F. 학습/검증
- 상태: 완료(강화)
- 구현: zone_outcomes 요약, WF/MC, Markdown 리포트 생성
- 추가:
  - 베이지안 스무딩 + `ev_r` 기반 품질 업데이트
  - 피처 중요도(Ablation) 자동 분석 + `/validation/feature-importance` API
  - 파라미터 변경 이력 자동 CHANGELOG(`reports/params/PARAM_CHANGELOG.md`)
  - 수동 생성 스크립트(`scripts/generate_parameter_changelog.py`)

### Phase G. 운영 자동화
- 상태: 완료(강화)
- 구현: symbol sync, universe sync, worker once/loop, 심볼 병렬 처리 + 동시성 제한

### Phase H. 운영 헬스체크
- 상태: 완료(강화)
- 구현: `/health/ready`에 외부 의존성 점검(db/binance_rest/event_backend) 반영

### Phase I. Timescale 실환경 검증
- 상태: 완료(신규)
- 구현:
  - `scripts/verify_timescale_runtime.py` 추가(스키마 생성, 마이그레이션, write/read, 압축 정책/잡 실행 검증)
  - 실환경 제약 반영: 하이퍼테이블 전환 전 PK를 시간 컬럼 포함 형태로 재정의
  - PASS 리포트 산출: `reports/timescale/validation_docker_e2e.md`

### Phase J. Timescale 부하/장기보관 벤치마크
- 상태: 완료(신규)
- 구현:
  - `scripts/benchmark_timescale_retention.py` 추가(임계치 기반 PASS/WARN/FAIL)
  - 대량 입력 실측(20 symbols, 90 days, 5m/15m + outcomes 30k)
  - 정책 시간 측정: compression policy + retention policy `run_job`
  - 성능 지표 산출: recent/aggregate/scanner/outcome 쿼리 p50/p95/max
  - PASS 리포트 산출: `reports/timescale/benchmark_docker_e2e.md`

### Phase K. 포트폴리오 리스크 오버레이
- 상태: 완료(신규)
- 구현:
  - `PortfolioRiskOverlayService` 추가
  - scanner 랭킹에 상관도 기반 패널티/차단 로직 적용
  - 동시 노출 제한(총 노출, 방향별 노출, 고상관 cluster 노출) 적용
  - 기존 노출 상태(ARMED/TRIGGERED/ENTERED/PARTIAL_EXIT, 옵션으로 PLANNED 포함) 연동
  - 회귀 테스트 추가(`tests/test_portfolio_overlay.py`)

### Phase L. 주문 실행 품질 리포트 자동화
- 상태: 완료(신규)
- 구현:
  - `ExecutionQualityService` 추가(슬리피지/fill-rate/미체결 원인 분해)
  - API 추가: `GET /execution/quality?symbol=...&days=...&write_report=...`
  - 스크립트 추가: `scripts/generate_execution_quality_report.py`
  - 리포트 산출: `reports/execution/quality_<SYMBOL>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_execution_quality.py`)

### Phase M. 알림 채널 장애 격리
- 상태: 완료(신규)
- 구현:
  - `NotificationDispatcher`에 채널별 재시도/백오프 추가
  - 채널별 서킷브레이커(`failures`, `cooldown`) 추가
  - `system` fanout 경로도 개별 채널 상태(정상/서킷오픈)를 반영
  - 설정 추가: `alert_retry_*`, `alert_circuit_breaker_*`
  - 회귀 테스트 추가(`tests/test_notification_dispatcher.py`)

### Phase N. 포지션 상태머신 실집행 연동
- 상태: 완료(신규)
- 구현:
  - 체결 원장 모델 추가: `execution_fills` (`fill_id` 멱등 키, 전이 전/후 상태, stage, qty/price/fee)
  - 상태 전이 서비스 추가: `PositionStateMachineService`
  - 전이 규칙: `TRIGGERED -> ENTERED -> PARTIAL_EXIT -> CLOSED` 단방향 적용(역전이 차단)
  - API 추가: `POST /internal/execution/fills` (plan 미존재 404, symbol mismatch 400)
  - 엔진 연동: `StrategyEngine.ingest_execution_fill(...)`
  - 이벤트 연동: 전이 시 `entry.triggered`, `trade.closed` outbox 발행
  - 회귀 테스트 추가(`tests/test_position_state_machine.py`, `tests/test_execution_fill_api.py`)

### Phase O. 주문 실행 품질 리포트 v2
- 상태: 완료(신규)
- 구현:
  - `ExecutionQualityService`가 `execution_fills`를 1차 소스로 사용하고 `zone_outcomes`는 fallback으로만 사용
  - 지표 확장: `fill_sources`, `stage_counts`, `entry_latency_seconds`, `fees`
  - entry model별 `partial_exit_rate`, `closed_rate`, `execution_source_rate` 추가
  - 미체결 원인 확장: `triggered_no_entry`
  - 회귀 테스트 보강(`tests/test_execution_quality.py`, `tests/test_api_smoke.py`)

### Phase O2. 주문 실행 품질 리포트 v3
- 상태: 완료(신규)
- 구현:
  - `strategy_version` 기준 비교 집계(`by_strategy_version`, `version_comparison`) 추가
  - 미체결 원인 세분화 추가: `expired_without_touch`, `expired_after_touch_limit`, `expired_after_touch_confirmation`, `timed_out_after_trigger`, `order_rejected`, `cancelled_before_entry`
  - `fill_events_total`, `comparison_axis`, `versions_compared`를 API/리포트에 반영
  - Markdown 리포트에 버전별 실행 품질 비교 섹션 추가
  - 회귀 테스트 보강(`tests/test_execution_quality.py`, `tests/test_api_smoke.py`)

### Phase P. 알림 채널 메트릭/관측성 확장
- 상태: 완료(신규)
- 구현:
  - `NotificationDispatcher`에 `latency_ms` 측정 및 서킷 상태 스냅샷 추가
  - `AlertMetricsService` 추가(`overall`, `channel_metrics`, `circuit_state`, 채널별 SLO 판정)
  - API 추가: `GET /alerts/metrics?days=...&write_report=...`
  - 스크립트 추가: `scripts/generate_alert_metrics_report.py`
  - 리포트 산출: `reports/alerts/alert_metrics_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_alert_metrics.py`, `tests/test_notification_dispatcher.py`, `tests/test_api_smoke.py`)

### Phase T. 알림 채널 복원력 v2 후속
- 상태: 완료(신규)
- 구현:
  - `AlertRetryQueueService` 추가(재시도 큐, dead-letter, manual requeue)
  - 재시도 대상은 leaf 채널 실패와 `circuit_open` 스킵만 큐잉하고, 비재시도성 오류는 제외
  - API 추가:
    - `GET /internal/alerts/retry-queue/status`
    - `POST /internal/alerts/retry-queue/process`
    - `POST /internal/alerts/retry-queue/dead-letter/requeue`
  - alert metrics 확장: `retry_queue`, `overall.error_budget`, `channel_metrics.*.error_budget`
  - 배치 스크립트 추가: `scripts/process_alert_retry_queue.py`
  - 회귀 테스트 추가(`tests/test_alert_retry_queue.py`, `tests/test_alert_metrics.py`, `tests/test_api_smoke.py`)

### Phase Q. 중요도 온라인 캘리브레이션
- 상태: 완료(신규)
- 구현:
  - `FeatureCalibrationService` 추가(최근 `plan.validity.confluence_components` + `zone_outcomes` 매칭, EWMA 스냅샷, bounded weight update)
  - zone type별 multiplier(`OB/FVG/LP/FLIP`) 보정 추가
  - `baseline.generated_plans` / `matched_samples` 최소 기준 미달 시 runtime 적용 차단
  - latest snapshot 기반 runtime 가중치 적용(`PlanGenerator.importance_calibration`)
  - API 추가: `GET /validation/feature-calibration?symbol=...&write_report=...`
  - 검증 리포트 연동: `POST /validation/report`에 `feature_calibration` 포함
  - 스크립트 추가: `scripts/generate_feature_calibration_report.py`
  - 리포트 산출: `reports/calibration/feature_calibration_<SYMBOL>_<REGIME>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_feature_calibration.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase R. 포트폴리오 리스크 버짓 v2
- 상태: 완료(신규)
- 구현:
  - `PortfolioRiskOverlayService` 확장(상관도 + 5m realized volatility + regime-aware cap)
  - `risk_budget_score` 계산 및 최소 점수 미달 후보 차단
  - 레짐별 동적 cap(`total/directional/cluster`) 적용
  - 스캐너 응답 확장: `regime`, `risk_budget_score`, `portfolio_volatility`, 동적 cap 노출
  - 파라미터 추적 추가: `portfolio_overlay_* risk budget` 계열
  - 회귀 테스트 추가(`tests/test_portfolio_overlay.py`, `tests/test_api_smoke.py`)

### Phase S. 포지션/포트폴리오 통합 버짓 리포트
- 상태: 완료(신규)
- 구현:
  - `PortfolioBudgetReportService` 추가(현재 노출 + 후보 평가 + headroom snapshot)
  - API 추가: `GET /portfolio/budget?universe=...&limit=...&write_report=...`
  - 스크립트 추가: `scripts/generate_portfolio_budget_report.py`
  - 리포트 산출: `reports/portfolio/budget_<UNIVERSE>_<UTC>.md`
  - 응답 필드: `current_exposure`, `headroom_by_regime`, `current_positions`, `blocked_reason_counts`
  - 회귀 테스트 추가(`tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)

### Phase T. 전략 v2 상태 엔진 1차 코드화
- 상태: 완료(신규)
- 구현:
  - `ContextSnapshot`에 `transition_score`, `transition_state`, `transition_features`, `transition_unlock_candidate`, `transition_lock_reason` 추가
  - `ContextEngine`에 transition 진단 로직 추가(opposing impulse conflict, bidirectional sweep churn, reaction failure cluster, wick dominance, state disagreement, invalidation churn)
  - `PlanGenerator`에 `transition_confirmed=no-trade`, `transition_watch=confirm_only` 연결
  - refresh 응답에 `transition_score/state/lock_reason` 노출
  - 회귀 테스트 추가(`tests/test_context_engine_transition.py`, `tests/test_plan_quality_gates.py`)

### Phase U. acceptance/rejection classifier 1차 코드화
- 상태: 완료(신규)
- 구현:
  - `AcceptanceRejectionClassifierService` 추가(입력 계약 + 점수화 + classification)
  - 입력 계약 고정: `ATR`, `reclaim_bars`, `outside_close_count`, `dwell_time_bars`, `inefficiency_created`, `retest_hold`
  - `PlanGenerator`에 classifier 연동
    - `mixed` -> no-trade
    - `acceptance_*` -> reversal 후보 차단
    - `rejection_tentative` -> `confirm only`
  - `validity`에 `reaction_classification`, `reaction_scores`, `reaction_input` 저장
  - 회귀 테스트 추가(`tests/test_acceptance_rejection_classifier.py`, `tests/test_plan_quality_gates.py`)

### Phase V. Sweep Reversal family routing 1차 코드화
- 상태: 완료(신규)
- 구현:
  - `StrategyFamilyRouter` 추가(`sweep_reversal` family, grade A/B/C, family score components)
  - `PlanGenerator`에 family routing 연동
    - rejection 기반 candidate만 `Sweep Reversal`로 승격
    - family-specific routing (`A clean -> LIMIT`, `A -> SWEEP_CONFIRM`, `B/C -> CONFIRM`)
    - `trend non-extreme`, `shock non-A`, `transition_watch non-A` 차단
  - `validity`와 API/scanner 응답에 `strategy_family`, `strategy_grade`, family score/time-stop metadata 저장
  - 회귀 테스트 추가(`tests/test_strategy_family_router.py`, `tests/test_plan_quality_gates.py`, `tests/test_api_smoke.py`)

### Phase W. Trend Continuation Pullback routing 1차 코드화
- 상태: 완료(신규)
- 구현:
  - `StrategyFamilyRouter`에 `trend_continuation` family 추가
  - 판정 기준:
    - `trend` regime only
    - `OB/FVG` execution zone only
    - `healthy pullback`
    - `protected low/high hold`
    - `impulse quality`
  - family-specific routing (`A -> LIMIT`, `B/C -> CONFIRM`)
  - fixed split `30/30/40`, time stop `5~8 bars`
  - low-quality trend candidate는 family-level block으로 generic fallback 우회 차단
  - 회귀 테스트 추가(`tests/test_strategy_family_router.py`, `tests/test_plan_quality_gates.py`)

### Phase X. Range Rotation research-only 분리 1차 코드화
- 상태: 완료(신규)
- 구현:
  - `StrategyFamilyRouter`에 `range_rotation` family 인식 추가
  - 조건:
    - `range` regime only
    - reversal signal 기반
    - edge proximity / range definition / liquidity grab / reversal quality 점수화
  - live routing은 열지 않고 `range_rotation_research_only`로 명시적 차단
  - `range center` 후보는 `range_rotation_range_center_block`으로 별도 차단
  - 회귀 테스트 추가(`tests/test_strategy_family_router.py`, `tests/test_plan_quality_gates.py`)

### Phase Y. pattern-only generic block 1차 코드화
- 상태: 완료(신규)
- 구현:
  - family routing 밖에 남은 generic 후보 중 `OB-only`, `FVG-only`, `trendline-led`를 runtime 차단
  - 조건:
    - family 없음
    - nearby liquidity 없음
    - reaction 없음
    - runtime 5m candle 기준일 때만 적용
  - `trendline-led`는 현재 `trend_proxy` 우세 generic setup을 proxy로 차단
  - 회귀 테스트 추가(`tests/test_plan_quality_gates.py`)

### Phase Z. thesis fingerprint / dedupe 공유 적용
- 상태: 완료(신규)
- 구현:
  - `app/services/thesis_fingerprint.py` 추가
  - plan 생성 시 `thesis_fingerprint`, `thesis_cluster_id`, `thesis_cluster_size`, `thesis_primary_symbol`, `thesis_rejected_reason` 저장
  - scanner / portfolio overlay / exposure report가 동일 fingerprint 함수 공유
  - active thesis cluster `2개` cap과 duplicate thesis block reason(`thesis_duplicate_blocked`, `thesis_active_cap_reached`) 연동
  - `GET /scanner/top`, `GET /portfolio/budget`에 thesis 필드 노출
  - 현재 `correlation_cluster`는 plan 생성 단계에서는 symbol taxonomy fallback(`btc_beta` / `eth_beta` / `majors` / `others`)을 사용하고, portfolio overlay의 realized correlation penalty와 함께 운영
  - 회귀 테스트 추가(`tests/test_thesis_fingerprint.py`, `tests/test_portfolio_overlay.py`, `tests/test_portfolio_budget_report.py`, `tests/test_plan_quality_gates.py`)

### Phase ZA. 전략군별 scorecard 저장
- 상태: 완료(신규)
- 구현:
  - `StrategyFamilyDecision.scorecard` 추가
  - family별 raw component는 유지하되, 공통 bucket(`location`, `liquidity`, `reaction`, `invalidation`, `session`, `trendline_bonus`)으로 재매핑
  - `grade_thresholds`, `bucket_caps`, `score`, `score_ex_trendline`, `trendline_bonus_source` 저장
  - `trendline_bonus`는 현재 `0.0` 고정으로 명시하고 primary score에서 분리
  - plan `validity`에 `strategy_scorecard`, `strategy_scorecard_buckets`, `strategy_scorecard_raw_components`, `strategy_scorecard_trendline_bonus` 저장
  - `GET /scanner/top`에도 `strategy_scorecard` 노출
  - 회귀 테스트 추가(`tests/test_strategy_family_router.py`, `tests/test_plan_quality_gates.py`, `tests/test_api_smoke.py`)

### Phase ZB. sizing 함수 v2
- 상태: 완료(신규)
- 구현:
  - `PositionSizingService` 추가
  - sizing 공식 적용: `grade_risk x regime_factor x reaction_factor x thesis_factor x execution_factor`
  - `transition_watch/transition_confirmed -> 0.00R`, `mixed -> 0.00R`, `active thesis cluster >= 2 -> 0.00R`
  - `strategy_sizing`, `recommended_risk_r`를 plan `validity`, scanner, portfolio budget report에 공통 노출
  - legacy `/plans/top` payload도 sizing 기본값이 항상 존재하도록 보정
  - 파라미터 추적 추가: `sizing_*`
  - 회귀 테스트 추가(`tests/test_position_sizing.py`, `tests/test_api_smoke.py`)

### Phase ZC. 운영 모드 분리
- 상태: 완료(신규)
- 구현:
  - `StrategyModeService` 추가
  - 모드 추가: `A_ONLY`, `A_PLUS_B`, `RESEARCH`
  - 모드 정책 적용:
    - 허용 전략군/등급
    - 일일 trade cap
    - 총노출 cap(`R`)
    - `RESEARCH -> shadow-only / 0.00R`
  - `scanner` / `portfolio budget report` / `plans.top validity`에 `strategy_mode`, `mode_policy`, `mode_stats` 반영
  - 포트폴리오 리포트 파일명을 mode별로 분리
  - 현재 호환성 메모:
    - v2 family-tagged 후보에는 등급/가족 제한을 직접 적용
    - legacy generic plan은 기존 회귀를 유지하기 위해 임시 passthrough
  - 회귀 테스트 추가(`tests/test_strategy_mode.py`, `tests/test_portfolio_overlay.py`, `tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)

### Phase ZD. exit engine / time stop / information failure 연동
- 상태: 완료(신규)
- 구현:
  - `ExitReason` enum 추가
  - `ExitEngineService` 추가
    - `execution_fills.payload` 표준화
    - family time stop(`strategy_family_time_stop_max_bars`) 기반 `time_failure` 판정
    - `rejection -> acceptance` 반전 기반 `information_failure` 판정
  - `PositionStateMachineService` 연동
    - `plan.validity`에 `exit_events`, `final_exit_reason`, `final_exit_trigger_detail`, `final_exit_held_bars` 저장
  - `/internal/execution/fills` 확장
    - `exit_reason`, `held_bars`, `classification_before_exit`, `classification_after_exit`, `trigger_detail` 입력 지원
  - `ExecutionQualityService` 확장
    - `exit_reasons`, `final_exit_reasons`, `target_exit_ratio`, `forced_exit_ratio`, `information_failure_ratio`, `time_failure_ratio`, `by_strategy_family` 집계
  - `ValidationReportService` 확장
    - validation report에 exit-quality summary 포함
  - 회귀 테스트 추가(`tests/test_position_state_machine.py`, `tests/test_execution_fill_api.py`, `tests/test_execution_quality.py`, `tests/test_api_smoke.py`, `tests/test_validation_report.py`)

### Phase ZE. daily/session lock
- 상태: 완료(신규)
- 구현:
  - `OperatingLockService` 추가
    - daily lock: `daily_realized_r <= -2R`, `3연속 손실`, `A급 2연속 실패`
    - session lock: London/NY 세션에서 `session_realized_r <= -1.5R` 또는 `2연속 손실`
    - unlock policy: daily는 `다음 UTC day`, session은 `현재 세션 종료`
  - `StrategyEngine` gate 합성
    - 기존 `risk_gate` 위에 `operating_lock`을 합성해 `risk_reason`을 일관 노출
    - `refresh_symbol`, `scanner_top`, `portfolio_budget_report`, `metrics`에 lock snapshot 반영
  - API/리포트 확장
    - `GET /metrics/strategy`: `risk_reason`, `operating_lock`
    - `GET /scanner/top`: row-level `risk_reason`, `operating_lock`
    - `GET /portfolio/budget`: top-level `operating_lock`
  - 파라미터 추적 추가: `operating_lock_*`, `trading_session_*`
  - 회귀 테스트 추가(`tests/test_operating_lock.py`, `tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)

### Phase ZF. validation 비교 리포트(A-only vs A+B)
- 상태: 완료(신규)
- 구현:
  - `StrategyV2ValidationService` 추가
    - `closed plans`의 `strategy_family/strategy_grade/final_exit_*` 메타데이터로 `A_ONLY`, `A_PLUS_B`, `B_INCREMENTAL` 비교 집계
    - 지표: `trades`, `win_rate`, `EV`, `p5/p50 EV`, `max_drawdown`, `ulcer_index`, `avg_hold_bars`, `forced_exit_ratio`, `information_failure_ratio`, `time_failure_ratio`
    - 기본 배포 권고는 `A_ONLY`로 고정하되, `a_only_downside_better`와 `incremental_b_trades`를 함께 노출
  - 리포트 템플릿 추가
    - `reports/validation/strategy_v2_validation_<SYMBOL>_<VERSION>_<UTC>.md`
    - `Executive Summary`, `Comparison Table`, `Exit Reason / Failure Decomposition`, `Deployment Recommendation`
  - 엔진/validation report 연동
    - `POST /validation/report` 응답에 `strategy_v2_validation` 포함
    - 기본 validation markdown에 `Strategy v2 Mode Comparison` 섹션 추가
  - 회귀 테스트 추가(`tests/test_strategy_v2_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZG. transition/shock lock 적용 전후 비교
- 상태: 완료(신규)
- 구현:
  - `StrategyV2LockValidationService` 추가
    - `closed v2 plans`의 `regime`, `transition_state`, `strategy_family`, `strategy_grade`, `reaction_classification`, `final_exit_*` 메타데이터로 `before_lock` vs `after_lock` 비교 집계
    - transition 관련 trade는 제거, shock 관련 trade는 현재 shock regime factor로 계정 영향 기준 clamp
    - 지표: `trades`, `win_rate`, `EV`, `p5/p50 EV`, `max_drawdown`, `ulcer_index`, `avg_hold_bars`, `forced_exit_ratio`, `information_failure_ratio`, `time_failure_ratio`
  - 리포트 템플릿 추가
    - `reports/validation/strategy_v2_lock_validation_<SYMBOL>_<VERSION>_<UTC>.md`
    - `Executive Summary`, `Comparison Table`, `Impact Breakdown`, `Deployment Recommendation`
  - 엔진/validation report 연동
    - `POST /validation/report` 응답에 `strategy_v2_lock_validation` 포함
    - 기본 validation markdown에 `Transition / Shock Lock Comparison` 섹션 추가
  - 회귀 테스트 추가(`tests/test_strategy_v2_lock_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZH. thesis dedupe 적용 전후 drawdown 비교
- 상태: 완료(신규)
- 구현:
  - `StrategyV2ThesisValidationService` 추가
    - `closed v2 plans`를 글로벌 포트폴리오 범위에서 수집하고, `thesis_fingerprint`, `thesis_cluster_id`, `final_exit_*`, `valid_from`/ENTRY fill 시각으로 `before_dedupe` vs `after_dedupe` 비교 집계
    - 현재 근사 규칙:
      - 같은 thesis가 겹치면 later overlapping trade 제거
      - distinct thesis cluster가 `thesis_max_active_clusters`를 넘기면 after에서 제거
      - ENTRY fill이 있으면 open time으로 사용하고, 없으면 `valid_from`으로 폴백
    - 지표: `trades`, `win_rate`, `EV`, `p5/p50 EV`, `max_drawdown`, `ulcer_index`, `avg_hold_bars`, `forced_exit_ratio`, `information_failure_ratio`, `time_failure_ratio`
  - 리포트 템플릿 추가
    - `reports/validation/strategy_v2_thesis_validation_<SYMBOL>_<VERSION>_<UTC>.md`
    - `Executive Summary`, `Comparison Table`, `Impact Breakdown`, `Deployment Recommendation`
  - 엔진/validation report 연동
    - `POST /validation/report` 응답에 `strategy_v2_thesis_validation` 포함
    - 기본 validation markdown에 `Thesis Dedupe Comparison` 섹션 추가
  - 회귀 테스트 추가(`tests/test_strategy_v2_thesis_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZI. cost `x1.5` / slippage `x2` stress report
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressValidationService` 추가
    - `closed v2 plans`의 `final_exit_realized_r`를 기준선으로 삼고, baseline/stressed cost를 R 단위로 차감해 `baseline_cost` vs `stressed_cost` 비교 집계
    - 현재 근사 규칙:
      - `execution_fills`가 있으면 actual fee + entry slippage 우선
      - 없으면 `plan.cost_est`를 fee/slippage component로 분해해 폴백
      - stress multiplier는 현재 고정값 `cost x1.5`, `slippage x2`
    - 지표: `trades`, `win_rate`, `EV`, `p5/p50 EV`, `max_drawdown`, `ulcer_index`, `avg_hold_bars`, `forced_exit_ratio`, `information_failure_ratio`, `time_failure_ratio`
  - 리포트 템플릿 추가
    - `reports/validation/strategy_v2_stress_validation_<SYMBOL>_<VERSION>_<UTC>.md`
    - `Executive Summary`, `Comparison Table`, `Cost Summary`, `Deployment Recommendation`
  - 엔진/validation report 연동
    - `POST /validation/report` 응답에 `strategy_v2_stress_validation` 포함
    - 기본 validation markdown에 `Stressed Cost Comparison` 섹션 추가
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZJ. PBO / DSR 검증 설계 추가
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrDesignService` 추가
    - 현재 단계는 계산이 아니라 `design-ready / not computed` 계약 고정
    - `PBO=CSCV`, `DSR=deflated_sharpe_ratio` 기준과 threshold를 payload로 노출
    - 필요한 저장 contract(`validation_trial_runs`, `validation_trial_fold_scores`, `validation_pbo_dsr_snapshots`)와 blocker를 함께 노출
  - 리포트 템플릿 추가
    - `reports/validation/strategy_v2_pbo_dsr_design_<SYMBOL>_<VERSION>_<UTC>.md`
    - `PBO Design`, `DSR Design`, `Proposed Storage Contract`, `Blockers`, `Next Implementation Steps`
  - 엔진/validation report 연동
    - `POST /validation/report` 응답에 `strategy_v2_pbo_dsr_design` 포함
    - 기본 validation markdown에 `PBO / DSR Design Status` 섹션 추가
  - 회귀 테스트 추가(`tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZJ-2. PBO / DSR runtime artifact store 설계 착수
- 상태: 완료(신규)
- 구현:
  - DB 계약 추가
    - `validation_trial_runs`
    - `validation_trial_fold_scores`
    - `validation_pbo_dsr_snapshots`
  - `ValidationArtifactRepository` + `StrategyV2PboDsrArtifactStoreService` 추가
    - `schema ready / empty`
    - `seeded / not computed`
    - `metrics available`
    상태를 분리해서 노출
  - API / validation report 연동
    - `GET /validation/pbo-dsr/artifact-store`
    - `POST /validation/report` 응답에 `strategy_v2_pbo_dsr_artifact_store` 포함
    - 기본 validation markdown에 `PBO / DSR Artifact Store` 섹션 추가
  - `strategy_v2_pbo_dsr_design`가 artifact store 상태를 상위 요약으로 반영
  - 회귀 테스트 추가(`tests/test_strategy_v2_pbo_dsr_artifact_store.py`, `tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZK. 실전 운영 체크리스트를 API/리포트 항목과 연결
- 상태: 완료(신규)
- 구현:
  - `OperationalChecklistService` 추가
    - 운영 체크리스트를 `health`, `validation`, `validation alert`, `alerts SLO`, `recent alert test`, `retry queue`, `event outbox`, `risk gate`, `portfolio headroom`, `execution quality`, `PBO/DSR design`으로 집계
    - 최근 `POST /alerts/test` 이력은 `AlertSubscription(type=test)` 기준으로만 판단하고, 자동 테스트는 수행하지 않음
    - blocking item이 `FAIL` 또는 `MANUAL`이면 overall은 `FAIL`
  - API / 스크립트 추가
    - `POST /operations/checklist`
    - `scripts/generate_operational_checklist_report.py`
  - markdown 리포트 추가
    - `reports/operations/operational_checklist_<SYMBOL>_<VERSION>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZK-2. 실전 운영 체크리스트의 session/dead-session 가이드 연결
- 상태: 완료(신규)
- 구현:
  - `OperationalChecklistService`에 `session_guidance` 항목 추가
    - `current_session`
    - `preferred_windows_utc`
    - `dead_session`
    - `session_lock_active`
    를 evidence로 남김
  - 해석 규칙 고정
    - London / New York 활성 세션: `PASS`
    - `dead session`: `WARN`
    - `session lock active`: `WARN`
    - hard block은 기존 `risk_gate_open`이 계속 담당
  - 회귀 테스트 추가(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZK-3. session/dead-session guidance의 scanner 후보 레벨 승격
- 상태: 완료(신규)
- 구현:
  - `SessionGuidanceService` 추가
    - `OperationalChecklistService`와 scanner/portfolio overlay가 같은 세션 판단 로직을 공유
    - `dead_session`, `session_lock_active`, `preferred_windows_utc`, `soft_penalty`를 단일 payload로 고정
  - scanner / portfolio 후보 필드 확장
    - `GET /scanner/top`와 `GET /portfolio/budget` 후보 row에 `session_guidance`, `session_penalty` 추가
    - `dead session`과 `session lock active`는 hard block이 아니라 ranking-only soft penalty로만 반영
    - 기존 `risk_gate_open`과 `operating_lock`의 차단 책임은 유지
  - markdown/API/회귀 테스트 연동
    - portfolio markdown에 `session_penalty` 출력 추가
    - 회귀 테스트 추가(`tests/test_session_guidance.py`, `tests/test_portfolio_overlay.py`, `tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)

### Phase ZL. 추가 stress 축(`latency +1 bar`, `partial fills only`, `shock concentration`)
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressValidationService` 확장
    - 기존 `baseline_cost` vs `stressed_cost` 유지
    - 추가 시나리오:
      - `latency_plus_1_bar`
      - `partial_fills_only`
      - `shock_concentration`
    - 현재 근사 규칙:
      - `latency +1 bar`: next 5m candle open 기준 directional adverse move만 penalty 반영, 캔들 없으면 slippage fallback
      - `partial fills only`: 현재 `50% fill ratio` 고정 근사
      - `shock concentration`: `regime=shock` trade의 손실 영향 확대 / 이익 영향 축소
  - 엔진/validation report 연동
    - `POST /validation/report`의 `strategy_v2_stress_validation`에 `scenario_metrics`, `scenario_comparison`, `scenario_summary`, `deployment_recommendation.scenario_statuses` 추가
    - 기본 validation markdown의 `Stressed Cost Comparison` 섹션에 추가 scenario 요약 삽입
  - 회귀 테스트 보강(`tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-2. stress 축의 full replay 대체 여부 평가
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayAssessmentService` 추가
    - 현재 stress 근사(`plan/fill/candle` 기반)를 유지할지, full replay 대체 우선순위를 올릴지 평가
    - `execution_fill_coverage`, `latency_candle_coverage`, `shock_regime_trade_share`, `estimate_only_share`를 coverage로 노출
    - `degraded_scenarios`, `catastrophic_scenarios`, `worst_scenario`, `scenario_statuses`를 묶어 replacement 필요도를 산출
    - `full_replay_ready`와 `replacement_recommended`를 분리해 lineage 준비도와 우선순위를 따로 판단
  - 엔진/API/validation report 연동
    - `GET /validation/stress-replay-assessment`
    - `POST /validation/report` 응답에 `strategy_v2_stress_replay_assessment` 포함
    - 기본 validation markdown에 `Stress Replay Assessment` 섹션 추가
    - 별도 markdown 리포트 추가: `reports/validation/strategy_v2_stress_replay_assessment_<SYMBOL>_<VERSION>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-3. stress full replay writer/runtime lineage 입력 계약
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayLineageService` 추가
    - `closed v2 trades + execution_fills + 5m candles`를 읽어 full replay 전환용 입력 lineage 상태를 평가
    - `runtime_inputs_ready`, `coverage`, `gap_counts`, `fill_path`, `candle_path`, `blocked_by`, `next_steps`를 공통 payload로 노출
    - anchor source는 `ENTRY/CLOSED fill` 우선, 없으면 `plan.valid_from/final_exit_ts` fallback을 사용
    - 현재 고정 임계값:
      - `stress_replay_lineage_min_execution_fill_coverage`
      - `stress_replay_lineage_min_latency_candle_coverage`
      - `stress_replay_lineage_min_candle_path_coverage`
  - 엔진/API/validation report 연동
    - `GET /validation/stress-replay-lineage`
    - `POST /validation/report` 응답에 `strategy_v2_stress_replay_lineage` 포함
    - 기본 validation markdown에 `Stress Replay Lineage` 섹션 추가
    - 별도 markdown 리포트 추가: `reports/validation/strategy_v2_stress_replay_lineage_<SYMBOL>_<VERSION>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_replay_lineage.py`, `tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-4. stress full replay 최소 runner/worker 계약
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayRunnerContractService` 추가
    - `stress_validation + stress_replay_lineage + stress_replay_assessment`를 묶어 `runtime_job_ready`, `implementation_status`, `scenario_contract`, `runner_contract`, `worker_input_contract`, `worker_output_contract`를 공통 payload로 노출
    - scenario별 readiness(`shock_concentration`, `latency_plus_1_bar`, `partial_fills_only`)와 prototype batch count를 계산
    - 현재 고정 batching 계약:
      - `stress_replay_runner_target_trades_per_job`
      - `stress_replay_runner_min_trades_per_job`
      - `stress_replay_runner_max_parallel_jobs`
  - 엔진/API/validation report 연동
    - `GET /validation/stress-replay-runner-contract`
    - `POST /validation/report` 응답에 `strategy_v2_stress_replay_runner_contract` 포함
    - 기본 validation markdown에 `Stress Replay Runner Contract` 섹션 추가
    - 별도 markdown 리포트 추가: `reports/validation/strategy_v2_stress_replay_runner_contract_<SYMBOL>_<VERSION>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_replay_runner_contract.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-5. full replay writer/runtime lineage와 stress scenario lineage의 lineage writer 연결
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayLineageWriterService` 추가
    - `strategy_v2_stress_replay_lineage.trade_rows`와 `strategy_v2_stress_replay_runner_contract.scenario_contract`를 묶어 scenario별 batch artifact를 JSON으로 materialize
    - 현재 scenario filter:
      - `shock_concentration`: `regime == shock`
      - `latency_plus_1_bar`: `latency_bar_exists == true`
      - `partial_fills_only`: `full_fill_path == true`
    - artifact 경로:
      - `reports/validation/stress_replay_lineage_batches/<symbol>/<version>/<utc>/<scenario>_batch_<nn>.json`
  - 엔진/API/validation report 연동
    - `GET /validation/stress-replay-lineage-writer`
    - `POST /validation/report` 응답에 `strategy_v2_stress_replay_lineage_writer` 포함
    - 기본 validation markdown에 `Stress Replay Lineage Writer` 섹션 추가
    - 별도 markdown 리포트 추가: `reports/validation/strategy_v2_stress_replay_lineage_writer_<SYMBOL>_<VERSION>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_replay_lineage_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZJ-3. PBO / DSR metric 계산 루프(CSCV/PBO, DSR)
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrMetricsService` 추가
    - `validation_trial_runs`, `validation_trial_fold_scores`를 읽어 `selected trial`, `PBO`, `DSR` 계산
    - `PBO`: selected trial이 fold별 OOS worse-half에 들어간 비율
    - `DSR`: selected trial sharpe_like_score와 selection-universe adjustment 기반 signed score + probability
  - snapshot writer 연동
    - 계산 결과를 `validation_pbo_dsr_snapshots`에 upsert
    - `artifact_store.metrics_available`와 `design.available`가 computed 상태를 반영
  - 엔진/API/validation report 연동
    - `GET /validation/pbo-dsr`
    - `POST /validation/report` 응답에 `strategy_v2_pbo_dsr_metrics` 포함
    - 기본 validation markdown에 `PBO / DSR Metrics` 섹션 추가
    - 별도 markdown 리포트 추가: `reports/validation/strategy_v2_pbo_dsr_metrics_<SYMBOL>_<VERSION>_<UTC>.md`
  - 회귀 테스트 추가(`tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZJ-4. PBO / DSR trial/fold writer 실전 validation 루프 연결
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrTrialWriterService` 추가
    - `closed v2 plans`에서 `mode_policy`, `lock_policy`, `stress_policy` runtime proxy trial을 구성
    - contiguous fold 분할로 `validation_trial_runs`, `validation_trial_fold_scores`를 자동 seed
    - `selection_rule=runtime_validation_proxy_top_in_sample_ev`로 rank/selected_flag를 고정
  - 엔진/API/validation report 연동
    - `recompute_learning()`이 `writer -> metrics -> artifact/design` 순서로 동작
    - `GET /validation/pbo-dsr/trial-writer`
    - `POST /validation/report` 응답에 `strategy_v2_pbo_dsr_trial_writer` 포함
    - 기본 validation markdown에 `PBO / DSR Trial Writer` 섹션 추가
    - 별도 markdown 리포트 추가: `reports/validation/strategy_v2_pbo_dsr_trial_writer_<SYMBOL>_<VERSION>_<UTC>.md`
  - 저장 정책
    - trial/fold row는 symbol/version 단위로 replace seed
    - snapshot은 기존대로 append/upsert lineage 유지
  - 회귀 테스트 추가(`tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZJ-5. threshold-sweep family를 runtime proxy writer 위에 확장
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrTrialWriterService` 확장
    - 기존 `mode_policy`, `lock_policy`, `stress_policy` runtime proxy trial 위에 stored-plan threshold proxy family를 추가 seed
    - 현재 연결된 family:
      - `scoring_thresholds` (`validity.confluence_score` 기반)
      - `transition_threshold` (`validity.transition_score` 기반)
      - `acceptance_rejection_thresholds` (`reaction_classification`, `reaction_rejection_score`, `reaction_acceptance_score` 기반)
      - `sizing_clamps` (`recommended_risk_r`와 grade clamp 기반 realized R scaling)
    - 응답 payload에 `threshold_parameter_families_present`, `candidate_trials_by_family` 추가
    - 현재 평가는 true parameter rerun이 아니라 `closed v2 trades + stored validity fields` 기반 proxy sweep이다
  - 엔진/API/validation report 연동
    - `GET /validation/pbo-dsr/trial-writer`
    - `POST /validation/report` 응답의 `strategy_v2_pbo_dsr_trial_writer` payload 확장
    - 기본 validation markdown의 `PBO / DSR Trial Writer` 섹션에 hybrid writer 상태 반영
  - 회귀 테스트 보강(`tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZJ-6. true threshold-sweep runner를 runtime proxy writer와 분리된 lineage로 연결
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrThresholdRunnerService` 추가
    - true threshold family를 `selection_rule=true_threshold_sweep_top_in_sample_ev`로 별도 seed
    - `validation_trial_runs/fold_scores`는 selection rule 단위 replace로 runtime proxy lineage와 공존
  - 엔진/API/validation report 연동
    - `GET /validation/pbo-dsr/threshold-runner`
    - `POST /validation/report` 응답에 `strategy_v2_pbo_dsr_threshold_runner` 포함
    - 기본 validation markdown에 `PBO / DSR Threshold Runner` 섹션 추가
  - lineage audit surface
    - `strategy_v2_pbo_dsr_artifact_store.selection_rule_counts`
    - `strategy_v2_pbo_dsr_metrics.selected_trial.writer_source`
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_pbo_dsr_threshold_runner.py`, `tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_strategy_v2_pbo_dsr_artifact_store.py`, `tests/test_strategy_v2_pbo_dsr_design.py`, `tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-6. replay worker output artifact를 validation stress 비교 payload에 연결
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayOutputArtifactsService` 추가
    - `reports/validation/stress_replay_worker_outputs/<SYMBOL>/<VERSION>/*.json`에서 최신 scenario별 replay worker output artifact를 로드
    - 현재 worker output schema contract:
      - `schema_version=strategy_v2_stress_replay_worker_output_v1`
      - top-level: `generated_at`, `symbol`, `version`, `scenario`, `summary`
      - summary: `trades`, `ev`, `p5_ev`, `max_drawdown`, `ulcer_index`
    - `comparison_to_approximation`으로 현재 stress approximation 시나리오와 replay output 차이를 계산
  - stress payload 연동
    - `strategy_v2_stress_validation`에 `replay_output_artifacts`, `replay_output_comparison`을 추가
    - `Validation Report`의 `Stressed Cost Comparison` 섹션에서 scenario별 replay output 유무와 delta를 함께 노출
  - 엔진/API 연동
    - `GET /validation/stress-replay-output-artifacts`
    - `recompute_learning()`과 `POST /validation/report`가 같은 artifact reader payload를 사용
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_replay_output_artifacts.py`, `tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-7. stress full replay prototype worker contract를 artifact writer와 실제 실행 경로에 연결
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayPrototypeWorkerService` 추가
    - `strategy_v2_stress_replay_lineage_writer.scenario_batches`를 읽어 scenario별 prototype replay trade row를 계산
    - 현재 worker mode:
      - `prototype_from_lineage_batches`
      - `latency_plus_1_bar`: fixed latency/path penalty 기반 deterministic replay proxy
      - `partial_fills_only`: fill-factor/path penalty 기반 deterministic replay proxy
      - `shock_concentration`: shock factor/path penalty 기반 deterministic replay proxy
    - output artifact 경로:
      - `reports/validation/stress_replay_worker_outputs/<symbol>/<version>/<scenario>_<utc>.json`
  - 엔진/API/validation report 연동
    - `POST /validation/stress-replay-worker/prototype`
    - `recompute_learning()`이 `lineage_writer -> prototype_worker -> output_artifacts` 순서로 같은 contract를 사용
    - `POST /validation/report` 응답에 `strategy_v2_stress_replay_prototype_worker` 포함
    - 기본 validation markdown에 `Stress Replay Prototype Worker` 섹션 추가
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_replay_prototype_worker.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-8. replay worker output artifact를 deployment recommendation gate에 반영
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressValidationService` 확장
    - `strategy_v2_stress_validation.replay_output_artifacts.scenario_outputs[*].summary`가 있으면 해당 scenario의 deployment gate를 approximation 대신 replay output 기준으로 평가
    - `deployment_recommendation`에 아래 필드 추가:
      - `replay_gate_applied`
      - `replay_gate_reason`
      - `replay_scenarios_considered`
      - `scenario_sources`
      - `worst_scenario_source`
    - `scenario_statuses[*].source`로 `approximation` vs `replay_output`를 명시
  - validation/report 연동
    - `Validation Report`와 `strategy_v2_stress_validation_summary`가 `worst_scenario_source`, `replay_gate_applied`, `replay_gate_reason`를 함께 출력
  - 해석 규칙
    - replay output artifact가 없는 scenario는 기존 approximation 기준을 유지
    - replay output artifact가 있는 scenario만 deployment gate evidence를 override
    - base `stressed_cost` row는 계속 approximation 기준이다
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-9. prototype replay worker -> true market replay runner readiness gate 세분화
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayAssessmentService` 확장
    - `true_runner_readiness` payload 추가
    - stronger gate:
      - `stress_true_replay_min_execution_fill_coverage`
      - `stress_true_replay_min_latency_candle_coverage`
      - `stress_true_replay_min_candle_path_coverage`
      - `stress_true_replay_min_scenarios_compared`
    - `critical_scenarios`(`catastrophic + degraded + worst fallback`)와 prototype replay output coverage를 함께 평가
  - `StrategyV2StressReplayRunnerContractService` 확장
    - `runtime_job_ready`는 계속 prototype contract readiness를 뜻한다
    - `true_runner_readiness.true_runner_ready`는 true market replay runner replacement readiness를 뜻한다
    - `implementation_status=runner_contract_defined_ready_for_true_market_runner` 상태 추가
  - 엔진/validation report/API 연동
    - `strategy_engine._build_stress_replay_runtime_stack()`가 replay-attached stress validation 기준 assessment/runner contract를 생성
    - `GET /validation/stress-replay-assessment`
    - `GET /validation/stress-replay-runner-contract`
    - `POST /validation/report` summary가 `true_runner_ready`, `true_runner_stage`를 함께 노출
  - 해석 규칙
    - `prototype ready`와 `true runner ready`는 별도 상태다
    - true runner는 stronger lineage threshold와 critical scenario replay-output coverage를 동시에 만족해야 한다
    - replacement recommendation이 없으면 true runner readiness도 `false`로 유지한다
  - 회귀 테스트 추가(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_strategy_v2_stress_replay_runner_contract.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`, `tests/test_strategy_engine_ops.py`)

### Phase ZL-10. proxy writer vs true threshold runner lineage audit를 deployment gate에 반영
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrMetricsService` 확장
    - `lineage_audit` payload 추가
    - `selection_rule_counts`, `selected_trial.writer_source`, `selected_trial.selection_rule`, `lineage_namespace`를 같은 기준으로 해석
    - dual-lineage(`runtime proxy` + `true threshold`)가 공존하는데 selected trial이 runtime proxy에서 오면:
      - `lineage_audit.audit_status=WARN`
      - `deployment_recommendation.decision=warn_lineage_audit|warn_overfit_and_lineage_audit`
      - `lineage_audit_applied=true`
    - legacy/unclassified selection rule만 있는 경우는 `legacy_or_unclassified_selection_rules_only`로 PASS 처리
  - validation/report 연동
    - `GET /validation/pbo-dsr` payload에 `lineage_audit` 추가
    - 기본 validation markdown과 `strategy_v2_pbo_dsr_metrics_summary`가 `lineage_audit_status`, `selected_trial_from_runtime_proxy`, `selected_trial_from_true_threshold`를 함께 노출
  - 버그 수정
    - `meets_protocol_gate` 계산에서 `PBO value=0.0`을 falsy로 오해하던 로직을 수정해 `pbo_status=PASS, dsr_status=PASS`가 잘못 `fail_validation_gate`로 내려가지 않도록 고정
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-11. replay-derived stress output과 approximation의 divergence threshold를 deployment policy로 고정
- 상태: 완료(신규)
- 구현:
  - `Settings` 확장
    - `stress_replay_divergence_warn_ev_delta`
    - `stress_replay_divergence_fail_ev_delta`
    - `stress_replay_divergence_warn_max_drawdown_delta`
    - `stress_replay_divergence_fail_max_drawdown_delta`
  - `StrategyV2StressValidationService` 확장
    - replay-backed scenario마다 `divergence_status`, `divergence_reason`, `divergence_axes`, `divergence_thresholds` 계산
    - replay output은 scenario 자체가 PASS라도 divergence가 크면 `status`를 `WARN/FAIL`로 승격
    - `deployment_recommendation`에 아래 필드 추가:
      - `divergence_gate_applied`
      - `divergence_problem_scenarios`
      - `divergence_fail_scenarios`
      - `divergence_warn_scenarios`
      - `worst_divergence_scenario`
      - `divergence_thresholds`
    - reason 우선순위:
      - `scenario_catastrophic_drawdown`
      - `replay_divergence_fail`
      - `replay_divergence_warn`
      - `scenario_degraded`
  - validation/report 연동
    - `Validation Report`와 `strategy_v2_stress_validation_summary`가 divergence gate 상태를 같이 출력
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_stress_validation.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-12. true market replay runner 실행 lineage와 threshold lineage를 배포 판정에 함께 연결
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayAssessmentService` 확장
    - `pbo_dsr_metrics`를 함께 받아 `true_runner_readiness`와 `strategy_v2_pbo_dsr_metrics.lineage_audit`를 같은 deployment contract로 결합
    - `deployment_recommendation.true_runner_promotion_*` 필드 추가:
      - `true_runner_promotion_gate_applied`
      - `true_runner_promotion_ready`
      - `true_runner_promotion_status`
      - `true_runner_promotion_action`
      - `true_runner_promotion_reason`
    - `threshold_lineage_audit_status/reason`, `selected_trial_writer_source/selection_rule`를 함께 노출해 실제 승격 차단 원인을 같은 payload에 고정
    - base replacement decision(`keep_approximation` / `prepare_full_replay` / `recommend_full_replay`)은 유지하고, actual runner promotion action은 별도 필드로 분리
  - 엔진 연동
    - `StrategyEngine._build_stress_replay_runtime_stack()`가 assessment 단계에 `pbo_dsr_metrics`를 함께 전달
    - direct stress replay assessment endpoint도 같은 contract를 재사용
  - validation/report 연동
    - `Validation Report`와 `strategy_v2_stress_replay_assessment_summary`가 `true_runner_promotion_*`, `threshold_lineage_audit_status`, `selected_trial_writer_source`를 함께 출력
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_strategy_engine_ops.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-13. selection-universe count를 full parameter-sweep universe 기준으로 분리 기록
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrMetricsService` 확장
    - `selection_universe_summary` payload 추가
    - 분리 기록 항목:
      - `combined_artifact_selection_universe_size`
      - `runtime_proxy_selection_universe_size`
      - `true_threshold_selection_universe_size`
      - `full_parameter_sweep_selection_universe_size`
      - `selected_trial_lineage_selection_universe_size`
      - `dsr_selection_universe_size`
      - `dsr_selection_universe_basis`
    - 현재 DSR 계산은 계속 `combined_artifact_universe`를 쓰되, full parameter-sweep universe는 별도 기록만 수행
    - snapshot payload에도 `selection_universe_summary`를 같이 저장
  - `StrategyV2PboDsrArtifactStoreService` 확장
    - artifact-store root payload와 markdown에 `selection_universe_summary` 추가
    - latest snapshot과 current trial-run counts를 함께 사용해 split recording 상태를 노출
  - selected trial metadata 보강
    - `ValidationTrialRun.payload`에 `selection_universe_basis`, `lineage_selection_universe_size`
    - true threshold lineage에는 `full_parameter_sweep_selection_universe_size`도 기록
  - validation/report/API 연동
    - `GET /validation/pbo-dsr`
    - `GET /validation/pbo-dsr/artifact-store`
    - `Validation Report`의 `strategy_v2_pbo_dsr_metrics_summary`, `strategy_v2_pbo_dsr_artifact_store_summary`
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_pbo_dsr_artifact_store.py`, `tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-14. best-trial Sharpe bias adjustment를 threshold-sweep universe 기준으로 재검증
- 상태: 완료(신규)
- 구현:
  - `StrategyV2PboDsrMetricsService` 확장
    - DSR bias adjustment가 `full_parameter_sweep_selection_universe_size`를 우선 사용
    - fallback은 `combined_artifact_universe`
    - `dsr.selection_universe_basis`, `legacy_combined_selection_universe_size`, `legacy_combined_benchmark_sharpe`, `benchmark_sharpe_delta_vs_legacy_combined` 추가
  - `selection_universe_summary` 확장
    - `dsr_selection_universe_basis`
    - `bias_adjustment_rechecked`
  - snapshot/report/API 연동
    - snapshot top-level `selection_universe_size`가 active DSR basis를 따르도록 정렬
    - `Validation Report`와 markdown이 active/legacy bias adjustment를 같이 출력
  - 설계 서비스/문서 정렬
    - dual-lineage seeded 상태에서 `selection_universe_basis` snapshot write를 next-step으로 고정
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_pbo_dsr_metrics.py`, `tests/test_strategy_v2_pbo_dsr_trial_writer.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-15. true market replay runner output lineage를 selected trial source audit와 deployment summary에 더 직접 결합
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayPrototypeWorkerService` 확장
    - worker output artifact에 `input_lineage_summary` 추가
    - `input_batch_count`, `input_trade_rows`, `entry/exit anchor sources`, `regime_counts`, `path coverage summary` 기록
  - `StrategyV2StressReplayOutputArtifactsService` 확장
    - root `lineage_summary` 추가
    - `worker_modes`, `compared_scenarios`, `input_batch_count`, `input_trade_rows` 집계
  - `StrategyV2StressReplayAssessmentService` 확장
    - `replay_output_lineage_alignment_*` 필드 추가
    - replay output lineage가 있고 selected trial이 runtime proxy면 promotion reason을 직접 `replay_output_lineage_alignment:*`로 고정
    - `deployment_recommendation`이 `selected_trial source audit + replay output lineage summary`를 한 payload로 해석
  - validation/report/API 연동
    - `/validation/stress-replay-output-artifacts`가 `lineage_summary`를 노출
    - `Validation Report`와 `strategy_v2_stress_replay_assessment_summary`가 `replay_output_lineage_alignment_status/reason`, `replay_output_lineage_compared_scenarios`를 같이 출력
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_stress_replay_prototype_worker.py`, `tests/test_strategy_v2_stress_replay_output_artifacts.py`, `tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-16. threshold lineage winner와 replay-derived worst scenario를 deployment approval 템플릿에서 직접 교차 표시
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayAssessmentService` 확장
    - `deployment_recommendation.approval_cross_display` 추가
    - `threshold_lineage_winner_*`와 `replay_derived_worst_scenario_*`를 같은 payload로 고정
    - replay output source가 누락된 fixture/partial payload도 output artifact 존재 시 `replay_output`로 해석하도록 보강
  - `ValidationReportService` 확장
    - `deployment_approval_summary` 추가
    - markdown에 `## Deployment Approval Template` 섹션 추가
    - threshold lineage winner/source/type, replay worst scenario/source/status/divergence, true-runner promotion action을 같은 섹션에서 출력
  - validation/report/API 연동
    - `POST /validation/report`의 `validation_report` payload가 `deployment_approval_summary`를 노출
    - `strategy_v2_stress_replay_assessment_summary`가 `approval_cross_display`를 같이 노출
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-17. proxy lineage selected-trial이 replay-backed deployment summary에 남을 때 경고 문구를 approval template에 직접 고정
- 상태: 완료(신규)
- 구현:
  - `StrategyV2StressReplayAssessmentService` 확장
    - `approval_cross_display.approval_warning_locked/code/message` 추가
    - `runtime_proxy winner + replay_output worst scenario` 조합이면 고정 경고 문구를 직접 기록
  - `ValidationReportService` 확장
    - `deployment_approval_summary.approval_warning_*` 추가
    - markdown `Deployment Approval Template`에 경고 잠금/코드/문구 출력
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_stress_replay_assessment.py`, `tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-18. replay output lineage alignment warning을 deployment approval 템플릿의 top-level 승인 문구와 직접 연결
- 상태: 완료(신규)
- 구현:
  - `ValidationReportService` 확장
    - `deployment_approval_summary.topline_status/code/message` 추가
    - `replay_output_lineage_alignment_status/reason`과 `approval_warning_*`를 합성해 top-level 승인 문구 생성
    - markdown `Deployment Approval Template` 상단에 `topline_*` 출력
  - 회귀 테스트 추가/보강(`tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-19. threshold lineage winner / replay-derived worst scenario / true-runner promotion action을 최상단 승인 문구에서 한 줄로 요약
- 상태: 완료(신규)
- 구현:
  - `ValidationReportService` 확장
    - `deployment_approval_summary.topline_summary_line` 추가
    - `winner / worst / promotion` 세 축을 항상 포함한 한 줄 summary 생성
    - `topline_message`도 같은 한 줄 summary를 포함하도록 정렬
    - markdown `Deployment Approval Template`에 `topline_summary_line` 출력
  - 회귀 테스트 추가/보강(`tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-20. approval template warning code를 운영 playbook의 go/no-go 문구와 1:1 매핑
- 상태: 완료(신규)
- 구현:
  - `ValidationReportService` 확장
    - `deployment_approval_summary.playbook_go_no_go/code/action/message` 추가
    - `approval_warning_code`를 `GO / NO_GO / MANUAL_REVIEW` 운영 문구로 직접 매핑
    - markdown `Deployment Approval Template`에 같은 playbook 필드 출력
  - `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`에 warning code별 운영 행동 표 추가
  - 회귀 테스트 추가/보강(`tests/test_validation_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-21. approval template top-level 문구를 scanner/ops checklist 배포 판단과 공통 언어로 정렬
- 상태: 완료(신규)
- 구현:
  - `ValidationReportService`
    - `topline_message`를 `GO / NO_GO / MANUAL_REVIEW` prefix 언어로 정렬
  - `OperationalChecklistService`
    - `deployment_go_no_go/code/message` 추가
    - validation approval summary와 operational blocking/warn 상태를 같은 배포 언어로 합성
  - `ScannerService`
    - candidate row에 `deployment_go_no_go/code/message` 추가
    - `risk_gate/operating_lock` 상태를 같은 배포 언어로 노출
  - 회귀 테스트 추가/보강(`tests/test_validation_report.py`, `tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZL-22. approval template one-line summary를 validation alert payload에도 동일하게 반영
- 상태: 완료(신규)
- 구현:
  - `StrategyEngine._maybe_emit_validation_alert`
    - `approval_topline_summary_line`를 validation alert payload, cooldown payload, retry payload, event payload에 추가
  - `NotificationDispatcher`
    - validation alert 메시지에 `approval=<topline_summary_line>` 출력
  - alert ID 생성
    - 초 단위 timestamp 기반 alert ID를 `uuid` 기반 helper로 교체해 중복 충돌 제거
  - 회귀 테스트 추가/보강(`tests/test_validation_alerts.py`, `tests/test_notification_dispatcher.py`, `tests/test_strategy_engine_ops.py`, `tests/test_api_smoke.py`)

### Phase ZL-23. approval template playbook mapping을 validation alert payload에도 동일하게 반영
- 상태: 완료(신규)
- 구현:
  - `StrategyEngine._maybe_emit_validation_alert`
    - `approval_playbook_go_no_go/code/action/message`를 validation alert payload, cooldown payload, retry payload, event payload에 추가
    - source of truth는 `deployment_approval_summary.playbook_*`
  - 회귀 테스트 추가/보강(`tests/test_validation_alerts.py`, `tests/test_api_smoke.py`)

### Phase ZL-24. approval template deployment language를 portfolio budget/report 요약에도 직접 반영
- 상태: 완료(신규)
- 구현:
  - `PortfolioBudgetReportService`
    - `deployment_go_no_go/code/message`를 top-level payload와 markdown summary에 추가
    - runtime deployment language는 scanner와 동일 helper를 재사용
  - API 응답 모델 확장
    - `GET /portfolio/budget` top-level에 `deployment_go_no_go/code/message` 노출
  - 회귀 테스트 추가/보강(`tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-25. validation alert payload의 deployment language를 alert metrics/ops checklist evidence에도 직접 반영
- 상태: 완료(신규)
- 구현:
  - `StrategyEngine._maybe_emit_validation_alert`
    - `deployment_go_no_go/code/message`를 validation alert payload, cooldown payload, retry payload, event payload에 추가
  - `AlertMetricsService`
    - `latest_validation_alert` summary 추가
    - `deployment_go_no_go/code/message`, `approval_topline_summary_line`, delivery 상태를 top-level evidence로 노출
  - `OperationalChecklistService`
    - `validation_alert_delivery.evidence`와 `alert_channel_slo.evidence.latest_validation_alert`에 deployment language 직접 반영
  - 회귀 테스트 추가/보강(`tests/test_validation_alerts.py`, `tests/test_alert_metrics.py`, `tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZL-26. validation alert payload의 playbook mapping을 alert metrics evidence에도 직접 반영
- 상태: 완료(신규)
- 구현:
  - `AlertMetricsService`
    - `latest_validation_alert` summary에 `approval_playbook_go_no_go/code/action/message` 추가
    - alert metrics markdown에도 same fields 출력
  - `OperationalChecklistService`
    - `alert_channel_slo.evidence.latest_validation_alert`가 alert metrics summary의 playbook mapping을 그대로 사용
  - 회귀 테스트 추가/보강(`tests/test_alert_metrics.py`, `tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZL-27. portfolio budget/report summary의 deployment language를 operations checklist portfolio evidence에도 직접 반영
- 상태: 완료(신규)
- 구현:
  - `OperationalChecklistService`
    - `portfolio_headroom.evidence`에 `deployment_go_no_go/code/message` 추가
    - source fields도 `/portfolio/budget` top-level deployment language를 포함하도록 확장
  - 회귀 테스트 추가/보강(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZL-28. validation alert payload의 deployment language를 notification formatter summary에도 직접 반영
- 상태: 완료(신규)
- 구현:
  - `NotificationDispatcher._format_message`
    - validation alert 메시지에 `deployment=<go_no_go>/<code>` 또는 `deployment=<go_no_go>` 출력
    - `approval=` one-line summary와 함께 배포 언어를 직접 노출
  - 회귀 테스트 추가/보강(`tests/test_notification_dispatcher.py`, `tests/test_validation_alerts.py`)

### Phase ZL-29. validation alert payload의 playbook mapping을 validation_alert_delivery evidence에도 직접 반영
- 상태: 완료(신규)
- 구현:
  - `OperationalChecklistService._validation_alert_evidence`
    - `approval_playbook_go_no_go/code/action/message`를 top-level evidence 필드로 직접 노출
    - `validation_alert_delivery` checklist item이 alert payload playbook mapping을 재해석 없이 바로 읽도록 고정
  - 회귀 테스트 추가/보강(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZL-30. portfolio budget/report summary의 playbook-style 운영 문구를 직접 반영
- 상태: 완료(신규)
- 구현:
  - `PortfolioBudgetReportService`
    - runtime deployment code를 source-of-truth로 하는 `playbook_go_no_go/code/action/message` 추가
    - `GET /portfolio/budget` top-level payload와 markdown summary가 같은 운영 액션 문구를 직접 노출
  - 회귀 테스트 추가/보강(`tests/test_portfolio_budget_report.py`, `tests/test_api_smoke.py`)

### Phase ZL-31. notification formatter summary에 playbook action까지 직접 반영
- 상태: 완료(신규)
- 구현:
  - `NotificationDispatcher._format_message`
    - validation alert 채널 메시지에 `playbook_action=<approval_playbook_action>` 직접 출력
  - 회귀 테스트 추가/보강(`tests/test_notification_dispatcher.py`, `tests/test_validation_alerts.py`)

### Phase ZL-32. validation alert payload의 playbook mapping을 alert test/manual test 경로에도 같은 수준으로 직접 반영
- 상태: 완료(신규)
- 구현:
  - `StrategyEngine.send_test_alert`
    - `deployment_*`, `approval_playbook_*`를 top-level 반환 payload에 직접 노출
    - manual alert drill 응답이 validation-style playbook mapping을 재해석 없이 반환
  - API 스키마/회귀 테스트 추가(`app/schemas/api.py`, `tests/test_strategy_engine_ops.py`, `tests/test_api_smoke.py`)

### Phase ZL-33. portfolio budget/report summary의 playbook mapping을 operations checklist portfolio evidence에도 직접 반영
- 상태: 완료(신규)
- 구현:
  - `OperationalChecklistService._portfolio_item`
    - `portfolio_headroom.evidence`와 `source.fields`에 `playbook_go_no_go/code/action/message` 직접 반영
  - 회귀 테스트 추가/보강(`tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZL-34. operations checklist top-level summary에도 playbook-style 운영 문구를 직접 반영
- 상태: 완료(신규)
- 구현:
  - `OperationalChecklistService._deployment_language`
    - top-level `deployment_*`와 함께 `playbook_go_no_go/code/action/message` 생성
    - validation approval summary와 operational blocking 상태를 합성한 운영 액션 문구를 직접 노출
  - markdown summary와 API 스키마/회귀 테스트 추가(`app/schemas/api.py`, `tests/test_operational_checklist.py`, `tests/test_api_smoke.py`)

### Phase ZL-35. alert subscribe/manual subscribe 경로에도 deployment/playbook contract를 직접 반영
- 상태: 완료(신규)
- 구현:
  - `POST /alerts/subscribe`
    - 저장된 payload에서 `deployment_*`, `approval_playbook_*`를 top-level 응답으로 직접 반환
    - manual subscribe 경로가 `alerts/test`와 같은 운영 contract를 공유
  - API 스키마/회귀 테스트 추가(`app/schemas/api.py`, `tests/test_api_smoke.py`)

### Phase ZL-36. validation/operations/report top-level contract 최종 정리
- 상태: 완료(신규)
- 구현:
  - `POST /validation/report`
    - top-level `deployment_go_no_go/code/message`, `approval_topline_status/code/message/summary_line`, `playbook_go_no_go/code/action/message`를 직접 반환
    - source of truth는 계속 `validation_report.deployment_approval_summary`
  - `OperationalChecklistService`
    - validation deployment/playbook 해석 시 `validation_payload` top-level contract를 우선 소비
    - `validation_report` evidence도 같은 top-level contract를 직접 노출
  - API 스키마/회귀 테스트 추가(`app/schemas/api.py`, `tests/test_api_smoke.py`, `tests/test_operational_checklist.py`)

### Phase ZL-37. 비검토 후속 backlog 재정리
- 상태: 완료(신규, docs-only)
- 정리 결과:
  - 배포 전 필수 backlog: 없음
  - 배포 후 리팩터 backlog:
    1. alert 경로 전반의 contract 중복 축소 여부 검토
    2. validation/report nested summary와 top-level passthrough 중복 축소 여부 검토
  - optional hold:
    - 첫 라이브 운영 사이클 이전에는 새 feature backlog를 더 열지 않음
- 결정:
  - 현재 남은 backlog는 기능 부족이 아니라 contract dedup/refactor 성격으로 본다
  - 다음 단일 포커스는 `alert 경로 전반의 contract 중복 축소 여부 검토`로 고정한다

### Phase ZL-38. Deployment/Playbook Contract Dedup
- 상태: 완료(신규)
- 구현:
  - `app/services/deployment_contracts.py` 추가
  - `approval_summary_passthrough`, `validation_report_contract`, `validation_alert_contract`, `alert_contract_defaults` 공통 helper 고정
  - alert/validation/report/metrics/checklist/message formatter가 같은 contract helper를 재사용하도록 정리
  - helper 단위 테스트 추가(`tests/test_deployment_contracts.py`)
- 결과:
  - active rollout-blocking backlog: 없음
  - active post-rollout refactor backlog: 없음
  - 남은 항목은 첫 라이브 운영 사이클 이후 contract pruning 재평가(optional hold)만 유지

### Phase ZL-39. 실시간 시그널/체결 lifecycle 알림
- 상태: 완료(신규)
- 구현:
  - `POST /alerts/subscribe`
    - subscription row에 `subscription_active/status/created_at` marker 저장
    - 지원 타입 확장: `near|touch|confirm|entry|tp|sl|partial_exit|closed`
  - `StrategyEngine.refresh_symbol`
    - active signal plan에 대해 `near/touch/confirm` 조건을 평가해 matching subscription으로 자동 fanout
    - `signal_alert_near_atr_multiple`, `signal_alert_cooldown_seconds` 적용
  - `StrategyEngine.tv_webhook`
    - incoming `near/touch/confirm` event를 matching subscription으로 자동 fanout
  - `StrategyEngine.ingest_execution_fill`
    - `ENTRY`, `PARTIAL_EXIT`, `CLOSED` stage를 `entry/partial_exit/tp/sl/closed` subscription alert로 자동 fanout
  - `AlertRepository`
    - matching subscription lookup, emitted alert cooldown lookup 추가
  - 회귀 테스트 추가/보강(`tests/test_signal_alerts.py`, `tests/test_execution_fill_api.py`, `tests/test_api_smoke.py`, `tests/test_notification_dispatcher.py`)

### Phase ZL-40. 후보별 승률 추정식 세분화
- 상태: 완료(신규)
- 구현:
  - `PlanGenerator`
    - `expected_win_prob` 계산에 `family/grade/reaction/entry_model/confluence/regime/friction/near_lp` 약한 보정항 추가
    - 표본 부족 구간일수록 differentiation weight를 더 크게 적용
    - `expected_tp1/2/3_prob`도 같은 보정 신호를 따라 미세 조정
    - `expected_win_prob_base`, `expected_win_prob_adjustment`, `expected_win_prob_components` 저장
  - 회귀 테스트 추가/보강(`tests/test_plan_generator.py`, `tests/test_candidate_expectations.py`, `tests/test_api_smoke.py`)

### Phase ZL-41. Binance 직접 주문 실행 어댑터(완전자동매매 1차)
- 상태: 완료(신규)
- 구현:
  - `BinanceFuturesClient`
    - signed REST helper(`timestamp`, `recvWindow`, HMAC SHA256)
    - `submit_order`, `query_order`, `cancel_order`
    - 기본 모드는 `test order`
    - live submit/cancel은 `binance_trade_live_enabled=true`일 때만 허용
  - `StrategyEngine`
    - normalized order payload(`action/mode/requested_live/live_enabled/test_order/order_id/client_order_id/status/raw`)
    - `plan_id` 기반 default `client_order_id` 생성
  - API
    - `POST /internal/binance/order`
    - `GET /internal/binance/order`
    - `DELETE /internal/binance/order`
  - 설정
    - `binance_api_key`
    - `binance_api_secret`
    - `binance_trade_recv_window`
    - `binance_trade_live_enabled`
  - 회귀 테스트 추가/보강(`tests/test_binance_client.py`, `tests/test_binance_trade_api.py`, 환경독립 alert 회귀 보강)

### Phase ZL-42. 전략 지표 요약/차트 payload
- 상태: 완료(신규)
- 구현:
  - `StrategyIndicatorsService`
    - readable summary payload(`headline`, `readable_lines`, `bias_label`, `momentum_label`, `risk_label`)
    - chart-friendly payload(`price_panel`, `indicator_panel`, `zones`, `plans`, `annotations`)
    - 기존 `ContextSnapshot`, active zones, top plans를 재사용해 지표 드리프트 없이 구성
  - `StrategyEngine`
    - `indicator_summary`
    - `indicator_chart`
  - API
    - `GET /indicators/summary`
    - `GET /indicators/chart`
  - 회귀 테스트 보강(`tests/test_api_smoke.py`)

### Phase ZL-43. 전략 지표 Pine-style payload
- 상태: 완료(신규)
- 구현:
  - `StrategyIndicatorsService`
    - Pine/TradingView bridge용 payload(`overlay`, `panels`, `signals`, `zones`, `plans`)
    - background color token, overlay plot line, zone box, annotation source를 기존 context/zone/plan source-of-truth에서 직접 구성
  - `StrategyEngine`
    - `indicator_pine`
  - API
    - `GET /indicators/pine`
  - 회귀 테스트 보강(`tests/test_api_smoke.py`)

### Phase ZL-44. Binance user-stream / 포지션 동기화 2차
- 상태: 완료(신규)
- 구현:
  - `BinanceFuturesClient`
    - user-stream listen key create/keepalive/close
    - futures user event normalize(`ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`, `executionReport` fallback)
    - `positionRisk` fetch + position row normalize
    - optional live websocket iterator(`websockets` 의존)
  - `StrategyEngine`
    - Binance order ledger / position snapshot 저장소 연결
    - `ingest_binance_user_stream_event`
    - `process_binance_user_stream`
    - `sync_binance_positions`
    - Binance order 상태를 기존 `execution_fills` / position state machine source-of-truth에 연결
  - API
    - `POST /internal/binance/user-stream/listen-key`
    - `PUT /internal/binance/user-stream/listen-key`
    - `DELETE /internal/binance/user-stream/listen-key`
    - `POST /internal/binance/user-stream/process`
    - `POST /internal/binance/user-stream/event`
    - `POST /internal/binance/positions/sync`
    - `GET /internal/binance/positions`
  - 회귀 테스트 보강(`tests/test_binance_client.py`, `tests/test_binance_user_stream_api.py`, `tests/test_binance_user_stream_engine.py`, `tests/test_api_smoke.py`)

### Phase ZL-45. TradingView native mirror Pine script
- 상태: 완료(신규)
- 구현:
  - `scripts/tradingview/trading_engine_v1_mirror.pine`
    - 5m scalp-friendly native TradingView mirror
    - HTF regime, transition/risk state, recent LP/FVG zones, best setup plan guide
    - stale-zone usage를 줄이기 위해 최근 zone/FVG age cap 적용
    - compile/display tuning:
      - confirmed-bar signal gating
      - dashboard position input
      - native TradingView alert conditions(`Long`, `Short`, `Blocked`)
      - risk background / marker toggles
  - API
    - `GET /indicators/pine-script`
  - 문서
    - `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md`

### Phase ZL-46. Family / Session 성과 리포트
- 상태: 완료(신규)
- 구현:
  - `StrategyV2ValidationService`
    - `family_metrics`, `family_summary`
    - `session_metrics`, `session_summary`
    - markdown report에 `Family Breakdown`, `Session Breakdown` 섹션 추가
  - `Validation Report`
    - `strategy_v2_validation_summary.best_ev_family`
    - `strategy_v2_validation_summary.best_ev_session`
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_validation.py`, `tests/test_validation_report.py`)

### Phase ZL-47. 5m zone / 1m execution 스캘프 실험 분기
- 상태: 완료(신규)
- 구현:
  - `StrategyV2ScalpExperimentService`
    - baseline: `15m zone / 5m execution`
    - experiment: `5m zone / 1m execution`
    - top plan EV / win-prob comparison
    - compare-only markdown report 생성
  - API
    - `GET /validation/scalp-experiment`
  - 엔진
    - `recompute_learning()`과 `POST /validation/report`에 `strategy_v2_scalp_experiment` 포함
    - Binance sync 경로가 `limit_1m`를 함께 받을 수 있도록 확장
  - 회귀 테스트 추가/보강(`tests/test_strategy_v2_scalp_experiment.py`, `tests/test_api_smoke.py`)

### Phase ZL-48. 스캘핑 운영 기준 정렬
- 상태: 완료(신규)
- 구현:
  - validation summary와 README/운영 문서에 `family/session` / `scalp experiment` 기준 추가
  - `5m zone / 1m execution`은 현재 compare-only branch로 고정
  - source-of-truth는 계속 baseline server branch(`15m zone / 5m execution`)로 유지
    - README quick usage / copy-paste flow
  - 회귀 테스트 보강(`tests/test_api_smoke.py`)

### Phase ZL-49. Execution Operator Dashboard
- 상태: 완료(신규)
- 구현:
  - `GET /execution/operator-dashboard` 추가
  - `new_entries_allowed`, `blocking_reason_code/message`, `active_locks`, `rollout_policies`, `recent_intents`, `open_orders`, `open_positions`, `recent_reconciliation_summary`, `portfolio_summary`, `alert_summary`, `execution_quality_summary`를 단일 payload로 집계
  - operator 관점의 approval/intent/reconcile/safety 상태를 같은 runtime surface로 정렬
  - 회귀 테스트 추가/보강(`tests/test_execution_operator_dashboard.py`, `tests/test_api_smoke.py`)

### Phase ZL-50. Auto-Trading 운영 문서
- 상태: 완료(신규)
- 구현:
  - `docs/AUTO_TRADING_OPERATING_RUNBOOK.md` 추가
  - `docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md` 추가
  - runbook에 pre-flight, candidate review, preview/approve/intent/submit, reconcile, close-only, kill-switch 절차를 고정
  - go-live checklist에 `SHADOW -> PAPER -> MICRO_LIVE -> LIVE` 승격 조건과 no-go 조건을 고정
  - README/API 목록에 operator dashboard와 운영 문서 링크 반영

### Phase ZL-51. Incident Drill / Failover Rehearsal
- 상태: 완료(신규)
- 구현:
  - `scripts/run_execution_incident_drill.py` 추가
  - `docs/AUTO_TRADING_INCIDENT_DRILL_PLAYBOOK.md` 추가
  - `dashboard`, `reconcile`, `kill_switch`, `close_only`, `rollout_block` 시나리오를 같은 runtime contract로 반복 실행 가능하게 고정
  - `ExecutionReconciliationService`의 naive/aware `submitted_at` 비교 버그를 수정하고 `FILL_EVENT_GAP` 회귀 테스트를 추가
  - README와 체크리스트에 incident drill 실행 절차를 반영

### Phase ZL-46. Server Scalp Hardening
- 상태: 완료(신규)
- 구현:
  - `24h` 초과 zone은 plan 단계에서 hard skip
  - zone freshness에 `created_ts` 기반 recent boost / age penalty 반영
  - 기본 `valid_until`을 `90m` baseline으로 단축하고, entry model / session state에 따라 `30~120m` 범위로 조정
  - preferred London/New York session은 setup score / probability를 소폭 boost
  - dead session / active session lock은 setup score / probability를 소폭 penalty
  - `ZoneEngine`도 `24h` 초과 stale zone을 `expired` 처리
- 회귀 테스트 보강(`tests/test_plan_generator.py`, `tests/test_zone_engine.py`)

## 4. 성능 최적화 정책 (현재 적용)
1. 레짐 분리: `trend`, `range`, `shock` 별로 다른 진입 임계값/가중치 사용
2. 컨플루언스 우선: 유동성/FVG-변위/상위TF 정렬/OB 신선도/트렌드 프록시 가중 합산
3. 하드 차단:
- 고마찰(`friction_hard_gate`) 구간
- 고점프(`jump_hard_gate`) 구간
- 강추세 역방향(비-range 레짐)
4. 자동 비활성화:
- 표본 수가 충분한데 `ev_r`가 임계값 이하이면 셋업 차단
5. Shock 레짐 보수 실행:
- LIMIT 제한, CONFIRM 중심 집행

## 5. 운영 기준
- 기본 전략 버전: `v1`
- 기본 이벤트 백엔드: `memory` (운영 전환 시 `redis`/`kafka`)
- 리스크 상태: `OPEN`, `THROTTLED`, `CLOSED`
- 배포 전 필수: 테스트/리포트/백로그 상태 점검

## 6. 완료 기준 (DoD)
1. 15m Zone lifecycle이 DB에 인과적으로 일관 저장된다.
2. 5m Top N 플랜이 EV/RR/Cost/Confluence 포함으로 노출된다.
3. 리스크 게이트가 비정상 상태에서 신규 진입을 차단한다.
4. 검증 리포트(WF/MC)가 파일로 자동 생성된다.
5. outbox 상태/재처리 API로 운영 가시성을 확보한다.

## 7. 다음 우선순위
1. 없음 (`active backlog` 정리 완료, 운영 전환 helper 포함, optional hold만 유지)

### 최신 안정화 메모
- 최근 회귀 안정화 기준선은 `Iteration #131`이다.
- `ExecutionPlanningService`는 `strategy_mode=RESEARCH`를 rollout/live gate보다 먼저 `APPROVED_SHADOW`로 처리한다.
- auto-trading transition 회귀 테스트는 `_env_file=None` 기준 settings를 사용해 로컬 `.env` drift를 제거했다.
- runtime `strategy_version`에 의존하는 PBO/DSR recompute 회귀는 현재 설정값 기준 fixture version을 직접 따라가도록 정렬했다.
- 최신 전체 테스트 기준선은 `217 passed, 1 skipped`다.

### Model Upgrade 메모
- 현재 메인 전략은 유지하고, 먼저 `signal funnel` 계측으로 후보가 어디서 줄어드는지 수치화한다.
- `/execution/operator-dashboard`는 이제 `signal_funnel`을 반환하며, `runtime_candidates`, `accepted_candidates`, `blocked_candidates`, `blocked_reason_counts`, `submit_decision_counts`, `open_orders`, `open_positions`, `family_pass_rates`, `regime_pass_rates`, `session_pass_rates`를 같은 payload에서 읽을 수 있다.
- `/execution/operator-ui`는 같은 `signal_funnel`을 `신호 퍼널` 섹션과 `Family / Regime / Session 통과율` 테이블로 노출한다.
- `signal_funnel`에는 이제 `blocked_gate_group_counts`, `blocked_gate_groups`, `current_entry_gate_group`, `current_entry_gate_reason`도 포함되며, blocked reason을 `safety / structural / quality / rollout`로 분리해 읽는다.
- 같은 payload에는 이제 `hard_block_summary`, `softening_candidate_summary`, `rollout_block_summary`도 포함되며, operator UI는 이를 `유지해야 하는 hard gate`, `완화 검토 후보`, `운영 정책 차단`으로 직접 요약한다.
- 같은 payload에는 이제 `quality_softening_priorities`, `family_bottlenecks`, `regime_bottlenecks`, `session_bottlenecks`도 포함되며, operator UI는 이를 `완화 우선순위`, `Family 병목 상위`, `Regime 병목 상위`, `Session 병목 상위`로 직접 요약한다.
- 이번 계측 단계에서는 `plan_generator`, `expected_*`, validation gate, rollout policy를 바꾸지 않는다. 목적은 완화가 아니라 병목 위치 측정이다.

## 7.1 잔여 Backlog 분류
- 배포 전 필수: 없음
- 배포 후 리팩터: 없음
- Optional hold: 첫 라이브 운영 사이클 이후 contract pruning 필요성 재평가

### Phase ZL-52. Execution Operator UI
- 구현 범위
  - `GET /execution/operator-ui` 추가
  - 기존 runtime surface(`GET /execution/operator-dashboard`, `POST /operations/checklist`, `POST /validation/report`)를 브라우저에서 한 화면으로 묶는 얇은 HTML operator UI 추가
- 구현 원칙
  - 새 판단/새 source-of-truth를 만들지 않음
  - 기존 runtime payload를 그대로 소비
  - 화면 상단에 `Operator surface only`와 최종 승인 source-of-truth 문구를 고정
- 완료 기준
  - 신규 진입 허용 여부, deployment/playbook 문구, locks, orders, positions, reconcile 요약을 브라우저에서 바로 확인 가능
  - API smoke에 HTML route 회귀 추가

### Phase ZL-53. MICRO_LIVE Preflight Helper
- 상태: 완료(신규)
- 구현:
  - `scripts/run_micro_live_preflight.py` 추가
  - `GET /health/ready`, `GET /execution/operator-dashboard`, `GET /execution/safety-state`, `POST /validation/report`, `POST /operations/checklist`, `GET /alerts/metrics`, `GET /scanner/top`를 한 번에 읽어 `READY_FOR_MICRO_LIVE` vs `NOT_READY`를 판단
  - markdown 리포트 산출: `reports/operations/micro_live_preflight/micro_live_preflight_<SYMBOL>_<UTC>.md`
  - live 전환 판단을 health/operator/safety/validation/checklist/alerts/candidate 기준으로 한 payload로 고정

### Phase ZL-54. Post-Live Pruning Review Helper
- 상태: 완료(신규)
- 구현:
  - `scripts/run_post_live_pruning_review.py` 추가
  - local DB `order_submissions`와 `GET /execution/operator-dashboard`, `POST /validation/report`, `POST /operations/checklist`를 함께 읽어 pruning review reopen 여부를 결정
  - 판단 기준: `requested_live=true` Binance submission 존재, fill-like live activity 존재, reconciliation healthy, validation/checklist not NO_GO
  - markdown 리포트 산출: `reports/operations/pruning_reviews/post_live_pruning_review_<SYMBOL>_<UTC>.md`
  - 실제 첫 live 운영 사이클 전에는 optional hold를 유지하는 보수적 정책을 helper 결과로 명시

### Phase ZL-55. PAPER Lineage Watcher Helper
- 상태: 완료(신규)
- 구현:
  - `scripts/watch_paper_candidate_drill.py` 추가
  - `scripts/run_paper_candidate_drill.py --no-write-report`를 주기적으로 반복 호출해 lineage 대상 family(`trend_continuation`, `sweep_reversal`) 후보가 뜰 때까지 감시
  - 옵션 `--submit-paper`로 첫 eligible candidate에 한해 `live=false` PAPER submit까지 이어지는 보수적 자동화 경로 제공
  - 결과 payload는 `overall_status`, `summary_line`, `attempts`, `final_result`, `next_steps`로 고정
  - markdown 리포트 산출: `reports/operations/paper_candidate_watch/paper_candidate_watch_<UTC>.md`

## 8. vNext 로드맵
- 상세 기획 문서: `docs/UPGRADE_ROADMAP_VNEXT.md`
- 전략 설계 청사진: `docs/STRATEGY_V2_BLUEPRINT.md`
- 추진 순서(권장):
  1. 실체결 연동 + 포지션 상태머신 자동화
  2. 중요도 온라인 캘리브레이션(OB/FVG/유동성/트렌드)
  3. 포트폴리오 리스크 버짓 v2(상관+변동성+레짐)
  4. 실행 품질 리포트 v3(체결 원장/버전 비교/원인 상세 분해)
  5. 알림 채널 복원력 v2(재시도/백오프/서킷브레이커+SLO)

## 9. 전략 설계 기준선
- 최신 전략 설계 기준은 `docs/STRATEGY_V2_BLUEPRINT.md`를 따른다.
- 실전 운영 기본값은 `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`를 따른다.
- signal 분류 계약은 `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`를 따른다.
- transition 정량 규칙은 `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`를 따른다.
- thesis fingerprint 계약은 `docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`를 따른다.
- exit reason/event 계약은 `docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`를 따른다.
- validation/PBO/DSR 프로토콜은 `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`를 따른다.
- 구현 착수 전 체크 항목은 `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`를 따른다.
- 구현 전 단계의 전략 논의는 반드시 본 문서와 청사진 문서에 같이 고정한다.
- 청사진에 없는 전략군/예외/락 규칙은 라이브 규칙으로 취급하지 않는다.
- 전략 v2 기획 상태는 `완료`, 청사진 문구는 현재 런타임 계약 기준으로 동기화됐다.
