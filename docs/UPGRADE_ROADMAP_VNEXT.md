# Trading Engine v1 업그레이드 로드맵 (vNext)

최종 갱신: 2026-03-09
상태: Living roadmap (Epic 1/2/3/4/5 최소 구현 완료, 후속 고도화 예정)

## 1. 목적
- 신호 품질 개선을 넘어, 실체결/포트폴리오/운영 복원력까지 포함한 실전형 성능을 만든다.
- “좋은 신호를 찾는 능력”과 “나쁜 구간/과집중/운영 장애를 피하는 능력”을 동시에 강화한다.

## 2. 현재 기준선
- 전략 엔진(Zone/Context/Plan/Validation/Execution Quality v3)과 기본 운영 체계는 구축 완료.
- 실체결 연동, 중요도 온라인 캘리브레이션, 실행 품질 v3, 알림 채널 관측성 최소 루프까지 반영되었다.
- 전략 v2 첫 코드화 항목으로 `transition_score/state`와 watch/lock 상태 엔진이 반영되었다.
- 전략 v2 두 번째/세 번째 코드화 항목으로 `acceptance/rejection classifier`, `Sweep Reversal` family routing이 반영되었다.
- 전략 v2 네 번째 코드화 항목으로 `Trend Continuation Pullback` family routing과 family-level block이 반영되었다.
- 전략 v2 다섯 번째 코드화 항목으로 `Range Rotation` research-only 분리와 center-block reason이 반영되었다.
- 전략 v2 여섯 번째 코드화 항목으로 family 밖 generic 후보에 대한 `OB-only/FVG-only/trendline-led` block이 반영되었다.
- 전략 v2 일곱 번째 코드화 항목으로 `thesis_fingerprint` shared dedupe가 scanner/execution 공용으로 반영되었다.
- 전략 v2 여덟 번째 코드화 항목으로 family scorecard와 공통 scoring bucket 저장이 반영되었다.
- 전략 v2 아홉 번째 코드화 항목으로 sizing v2(`strategy_sizing`, `recommended_risk_r`)가 plan/scanner/portfolio에 공통 반영되었다.
- 전략 v2 열 번째 코드화 항목으로 mode 분리(`A_ONLY`, `A_PLUS_B`, `RESEARCH`)와 daily cap / total risk cap / shadow-only가 반영되었다.
- 전략 v2 열한 번째 코드화 항목으로 exit engine(`exit_reason`, family time stop, information/time failure, execution/validation report summary)이 반영되었다.
- 전략 v2 열두 번째 코드화 항목으로 daily/session lock(`-2R`, `3연속 손실`, `A급 2연속 실패`, session loss streak, unlock_at)이 반영되었다.
- 전략 v2 열세 번째/열네 번째/열다섯 번째/열여섯 번째 코드화 항목으로 `A-only vs A+B`, `transition/shock lock`, `thesis dedupe`, `cost/slippage stress` 비교 리포트가 validation 경로에 반영되었다.
- 최신 전략 설계 기준선은 `docs/STRATEGY_V2_BLUEPRINT.md`에 별도 고정되어 있다.
- 운영/신호/구현 세부 기준은 `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`, `docs/STRATEGY_V2_ACCEPTANCE_REJECTION_SPEC.md`, `docs/STRATEGY_V2_IMPLEMENTATION_CHECKLIST.md`로 분리되었다.
- 추가 정량 명세는 `docs/STRATEGY_V2_TRANSITION_REGIME_SPEC.md`, `docs/STRATEGY_V2_THESIS_FINGERPRINT_SPEC.md`, `docs/STRATEGY_V2_EXIT_EVENT_SCHEMA.md`, `docs/STRATEGY_V2_VALIDATION_PROTOCOL.md`, `docs/STRATEGY_V2_PBO_DSR_DESIGN.md`에 고정되었다.
- 전략 v2 스무 번째 코드화 항목으로 `PBO / DSR runtime artifact store` 계약(`validation_trial_runs`, `validation_trial_fold_scores`, `validation_pbo_dsr_snapshots`, `strategy_v2_pbo_dsr_artifact_store`)이 반영되었다.
- 전략 v2 스물한 번째 코드화 항목으로 `session_guidance`가 운영 체크리스트에 반영되었고, `dead session`은 non-blocking `WARN`으로 고정되었다.
- 전략 v2 스물두 번째 코드화 항목으로 `strategy_v2_stress_replay_assessment`가 반영되어 stress 근사 유지/대체 우선순위를 validation runtime에서 바로 확인할 수 있게 되었다.
- 전략 v2 스물세 번째 코드화 항목으로 `strategy_v2_pbo_dsr_metrics`가 반영되어 seeded artifact 기준 CSCV/PBO, DSR 계산과 snapshot upsert가 validation runtime에 연결되었다.
- 전략 v2 스물네 번째 코드화 항목으로 `session_guidance`가 `GET /scanner/top`, `GET /portfolio/budget` 후보 row까지 승격되었고, `session_penalty`는 hard block이 아닌 soft penalty로만 반영된다.
- 전략 v2 스물다섯 번째 코드화 항목으로 `strategy_v2_stress_replay_lineage`가 반영되어 full replay 전환용 writer/runtime input lineage readiness, fallback anchor source, gap count를 validation runtime에서 바로 확인할 수 있게 되었다.
- 전략 v2 스물여섯 번째 코드화 항목으로 `strategy_v2_pbo_dsr_trial_writer`가 반영되어 `mode/lock/stress` runtime proxy trial/fold lineage가 validation loop에서 자동 seed되도록 연결되었다.
- 전략 v2 스물일곱 번째 코드화 항목으로 `strategy_v2_stress_replay_runner_contract`가 반영되어 scenario readiness, prototype batching, worker IO contract를 validation runtime에서 바로 확인할 수 있게 되었다.
- 전략 v2 스물여덟 번째 코드화 항목으로 `strategy_v2_stress_replay_lineage_writer`가 반영되어 scenario별 replay input batch artifact(JSON)가 validation runtime에서 바로 materialize되도록 연결되었다.
- 전략 v2 스물아홉 번째 코드화 항목으로 `strategy_v2_pbo_dsr_trial_writer`가 `scoring_thresholds`, `transition_threshold`, `acceptance_rejection_thresholds`, `sizing_clamps` stored-plan threshold proxy family까지 seed하도록 확장되었다.
- 전략 v2 서른 번째 코드화 항목으로 `strategy_v2_stress_replay_output_artifacts`가 반영되어 replay worker output artifact가 있을 경우 `strategy_v2_stress_validation.replay_output_artifacts`와 `replay_output_comparison`으로 바로 비교되도록 연결되었다.
- 전략 v2 서른한 번째 코드화 항목으로 `strategy_v2_stress_replay_prototype_worker`가 반영되어 lineage batch artifact를 실제 replay output artifact/markdown으로 materialize하는 실행 경로가 validation runtime에 연결되었다.
- 전략 v2 서른두 번째 코드화 항목으로 `strategy_v2_pbo_dsr_threshold_runner`가 반영되어 true threshold-sweep lineage가 `selection_rule=true_threshold_sweep_top_in_sample_ev`로 runtime proxy lineage와 분리 seed되고, `selection_rule_counts`/`selected_trial.writer_source`로 combined universe를 해석할 수 있게 되었다.
- 전략 v2 서른세 번째 코드화 항목으로 replay worker output artifact가 있는 scenario를 `strategy_v2_stress_validation.deployment_recommendation`의 replay-backed gate로 승격하도록 반영되었다.
- 전략 v2 서른네 번째 코드화 항목으로 `true_runner_readiness`가 반영되어 prototype runner readiness와 true market replay runner replacement readiness가 분리되었다.
- 전략 v2 서른다섯 번째 코드화 항목으로 `strategy_v2_pbo_dsr_metrics.lineage_audit`가 반영되어 dual-lineage selected-trial source audit와 deployment warning downgrade가 연결되었다.
- 전략 v2 서른여섯 번째 코드화 항목으로 replay-backed stress scenario의 `divergence_status`와 `replay_divergence_warn/fail` gate가 deployment policy에 고정되었다.
- 전략 v2 서른일곱 번째 코드화 항목으로 `strategy_v2_stress_replay_assessment.deployment_recommendation.true_runner_promotion_*`가 반영되어 true-runner readiness와 threshold lineage audit가 같은 배포 action으로 묶였다.
- 전략 v2 서른여덟 번째 코드화 항목으로 `strategy_v2_pbo_dsr_metrics.selection_universe_summary`와 `strategy_v2_pbo_dsr_artifact_store.selection_universe_summary`가 반영되어 combined artifact universe와 full parameter-sweep universe가 분리 기록되었다.
- 전략 v2 서른아홉 번째 코드화 항목으로 DSR bias adjustment가 `full_parameter_sweep_universe`를 우선 사용하도록 재검증되었고, `legacy_combined_benchmark_sharpe` 비교값이 함께 기록된다.
- 전략 v2 마흔 번째 코드화 항목으로 `strategy_v2_stress_replay_output_artifacts.lineage_summary`와 `strategy_v2_stress_replay_assessment.deployment_recommendation.replay_output_lineage_alignment_*`가 반영되어 replay output provenance와 selected-trial source audit가 같은 deployment summary에서 직접 해석된다.
- 전략 v2 마흔한 번째 코드화 항목으로 `strategy_v2_stress_replay_assessment.deployment_recommendation.approval_cross_display`와 `validation_report.deployment_approval_summary`가 반영되어 threshold lineage winner와 replay-derived worst scenario를 같은 approval template에서 직접 교차 표시한다.
- 전략 v2 마흔두 번째 코드화 항목으로 `approval_cross_display.approval_warning_locked/code/message`가 반영되어 runtime proxy selected-trial이 replay-backed downside와 함께 남을 때 approval template 경고 문구가 직접 고정된다.
- 전략 v2 마흔세 번째 코드화 항목으로 `deployment_approval_summary.topline_status/code/message`가 반영되어 replay output lineage alignment warning이 approval template 최상단 승인 문구에 직접 연결된다.
- 전략 v2 마흔네 번째 코드화 항목으로 `deployment_approval_summary.topline_summary_line`이 반영되어 threshold lineage winner / replay-derived worst scenario / true-runner promotion action이 한 줄 승인 문구로 요약된다.
- 전략 v2 마흔다섯 번째 코드화 항목으로 `deployment_approval_summary.playbook_go_no_go/code/action/message`가 반영되어 approval template warning code가 운영 playbook의 `GO / NO_GO / MANUAL_REVIEW` 문구로 직접 매핑된다.
- 전략 v2 마흔여섯 번째 코드화 항목으로 `deployment_approval_summary.topline_message`, `operations/checklist.deployment_*`, `scanner.top[*].deployment_*`가 같은 `GO / NO_GO / MANUAL_REVIEW` 언어로 정렬된다.
- 전략 v2 마흔일곱 번째 코드화 항목으로 `validation_alert.approval_topline_summary_line`가 반영되어 approval template one-line summary가 alert payload/재시도 payload/채널 메시지까지 동일하게 전달된다.
- 전략 v2 마흔여덟 번째 코드화 항목으로 `validation_alert.approval_playbook_go_no_go/code/action/message`가 반영되어 approval template playbook mapping이 alert payload/재시도 payload/outbox payload까지 동일하게 전달된다.
- 전략 v2 마흔아홉 번째 코드화 항목으로 `GET /portfolio/budget` top-level `deployment_go_no_go/code/message`와 portfolio markdown summary가 scanner/operations checklist와 같은 `GO / NO_GO / MANUAL_REVIEW` 언어로 정렬된다.
- 전략 v2 쉰 번째 코드화 항목으로 `validation_alert.deployment_go_no_go/code/message`가 alert payload에 직접 기록되고, `alerts/metrics.latest_validation_alert`, `operations/checklist` evidence도 같은 배포 언어를 직접 노출한다.
- 전략 v2 쉰한 번째 코드화 항목으로 `alerts/metrics.latest_validation_alert.approval_playbook_go_no_go/code/action/message`와 `operations/checklist.alert_channel_slo.evidence.latest_validation_alert`가 alert metrics 경로의 playbook mapping을 직접 노출한다.
- 전략 v2 쉰두 번째 코드화 항목으로 `operations/checklist.portfolio_headroom.evidence.deployment_go_no_go/code/message`가 `/portfolio/budget` top-level 배포 언어를 checklist portfolio evidence에도 직접 반영한다.
- 전략 v2 쉰세 번째 코드화 항목으로 validation alert 채널 메시지가 `deployment=<go_no_go>/<code>`를 직접 포함해 `approval=` one-line summary와 함께 배포 언어를 즉시 노출한다.
- 전략 v2 쉰네 번째 코드화 항목으로 `operations/checklist.validation_alert_delivery.evidence.approval_playbook_go_no_go/code/action/message`가 `validation_alert.approval_playbook_*`를 top-level evidence로 직접 노출한다.
- 전략 v2 쉰다섯 번째 코드화 항목으로 `GET /portfolio/budget` top-level `playbook_go_no_go/code/action/message`와 portfolio markdown summary가 runtime deployment code 기반 운영 액션 문구를 직접 노출한다.
- 전략 v2 쉰여섯 번째 코드화 항목으로 validation alert 채널 메시지가 `playbook_action=<approval_playbook_action>`를 직접 포함해 운영 액션 문구를 즉시 노출한다.
- 전략 v2 쉰일곱 번째 코드화 항목으로 `POST /alerts/test` 응답이 `deployment_*`, `approval_playbook_*`를 top-level로 직접 반환해 manual alert drill 경로가 같은 contract를 사용한다.
- 전략 v2 쉰여덟 번째 코드화 항목으로 `operations/checklist.portfolio_headroom.evidence.playbook_go_no_go/code/action/message`가 `/portfolio/budget` top-level playbook 필드를 직접 노출한다.
- 전략 v2 쉰아홉 번째 코드화 항목으로 `POST /operations/checklist` top-level `playbook_go_no_go/code/action/message`가 validation/report/portfolio와 같은 수준의 운영 액션 문구를 직접 노출한다.
- 전략 v2 예순 번째 코드화 항목으로 `POST /alerts/subscribe` 응답이 `deployment_*`, `approval_playbook_*`를 top-level로 직접 반환해 manual subscribe 경로가 `alerts/test`와 같은 contract를 공유한다.
- 전략 v2 예순한 번째 코드화 항목으로 `POST /validation/report` top-level이 `deployment_*`, `approval_topline_*`, `playbook_*`를 직접 반환하고 `operations/checklist`가 같은 contract를 우선 소비하도록 정리했다.
- 전략 v2 예순두 번째 코드화 항목으로 남은 비검토 backlog를 `배포 전 필수 0건 / 배포 후 리팩터 2건 / optional hold`로 재분류했다.
- 전략 v2 예순세 번째 코드화 항목으로 `app/services/deployment_contracts.py` shared helper가 도입되어 alert/test/subscribe/metrics/checklist/message formatter가 같은 alert contract를 재사용한다.
- 전략 v2 예순네 번째 코드화 항목으로 `validation_report_contract` helper가 도입되어 validation nested summary와 top-level passthrough consumer가 같은 fallback contract를 사용한다.

## 3. 우선순위 (권장 순서)
1. 첫 라이브 운영 사이클 이후 contract pruning 필요성 재평가(optional hold)

## 4. Epic 상세

### Epic 1. 실체결 연동 + 포지션 상태머신 자동화
문제:
- 현재는 plan/outcome 기반 추론이 포함되어 실제 체결 기준 상태 추적 정확도가 제한된다.

목표:
- 거래소 fill 이벤트를 기준으로 `TRIGGERED -> ENTERED -> PARTIAL_EXIT -> CLOSED`를 자동 전이.
- 상태 전이 오차율 < 1%, 중복 전이 0건.

핵심 설계:
- 체결 원장(`execution_fills`) 테이블 추가.
- 주문/체결 이벤트 수집기(REST 백필 + WS user stream) 추가.
- idempotency key 기반 중복 체결 방지.

DoD:
- 동일 체결 이벤트 재주입 시 상태/손익 결과가 불변.
- 상태머신 전이가 리포트/대시보드/API와 일치.

### Epic 2. 중요도 온라인 캘리브레이션
문제:
- OB/FVG/유동성/트렌드 중요도를 고정 가중치로 두면 레짐 변화에 늦게 적응한다.

목표:
- 최근 성과를 반영한 반감기(rolling decay) 가중치 자동 보정.
- “신호 남발” 감소와 EV 안정성 개선.

핵심 설계:
- feature contribution 로그를 저장하고 EWMA 기반 점수 업데이트.
- 가중치 변화율 상한(1회 업데이트당 max delta) 적용.
- 최소 표본 미달 구간에서는 기존 가중치 유지.

DoD:
- 워크포워드 기준 EV 악화 없이 하방(p5) 개선.
- 가중치 변경 이력이 changelog와 100% 동기화.

### Epic 3. 포트폴리오 리스크 버짓 v2
문제:
- 상관도 기반 차단만으로는 변동성 급변/레짐 충격 구간을 충분히 제어하기 어렵다.

목표:
- 심볼별 허용 노출을 `상관 + 변동성 + 레짐`으로 동적으로 조절.
- 동방향 동조화 손실 구간의 손실 폭 축소.

핵심 설계:
- 위험 예산 점수(`risk_budget_score`) 계산.
- 레짐별 총노출 cap 및 섹터/클러스터 cap.
- 스캐너 랭킹과 사이징에 동시 반영.

DoD:
- 충격 구간(shock)에서 총노출 자동 축소 확인.
- 포트폴리오 max drawdown 지표 개선.
- 현재 상태:
  - `GET /portfolio/budget`와 `reports/portfolio/*`로 현재 노출, regime별 headroom, blocked reason을 함께 확인 가능
  - `PortfolioBudgetReportService`가 `current_exposure`, `headroom_by_regime`, `blocked_reason_counts`를 API/Markdown으로 고정

### Epic 4. 실행 품질 리포트 v3
문제:
- 현재 리포트는 원인 분해가 기본 수준이라 라우팅/체결 개선 포인트 추적이 제한된다.

목표:
- 미체결/슬리피지 원인을 체결 원장 기준으로 상세 분해.
- entry model별 체결 효율/비용을 운영 지표화.

핵심 설계:
- 분해 항목 확장: 가격 미도달, 확인 실패, 타임아웃, 오더 거절, 부분체결 후 취소.
- 체결 지연(latency)과 수수료/슬리피지 분리 집계.
- 일/주/버전 비교 리포트 자동 생성.

DoD:
- 리포트가 배포 전 점검 체크리스트에 자동 포함.
- 실행 품질 악화 시 WARN 알림 자동 발행.
- 현재 상태:
  - `execution_fills` 우선 집계와 `zone_outcomes` fallback 적용 완료
  - `by_strategy_version`, `version_comparison`, `unfilled_reason_details` API/Markdown 리포트 반영 완료

### Epic 5. 알림 채널 복원력 v2
문제:
- 채널 장애 시 알림 품질 저하를 정량 추적하는 SLO/에러 예산 관리가 약하다.

목표:
- 채널별 전달 성공률/지연/SLO를 운영 기준으로 관리.
- 장애 시 자동 격리 + 복구 후 자동 재개.

핵심 설계:
- 채널별 서킷브레이커 상태 스냅샷 API.
- 재시도 큐 + 지수 백오프 + 지터.
- dead-letter 경로와 재전송 도구 제공.

DoD:
- 채널 장애 주입 테스트에서 전체 알림 유실률 목표치 이내.
- 채널별 성공률/지연 대시보드 운영.
- 현재 상태:
  - `alert_retry_queue` 기반 재시도 큐/수동 dead-letter requeue/API 반영 완료
  - `alerts/metrics`에 `error_budget`, `retry_queue` 반영 완료

## 5. 공통 운영 원칙
- 전략 변경은 항상 `strategy_version` 단위로 롤아웃한다.
- 단계별 WF/MC/실행품질 리포트 없이는 다음 단계로 진행하지 않는다.
- 기획 항목은 “단건 구현”이 아니라 “테스트 + 문서 + 운영 증빙”까지 완료되어야 닫는다.

## 6. 단계별 추진 계획
1. Epic 1 설계/스키마/이벤트 계약 확정
2. Epic 1 최소 구현 + 회귀 테스트 + 페이퍼 운용 검증
3. Epic 2/3 병행 설계 후, Epic 2 먼저 적용(신호 품질 안정화)
4. Epic 3 적용(포트폴리오 버짓), 이후 Epic 4로 실행 개선 루프 강화
5. Epic 5로 운영 복원력/SLO 고정
6. 현재는 thesis dedupe 공유 적용과 strategy-family score/log 정교화로 진행

## 7. 승인 조건
- 본 문서를 기준으로 각 Epic 세부 ADR/테스트 계획이 생성되면 구현 착수.
