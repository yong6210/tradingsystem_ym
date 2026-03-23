# Trading Engine v1 체크리스트 (Living)

최종 갱신: 2026-03-09
현재 기준선: Iteration #133 (quality softening priority + family/regime/session bottleneck visibility)

## 운영 메모
- active backlog의 source-of-truth는 이제 [AUTO_TRADING_TRANSITION_CHECKLIST.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md)다.
- 앞으로 신규 체크리스트 항목은 한 줄 체크박스가 아니라 `목적 / 구현 방식 / 완료 기준 / 검증`이 포함된 상세 항목으로 관리한다.
- `POST /execution/plans/preview`, `POST /execution/approve-plan`는 현재 실제 execution contract를 반환한다.

## A. 기반 구축
- [x] 프로젝트 스캐폴드(FastAPI/DB/서비스 구조)
- [x] 핵심 도메인 타입/상태머신 정의
- [x] 기본 API 엔드포인트 구성

## B. 전략 엔진
- [x] Zone 엔진(15m) 생성/병합/만료
- [x] Context 엔진(5m/15m) + Kalman F/V/A
- [x] Plan Generator + Entry Router
- [x] 메타 필터(2차 실행 게이트)
- [x] Risk Gate(연속 손실/점프/인프라)
- [x] 신호 남발 방지(Confluence 하드 게이트)
- [x] 레짐 분리(trend/range/shock)
- [x] 동적 가중치(학습 통계 기반)
- [x] 자동 비활성화(음수 EV 셋업)
- [x] 근접 중복 엔트리 dedupe
- [x] 포트폴리오 리스크 오버레이(상관도/동시 노출 제한)
- [x] 포트폴리오 리스크 버짓 v2(상관+변동성+레짐)
- [x] 포지션/포트폴리오 통합 버짓 리포트
- [x] 전략 v2 상태 엔진 1차 코드화(`transition` regime + watch/lock)
- [x] 전략 v2 acceptance/rejection classifier + mixed gate
- [x] 전략 v2 Sweep Reversal 분기 추가(`strategy_family/grade` + family-specific routing)
- [x] 전략 v2 Trend Continuation Pullback 분기 강화(`healthy pullback + protected level hold`)
- [x] 전략 v2 Range Rotation 연구 모드 분리(`research_only` routing + center block)
- [x] 전략 v2 `OB-only/FVG-only/trendline-led` 차단
- [x] 전략 v2 thesis fingerprint / dedupe 공유 적용
- [x] 전략 v2 전략군별 A/B/C scorecard 저장 + trendline bonus-only 명시
- [x] 전략 v2 sizing 함수 v2(`grade/regime/reaction/thesis/execution factor` + `recommended_risk_r`)
- [x] 전략 v2 운영 모드 분리(`A_ONLY/A_PLUS_B/RESEARCH` + daily cap + total risk cap + shadow-only)
- [x] 후보별 승률 추정식 세분화(`expected_win_prob` fallback differentiation + `expected_win_prob_base/adjustment/components`)
- [x] 전략 v2 family별 성과 리포트(`strategy_v2_validation.family_metrics/family_summary`)
- [x] 전략 v2 session별 성과 리포트(`strategy_v2_validation.session_metrics/session_summary`)
- [x] 전략 v2 스캘프 실험 분기(`5m zone / 1m execution`, `GET /validation/scalp-experiment`, compare-only)
- [x] 전략 지표 요약/차트 payload(`GET /indicators/summary`, `GET /indicators/chart`, context/zone/plan 기반 readable + chart-friendly indicator view)
- [x] 전략 지표 Pine-style payload(`GET /indicators/pine`, TradingView/Pine bridge용 overlay/panel/signal/zone snapshot)
- [x] TradingView native mirror Pine script(`GET /indicators/pine-script`, `scripts/tradingview/trading_engine_v1_mirror.pine`, 5m scalp-friendly mirror)
- [x] 서버 스캘핑 강화(`24h` old-zone hard filter, `90m` baseline validity, preferred-session bias, stale-zone expiry)
- [x] 주문 실행 품질 리포트(슬리피지/미체결 원인 분해) 자동화
- [x] 주문 실행 품질 리포트 v2(`execution_fills` 기반 latency/fee/stage coverage)
- [x] 주문 실행 품질 리포트 v3(`strategy_version` 비교 + 미체결 원인 세분화)

## C. 데이터/연동
- [x] Demo 데이터 부트스트랩
- [x] Binance REST 백필(5m/15m)
- [x] Binance WS 상시 수집 루프(엔진 ingest 경로 연결)
- [x] 유니버스 동기화(Binance 24h quoteVolume 기반)
- [x] Binance 직접 주문 실행 어댑터 1차(`POST/GET/DELETE /internal/binance/order`, signed REST, test order 기본, live gate)
- [x] Binance user-stream / 포지션 동기화 2차(`listen-key`, `ORDER_TRADE_UPDATE/ACCOUNT_UPDATE`, position sync, fill state-machine 연결)

## D. 이벤트/운영
- [x] Event Outbox 테이블 + 발행 경로
- [x] 중복/지연/재처리 정책
- [x] outbox 상태 모니터링 API
- [x] 배치 워커(once/loop)
- [x] 워커 병렬 처리(심볼 동시성 제한)
- [x] 운영 알림 채널 연동(telegram/discord/push) 실배선
- [x] 알림 채널 장애 격리(재시도/백오프/채널별 서킷브레이커)
- [x] 알림 채널 메트릭/관측성 확장(채널별 실패율/SLO)
- [x] 알림 채널 복원력 v2 후속(재시도 큐/에러 예산)
- [x] 포지션 상태머신 실집행 연동(ENTRY fill 기반 `ENTERED/PARTIAL_EXIT/CLOSED`)
- [x] 실시간 시그널/체결 lifecycle 알림(`POST /alerts/subscribe`, `near/touch/confirm/entry/tp/sl/partial_exit/closed`, refresh/webhook/fill fanout)
- [x] execution operator telemetry dashboard(`GET /execution/operator-dashboard`, approval/intent/order/position/reconcile/safety 상태 집계)

## E. 학습/검증
- [x] zone_outcomes 기반 요약 메트릭
- [x] 베이지안 스무딩 + `ev_r` 계산
- [x] Walk-forward / Monte Carlo 계산
- [x] 검증 리포트 Markdown 생성
- [x] 피처 중요도(Ablation) 자동 분석
- [x] 중요도 온라인 캘리브레이션(outcome-grounded EWMA + zone-type multiplier + runtime 적용)
- [x] 리포트 FAIL/WARN 자동 알림
- [x] validation API 파라미터 계약 명확화(refresh=false 차단)

## F. 인프라/DB
- [x] Timescale 초기 마이그레이션 SQL
- [x] Timescale 실환경 실행 검증
- [x] Timescale 부하/장기보관 벤치마크(대용량 입력 + 정책 실행 시간 측정)
- [x] 외부 의존성 포함 `/health/ready` 점검

## G. 품질
- [x] 테스트 214개 통과 (+ 실연결 1개 옵트인 skip)
- [x] API 스모크 테스트
- [x] Binance 실연결 통합 테스트(옵트인: `RUN_BINANCE_LIVE=1`)
- [x] 장애 시나리오 테스트(거래소/API/이벤트백엔드)

## H. 문서화
- [x] PLAN/CONTEXT/CHECKLIST/SELF_CHECK Living 문서 유지
- [x] 전략 운영 매뉴얼 문서화
- [x] 전략 v2 청사진 문서화(`docs/STRATEGY_V2_BLUEPRINT.md`)
- [x] 전략 v2 A-only 플레이북 문서화(`docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`)
- [x] acceptance/rejection 세부 스펙 문서화(`docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`)
- [x] transition regime 정량 스펙 문서화(`docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`)
- [x] thesis fingerprint 스펙 문서화(`docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`)
- [x] exit event schema 문서화(`docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`)
- [x] validation/PBO/DSR 프로토콜 문서화(`docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`)
- [x] 전략 v2 구현 체크리스트 문서화(`docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`)
- [x] 전략 v2 청사진-코드 1:1 동기화(`docs/STRATEGY_V2_BLUEPRINT.md` current implementation memo 정리)
- [x] 파라미터 변경 이력(버전별 CHANGELOG) 자동 생성
- [x] 자동매매 운영 runbook 문서화(`docs/AUTO_TRADING_OPERATING_RUNBOOK.md`)
- [x] 자동매매 라이브 전환 체크리스트 문서화(`docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md`)
- [x] incident drill / failover rehearsal 문서화 및 runtime 검증(`docs/AUTO_TRADING_INCIDENT_DRILL_PLAYBOOK.md`, `scripts/run_execution_incident_drill.py`)
- [x] MICRO_LIVE preflight helper(`scripts/run_micro_live_preflight.py`, `reports/operations/micro_live_preflight/*`)
- [x] PAPER lineage drill helper(`scripts/run_paper_candidate_drill.py`, `reports/operations/paper_candidate_drill/*`)
- [x] PAPER lineage watcher helper(`scripts/watch_paper_candidate_drill.py`, `reports/operations/paper_candidate_watch/*`)
- [x] post-live pruning review helper(`scripts/run_post_live_pruning_review.py`, `reports/operations/pruning_reviews/*`)

## J. 전략 v2 기획 완료 기준
- [x] 전략군 정의 완료
- [x] 운영 플레이북 완료
- [x] signal classifier 계약 완료
- [x] transition 정량 규칙 완료
- [x] thesis fingerprint 계약 완료
- [x] exit reason schema 완료
- [x] validation protocol(PBO/DSR 포함) 완료
- [x] 구현 체크리스트 완료

## I. vNext 진행 현황
- [x] vNext 업그레이드 로드맵 문서화(`docs/UPGRADE_ROADMAP_VNEXT.md`)
- [x] Epic 1 최소 구현: 실체결 연동 + 포지션 상태머신 자동화
- [x] Epic 2 최소 구현: 중요도 온라인 캘리브레이션
- [x] Epic 3 최소 설계/검증 루프: 포트폴리오 리스크 버짓 v2
- [x] Epic 3 후속: 포지션/포트폴리오 통합 버짓 리포트
- [x] Epic 4 최소 구현: 실행 품질 리포트 v2
- [x] Epic 5 최소 구현: 알림 채널 복원력 v2
- [x] Epic 4 후속: 실행 품질 리포트 v3(버전 비교/원인 세분화)
- [x] Epic 5 후속: 재시도 큐/에러 예산/dead-letter
- [x] 전략 v2 첫 코드화: 상태 엔진(`transition_score/state` + watch/lock)
- [x] 전략 v2 두 번째 코드화: acceptance/rejection classifier + mixed no-trade
- [x] 전략 v2 세 번째 코드화: Sweep Reversal 분기(`strategy_family/grade` + family routing)
- [x] 전략 v2 네 번째 코드화: Trend Continuation Pullback 분기(`healthy pullback + protected level hold`)
- [x] 전략 v2 다섯 번째 코드화: Range Rotation 연구 모드 분리(`research_only` + range center block)
- [x] 전략 v2 여섯 번째 코드화: `OB-only/FVG-only/trendline-led` generic block
- [x] 전략 v2 일곱 번째 코드화: thesis fingerprint / dedupe 공유 적용
- [x] 전략 v2 여덟 번째 코드화: 전략군별 scorecard 저장(`Location/Liquidity/Reaction/Invalidation/Session`)
- [x] 전략 v2 아홉 번째 코드화: sizing 함수 v2(`strategy_sizing` + `recommended_risk_r`)
- [x] 전략 v2 열 번째 코드화: 운영 모드 분리(`strategy_mode`, daily cap, total risk cap, shadow-only)
- [x] 전략 v2 열한 번째 코드화: exit engine 연동(`exit_reason`, family time stop, information/time failure, validation/execution report 반영)
- [x] 전략 v2 열두 번째 코드화: daily/session lock(`-2R`, `3연속 손실`, `A급 2연속 실패`, 세션 손실/연속손실, unlock_at`)
- [x] 전략 v2 열세 번째 코드화: validation 비교 리포트(`A_ONLY` vs `A_PLUS_B`, `strategy_v2_validation` 템플릿)
- [x] 전략 v2 열네 번째 코드화: transition/shock lock 적용 전후 비교(`strategy_v2_lock_validation` 템플릿)
- [x] 전략 v2 열다섯 번째 코드화: thesis dedupe 적용 전후 drawdown 비교(`strategy_v2_thesis_validation` 템플릿)
- [x] 전략 v2 열여섯 번째 코드화: cost `x1.5` / slippage `x2` stress report(`strategy_v2_stress_validation` 템플릿)
- [x] 전략 v2 열일곱 번째 코드화: PBO / DSR 검증 설계 payload(`strategy_v2_pbo_dsr_design`, design-ready / not computed)
- [x] 전략 v2 열여덟 번째 코드화: 실전 운영 체크리스트 집계(`operations/checklist`, health/validation/alerts/outbox/risk/portfolio 연결)
- [x] 전략 v2 열아홉 번째 코드화: 추가 stress 축(`latency +1 bar`, `partial fills only`, `shock concentration`)을 `strategy_v2_stress_validation`에 통합
- [x] 전략 v2 스무 번째 코드화: PBO / DSR runtime artifact store contract(`validation_trial_runs/fold_scores/snapshots`, `strategy_v2_pbo_dsr_artifact_store`, `/validation/pbo-dsr/artifact-store`)
- [x] 전략 v2 스물한 번째 코드화: 운영 체크리스트 session/dead-session guidance(`session_guidance`, preferred window/dead session warning)
- [x] 전략 v2 스물두 번째 코드화: stress full-replay replacement assessment(`strategy_v2_stress_replay_assessment`, `/validation/stress-replay-assessment`)
- [x] 전략 v2 스물세 번째 코드화: PBO / DSR metric 계산 루프(`strategy_v2_pbo_dsr_metrics`, `/validation/pbo-dsr`, snapshot upsert)
- [x] 전략 v2 스물네 번째 코드화: session/dead-session guidance 후보 레벨 승격(`session_guidance`, `session_penalty`, scanner/portfolio soft penalty)
- [x] 전략 v2 스물다섯 번째 코드화: stress replay writer/runtime lineage 입력 계약(`strategy_v2_stress_replay_lineage`, `/validation/stress-replay-lineage`, fill/candle coverage threshold + fallback anchor source)
- [x] 전략 v2 스물여섯 번째 코드화: PBO / DSR trial/fold writer 실전 validation 루프 연결(`strategy_v2_pbo_dsr_trial_writer`, `/validation/pbo-dsr/trial-writer`, runtime proxy trial/fold seed + recompute_learning 연결)
- [x] 전략 v2 스물일곱 번째 코드화: stress full replay 최소 runner/worker 계약(`strategy_v2_stress_replay_runner_contract`, `/validation/stress-replay-runner-contract`, scenario readiness + batching + worker IO contract)
- [x] 전략 v2 스물여덟 번째 코드화: full replay writer/runtime lineage와 stress scenario lineage의 lineage writer 연결(`strategy_v2_stress_replay_lineage_writer`, `/validation/stress-replay-lineage-writer`, per-scenario batch artifact JSON write)
- [x] 전략 v2 스물아홉 번째 코드화: threshold-sweep family를 runtime proxy writer 위에 확장(`strategy_v2_pbo_dsr_trial_writer`, `scoring_thresholds/transition_threshold/acceptance_rejection_thresholds/sizing_clamps`, `threshold_parameter_families_present`, `candidate_trials_by_family`)
- [x] 전략 v2 서른 번째 코드화: replay worker output artifact를 validation stress 비교 payload에 연결(`strategy_v2_stress_replay_output_artifacts`, `/validation/stress-replay-output-artifacts`, `strategy_v2_stress_validation.replay_output_artifacts`)
- [x] 전략 v2 서른한 번째 코드화: stress full replay prototype worker 실행 경로 연결(`strategy_v2_stress_replay_prototype_worker`, `POST /validation/stress-replay-worker/prototype`, lineage batch -> output artifact -> validation/report 연결)
- [x] 전략 v2 서른두 번째 코드화: true threshold-sweep runner를 runtime proxy writer와 분리된 lineage로 연결(`strategy_v2_pbo_dsr_threshold_runner`, `/validation/pbo-dsr/threshold-runner`, `selection_rule_counts`, selected-trial writer source, dual-lineage artifact/design/report 반영)
- [x] 전략 v2 서른세 번째 코드화: replay worker output artifact를 deployment recommendation gate에 반영(`strategy_v2_stress_validation.deployment_recommendation`, `worst_scenario_source`, `replay_gate_applied`, replay-backed scenario status 승격)
- [x] 전략 v2 서른네 번째 코드화: prototype replay worker -> true market replay runner readiness gate 세분화(`true_runner_readiness`, stronger lineage thresholds, critical scenario replay-output coverage, runner/assessment/report 반영)
- [x] 전략 v2 서른다섯 번째 코드화: proxy writer vs true threshold runner lineage audit를 deployment gate에 반영(`strategy_v2_pbo_dsr_metrics.lineage_audit`, `warn_lineage_audit`, selected-trial source audit, validation/report summary 반영)
- [x] 전략 v2 서른여섯 번째 코드화: replay-derived stress divergence threshold를 deployment policy로 고정(`stress_replay_divergence_*`, divergence_status, replay_divergence_fail/warn, validation/report summary 반영)
- [x] 전략 v2 서른일곱 번째 코드화: true market replay runner 실행 lineage와 threshold lineage를 배포 판정에 함께 연결(`strategy_v2_stress_replay_assessment.deployment_recommendation.true_runner_promotion_*`, true-runner readiness + PBO/DSR lineage audit + selected-trial source 결합)
- [x] 전략 v2 서른여덟 번째 코드화: selection-universe count를 full parameter-sweep universe 기준으로 분리 기록(`selection_universe_summary`, combined artifact vs true threshold universe 분리, snapshot/report/API 반영)
- [x] 전략 v2 서른아홉 번째 코드화: best-trial Sharpe bias adjustment를 threshold-sweep universe 기준으로 재검증(`selection_universe_basis=full_parameter_sweep_universe` 우선, legacy combined benchmark 비교, snapshot/report/API 반영)
- [x] 전략 v2 마흔 번째 코드화: true market replay runner output lineage를 selected trial source audit와 deployment summary에 더 직접 결합(`replay_output_lineage_alignment_*`, output lineage summary, promotion reason 직접 결합)
- [x] 전략 v2 마흔한 번째 코드화: threshold lineage winner와 replay-derived worst scenario를 deployment approval 템플릿에서 직접 교차 표시(`validation_report.deployment_approval_summary`, `approval_cross_display`, threshold winner/source + replay worst scenario/status 직접 표기)
- [x] 전략 v2 마흔두 번째 코드화: proxy lineage selected-trial이 replay-backed deployment summary에 남을 때 경고 문구를 approval template에 직접 고정(`approval_warning_locked/code/message`, runtime proxy winner warning 고정)
- [x] 전략 v2 마흔세 번째 코드화: replay output lineage alignment warning을 deployment approval 템플릿의 top-level 승인 문구와 직접 연결(`deployment_approval_summary.topline_*`, alignment warning -> top-level message 직접 연결)
- [x] 전략 v2 마흔네 번째 코드화: threshold lineage winner / replay-derived worst scenario / true-runner promotion action을 최상단 승인 문구에서 한 줄로 요약(`deployment_approval_summary.topline_summary_line`, one-line approval summary)
- [x] 전략 v2 마흔다섯 번째 코드화: approval template warning code를 운영 playbook의 go/no-go 문구와 1:1 매핑(`playbook_go_no_go/code/action/message`, approval template -> 운영 문구 직접 매핑)
- [x] 전략 v2 마흔여섯 번째 코드화: approval template top-level 문구를 scanner/ops checklist 배포 판단과 공통 언어로 정렬(`topline_message`, `scanner.deployment_*`, `operations/checklist.deployment_*`, GO/NO_GO/MANUAL_REVIEW 공통 언어)
- [x] 전략 v2 마흔일곱 번째 코드화: approval template one-line summary를 validation alert payload에도 동일하게 반영(`validation_alert.approval_topline_summary_line`, notification message `approval=...`, alert payload 저장/재시도 동일 계약)
- [x] 전략 v2 마흔여덟 번째 코드화: approval template playbook mapping을 validation alert payload에도 동일하게 반영(`validation_alert.approval_playbook_*`, alert 저장 payload/재시도 payload/outbox payload가 `deployment_approval_summary.playbook_*`와 동일 계약 공유)
- [x] 전략 v2 마흔아홉 번째 코드화: approval template deployment language를 portfolio budget/report 요약에도 직접 반영(`GET /portfolio/budget` top-level `deployment_go_no_go/code/message`, portfolio markdown summary 동일 언어)
- [x] 전략 v2 쉰 번째 코드화: validation alert payload의 deployment language를 alert metrics/ops checklist evidence에도 직접 반영(`validation_alert.deployment_*`, `alerts/metrics.latest_validation_alert`, `validation_alert_delivery.evidence`, `alert_channel_slo.evidence`)
- [x] 전략 v2 쉰한 번째 코드화: validation alert payload의 playbook mapping을 alert metrics evidence에도 직접 반영(`alerts/metrics.latest_validation_alert.approval_playbook_*`, ops checklist `alert_channel_slo.evidence.latest_validation_alert` 동일 계약)
- [x] 전략 v2 쉰두 번째 코드화: portfolio budget/report summary의 deployment language를 operations checklist portfolio evidence에도 직접 반영(`portfolio_headroom.evidence.deployment_*`, `/portfolio/budget` top-level 배포 언어를 checklist evidence까지 직접 노출)
- [x] 전략 v2 쉰세 번째 코드화: validation alert payload의 deployment language를 notification formatter summary에도 직접 반영(`notification message deployment=GO/NO_GO/MANUAL_REVIEW/code`, alert 채널 메시지에서 배포 언어 직접 노출)
- [x] 전략 v2 쉰네 번째 코드화: validation alert payload의 playbook mapping을 validation_alert_delivery evidence에도 직접 반영(`validation_alert_delivery.evidence.approval_playbook_*`, validation alert delivery checklist evidence가 alert payload playbook mapping을 top-level로 직접 노출)
- [x] 전략 v2 쉰다섯 번째 코드화: portfolio budget/report summary의 playbook-style 운영 문구를 직접 반영(`GET /portfolio/budget` top-level `playbook_go_no_go/code/action/message`, portfolio markdown summary에 운영 액션 문구 직접 노출)
- [x] 전략 v2 쉰여섯 번째 코드화: notification formatter summary에 playbook action까지 직접 반영(`notification message playbook_action=...`, validation alert 채널 메시지가 운영 액션 문구를 직접 노출)
- [x] 전략 v2 쉰일곱 번째 코드화: validation alert payload의 playbook mapping을 alert test/manual test 경로에도 같은 수준으로 직접 반영(`POST /alerts/test` top-level `approval_playbook_*`, manual alert drill 응답이 playbook mapping을 직접 반환)
- [x] 전략 v2 쉰여덟 번째 코드화: portfolio budget/report summary의 playbook mapping을 operations checklist portfolio evidence에도 직접 반영(`portfolio_headroom.evidence.playbook_*`, checklist portfolio evidence가 `/portfolio/budget` playbook 문구를 직접 노출)
- [x] 전략 v2 쉰아홉 번째 코드화: operations checklist top-level summary에도 playbook-style 운영 문구를 직접 반영(`POST /operations/checklist` top-level `playbook_go_no_go/code/action/message`, operational checklist summary가 validation/report/portfolio와 같은 운영 액션 문구를 직접 노출)
- [x] 전략 v2 예순 번째 코드화: alert subscribe/manual subscribe 경로에도 deployment/playbook contract를 직접 반영(`POST /alerts/subscribe` top-level `deployment_*`, `approval_playbook_*`, subscribe 응답이 manual drill/test와 같은 운영 contract를 직접 반환)
- [x] 전략 v2 예순한 번째 코드화: validation/operations/report top-level contract 최종 정리(`POST /validation/report` top-level `deployment_*`, `approval_topline_*`, `playbook_*`, `operations/checklist`가 같은 top-level contract를 우선 소비)
- [x] 전략 v2 예순두 번째 코드화: 비검토 후속 backlog 재정리(배포 전 필수 `0건`, 배포 후 리팩터 `2건`, optional hold 정책 고정)
- [x] 전략 v2 예순세 번째 코드화: alert 경로 전반의 contract 중복 축소(`app/services/deployment_contracts.py`, alert/test/subscribe/metrics/checklist/message formatter 공통 helper 적용)
- [x] 전략 v2 예순네 번째 코드화: validation/report nested summary와 top-level passthrough 중복 축소(`validation_report_contract`, top-level/nested fallback contract 단일화, helper 단위 테스트 추가)
- [x] signal funnel 계측 추가(`runtime candidate -> blocked reason -> recent intent -> open order/open position`, `/execution/operator-dashboard.signal_funnel`)
- [x] signal funnel operator UI 노출(`신호 퍼널`, `Family/Regime/Session 통과율`, `/execution/operator-ui`)
- [x] signal funnel gate-group 분류(`safety / structural / quality / rollout`, `/execution/operator-dashboard.signal_funnel.blocked_gate_group_counts`, operator UI `게이트 유형별 차단`)
- [x] hard block vs softening summary 노출(`hard_block_summary`, `softening_candidate_summary`, `rollout_block_summary`, operator UI `유지해야 하는 hard gate / 완화 검토 후보`)
- [x] quality softening priority 노출(`quality_softening_priorities`, operator UI `완화 우선순위`)
- [x] family/regime/session bottleneck 노출(`family_bottlenecks`, `regime_bottlenecks`, `session_bottlenecks`, operator UI `Family/Regime/Session 병목 상위`)

---
현재 다음 작업(상세 체크리스트 기준): `없음 (1~12 execution transition phase active backlog 완료, 운영 전환 helper와 signal funnel softening priority/bottleneck 계측 포함)`

진행 기준:
- `Pine-Server Contract Alignment Phase 1`, `Auto Trading Phase 1A`, `Auto Trading Phase 1B`, `Auto Trading Phase 1C`, `Auto Trading Phase 1D`, `Auto Trading Phase 1E` 완료
- `Phase 1D` 보강: `order_intents`가 top-level approval snapshot을 반환하고, duplicate thesis는 execution-layer open intent/submission 기준을 우선 사용
- `Auto Trading Phase 2A`, `2B`, `3A`, `3B`, `4A`, `4B`도 현재 체크리스트 기준 완료
- active backlog의 상세 상태와 다음 순서는 [AUTO_TRADING_TRANSITION_CHECKLIST.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md)만 갱신한다.

상세 정의:
- [ ] [AUTO_TRADING_TRANSITION_CHECKLIST.md](/Users/yumin/Documents/trading/docs/AUTO_TRADING_TRANSITION_CHECKLIST.md) 기준으로 순차 진행

Optional hold:
- 첫 라이브 운영 사이클 이후 contract pruning 필요성 재평가
