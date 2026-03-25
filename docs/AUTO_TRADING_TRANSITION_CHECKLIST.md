# Trading Engine v1 자동매매 전환 상세 체크리스트 (Living)

최종 갱신: 2026-03-25
현재 기준선: Iteration #133 (quality softening priority + family/regime/session bottleneck visibility)

## 운영 규칙
- 이 문서는 자동매매 전환과 Pine-Server contract 정렬의 active backlog source-of-truth다.
- 앞으로 신규 항목은 한 줄 체크박스가 아니라 아래 4가지를 반드시 포함한다: `목적`, `구현 방식`, `완료 기준`, `검증`.
- 기존 `docs/CHECKLIST.md`는 상위 진행 현황과 기준선만 유지하고, 실제 실행 순서는 이 문서를 따른다.
- 이번 체크리스트의 기본 원칙은 `기존 전략 판단 계약을 깨지 않고`, `실주문 가능 schema/approval/intent/reconciliation/safety`를 순차적으로 붙이는 것이다.
- 권장 디렉토리 구조는 장기 목표로 유지하되, 초기 PR은 현재 리포 구조(`app/api/routes.py`, `app/db/*`, `app/schemas/api.py`, `app/services/*`)에 additive 방식으로 반영한다.

## 구조 원칙
- 장기 목표 구조:
  - `app/services/execution/*`
  - `app/exchange/*`
  - `app/models/schema/execution_*`
  - `app/repositories/*`
  - `app/api/routes/execution*.py`
- 초기 구현 원칙:
  - 전면 리오거나이즈 금지
  - 기존 `plans/scanner/validation/deployment/playbook` contract 재사용
  - `approval`과 `submit` 분리
  - `thesis dedupe`, `operating_lock`, `portfolio gate`, `deployment_go_no_go`를 execution layer 입력으로 재사용

## 1. Pine-Server Contract Alignment Phase 1
- [x] `ScannerService`에 top assessed candidate helper 추가
- 목적: `/indicators/*`가 accepted-only 후보가 아니라 `accepted 또는 blocked`를 포함한 top assessed candidate를 기반으로 운영 질문 3개(`Can I trade this now?`, `Which family is this?`, `Why is it allowed or blocked?`)에 답하게 만든다.
- 구현 방식: `app/services/scanner.py`에 `_plan_to_item`, runtime deployment language, `PortfolioRiskOverlayService.assess_rows(...)`를 재사용하는 public helper를 추가한다. accepted row가 없더라도 block reason이 있는 top assessed row를 반환하도록 고정한다.
- 완료 기준: indicator layer가 `NO_CANDIDATE`, `GO`, `MANUAL_REVIEW`, `NO_GO`를 top assessed candidate 기준으로 일관되게 계산한다.
- 검증: helper 단위 테스트에서 `accepted / blocked / none` 세 경우를 각각 검증한다.

- [x] `/indicators/summary`, `/indicators/chart`, `/indicators/pine`에 additive `operator_summary` 추가
- 목적: indicator surface에서 runtime/portfolio truth를 직접 읽게 한다.
- 구현 방식: `app/services/strategy_indicators.py`, `app/schemas/api.py`, `app/api/routes.py`를 확장해서 아래 고정 필드를 가진 `operator_summary`를 추가한다.
- 구현 방식: 필드 목록은 `trade_now_status`, `can_trade_now`, `active_family`, `family_reason`, `why_now`, `why_allowed_or_blocked`, `top_plan_id`, `deployment_go_no_go`, `deployment_code`, `deployment_message`, `strategy_mode`, `risk_reason`, `operating_lock`, `session_guidance`, `block_reason`, `block_reason_message`, `thesis_cluster_id`, `thesis_primary_symbol`, `authority_source`다.
- 구현 방식: `trade_now_status`는 `NO_CANDIDATE`, `GO`, `MANUAL_REVIEW`, `NO_GO`만 허용하고, `can_trade_now`는 `trade_now_status == "GO"`일 때만 true다.
- 구현 방식: `why_allowed_or_blocked` 우선순위는 `block_reason_message -> deployment_message -> "No active candidate for this symbol."`로 고정한다.
- 구현 방식: `authority_source`는 이번 phase에서 항상 `scanner_runtime_portfolio_gate`다.
- 완료 기준: `/indicators/*` 응답만 봐도 runtime/portfolio truth 기준으로 지금 거래 가능 여부와 사유가 즉시 읽힌다.
- 검증: API smoke에서 세 endpoint 모두 `operator_summary` 존재와 필드 일관성을 검증한다.

- [x] indicator plan row를 operator-friendly 하게 확장
- 목적: 기존 numeric plan contract를 유지하면서도 운영자가 바로 읽는 문장과 block context를 plan row에 추가한다.
- 구현 방식: `IndicatorPlanOut`에 `entry_condition`, `strategy_family_reason`, `why_now`, `strategy_scorecard_buckets`, `strategy_scorecard_raw_components`, `operator_status`, `block_reason`, `block_reason_message`를 additive로 추가한다.
- 구현 방식: `operator_status`는 `accepted | blocked | none`만 사용한다.
- 구현 방식: 기존 `expected_*` numeric field는 이름을 바꾸거나 제거하지 않는다.
- 완료 기준: indicator plan row가 `expected_*` 기계 계약과 `operator-friendly` 설명을 동시에 제공한다.
- 검증: API smoke에서 새 additive field 존재와 기존 `expected_*` field 보존을 함께 검증한다.

- [x] `why_now` human-readable mapping helper 추가
- 목적: raw reason code를 그대로 노출하지 않고, Pine/dashboard/operator summary에서 사람이 읽을 문장으로 정렬한다.
- 구현 방식: 새 helper에서 아래 고정 매핑을 우선 적용한다.
- 구현 방식: `sweep_reversal_limit -> extreme location + rejection + clean limit`
- 구현 방식: `sweep_reversal_confirm_only -> extreme location + rejection + confirmation required`
- 구현 방식: `sweep_reversal_sweep_confirm -> extreme location + sweep rejection + confirm break`
- 구현 방식: `trend_continuation_limit -> trend regime + pullback held + clean continuation`
- 구현 방식: `trend_continuation_confirm_only -> trend regime + pullback + confirmation required`
- 구현 방식: `range_rotation_research_only -> range regime + reversal signal + research-only`
- 구현 방식: 나머지는 snake_case를 공백 기반 humanize fallback으로 변환한다.
- 완료 기준: indicator와 Pine에서 raw snake_case reason을 직접 읽지 않아도 된다.
- 검증: 단위 테스트에서 fixed mapping과 fallback mapping을 모두 검증한다.

- [x] Pine mirror wording/설명 정렬
- 목적: 차트 surface가 authority로 오해되지 않게 하고, mirror semantics를 명확히 드러낸다.
- 구현 방식: `scripts/tradingview/trading_engine_v1_mirror.pine`에서 display wording만 바꾼다.
- 구현 방식: `p(win) -> Est. win`, `EV -> Est. EV`, `Best setup -> Chart-side best setup`, `Plan entry -> Mirror entry`, `Plan stop -> Mirror stop`.
- 구현 방식: entry/sl/tp 산식은 이번 phase에서 유지한다. entry semantics 안내만 추가한다.
- 구현 방식: `LIMIT -> limit on touch`, `CONFIRM -> touch then confirm`, `SWEEP_CONFIRM -> sweep then confirm`.
- 구현 방식: dashboard/label에 `Family`, `Why now`, `Blocked reason`, `Score breakdown`, `Authority: mirror only, check scanner/ops`를 추가한다.
- 완료 기준: 차트만 봐도 mirror임이 명확하고, server approval과 혼동되지 않는다.
- 검증: Pine script string 회귀 테스트에서 새 wording 존재와 authoritative wording 제거를 확인한다.

- [x] 문서 재정렬
- 목적: 운영자가 차트와 서버 판단의 위계를 혼동하지 않게 한다.
- 구현 방식: `README.md`, `docs/TRADINGVIEW_PINE_MIRROR_GUIDE.md`에 아래 문구를 전면 배치한다.
- 구현 방식: `chart score != deployment approval`
- 구현 방식: `chart plan != live order instruction`
- 구현 방식: `/indicators/* operator_summary = runtime/portfolio truth summary`
- 구현 방식: 최종 rollout approval은 `POST /validation/report`와 `POST /operations/checklist`가 담당한다고 명시한다.
- 완료 기준: 문서만 읽어도 mirror/authority 경계가 명확하다.
- 검증: 문서 링크와 wording이 Pine 및 API 응답 계약과 일치하는지 수동 검수한다.

## 2. Auto Trading Phase 1A — Enum / Config / Contract Scaffold
- [x] 실행 계층 enum 추가
- 목적: strategy 판단과 execution 판단을 분리할 최소 공통 타입을 고정한다.
- 구현 방식: `app/core/enums.py`에 `ExecutionMode`, `ApprovalState`, `SubmitDecision`, `OrderLifecycleState`, `LockScopeType`, `LockSeverity`, `ReconciliationSeverity`를 additive로 추가한다.
- 구현 방식: 기존 `StrategyMode`, `EntryModel`, `PlanState`, `ExecutionFillStage`는 그대로 재사용한다.
- 완료 기준: execution layer가 새 enum을 쓰되 기존 전략 엔진 enum과 충돌하지 않는다.
- 검증: enum parse/unit test와 API schema import smoke를 추가한다.

- [x] 자동매매 설정 추가
- 목적: live gate와 rollout 범위를 설정으로 통제한다.
- 구현 방식: `app/core/config.py`에 `AUTO_TRADING_ENABLED`, `AUTO_TRADING_EXECUTION_MODE`, `AUTO_TRADING_ALLOWED_SYMBOLS`, `AUTO_TRADING_ALLOWED_FAMILIES`, `AUTO_TRADING_CLOSE_ONLY`, `AUTO_TRADING_REQUIRE_VALIDATION_GO`, `AUTO_TRADING_NOTIONAL_PER_R`, `AUTO_TRADING_MAX_SLIPPAGE_BPS`를 추가한다.
- 완료 기준: Phase 1 서비스가 설정만으로 shadow/manual/auto 범위를 통제할 수 있다.
- 검증: settings load test와 기본값 회귀를 추가한다.

## 3. Auto Trading Phase 1B — Executable Plan Preview
- [x] `ExecutablePlan` Pydantic schema 추가
- 목적: 사람이 읽는 `plans/top` payload와 실주문 가능한 execution plan contract를 분리한다.
- 구현 방식: 현재 리포 구조를 존중해서 우선 `app/schemas/api.py` 또는 별도 additive schema 파일에 `TargetLeg`, `ExpectedSummary`, `ContextSnapshot`, `ExecutablePlan`을 추가한다.
- 구현 방식: 최소 필드는 `plan_id`, `symbol`, `tf`, `strategy_version`, `strategy_family`, `strategy_mode`, `thesis_fingerprint`, `direction`, `setup_grade`, `setup_score`, `entry_model`, `entry_type`, `entry_trigger_price`, `entry_limit_price`, `stop_price`, `tp_targets`, `recommended_risk_r`, `max_position_notional`, `valid_from`, `valid_until`, `expected_summary`, `context_snapshot`이다.
- 완료 기준: 기존 `Plan`을 실주문 preview용으로 변환한 구조화 contract가 고정된다.
- 검증: schema serialize/deserialize unit test를 추가한다.

- [x] `ExecutablePlanBuilder` 또는 동등 서비스 추가
- 목적: 기존 `Plan + validity + scanner/runtime gate`를 execution-safe preview로 변환한다.
- 구현 방식: `app/services/execution/` 하위 또는 현재 `app/services/execution_approval.py`를 정리해 preview builder로 분리한다.
- 구현 방식: `entry_model -> entry_type` 매핑은 Phase 1에서 단순 고정한다.
- 구현 방식: `LIMIT -> limit`, `CONFIRM -> stop_market`, `SWEEP_CONFIRM -> stop_market`.
- 구현 방식: `expected_summary`와 `context_snapshot`은 기존 runtime truth를 재사용하고, 새 판단을 만들지 않는다.
- 완료 기준: `plans/top`와는 별개로 preview 가능한 executable plan이 항상 생성된다.
- 검증: `LIMIT/CONFIRM/SWEEP_CONFIRM`별 mapping 테스트를 추가한다.

- [x] `POST /execution/plans/preview` 추가
- 목적: operator/debugger/QA가 특정 plan을 실주문 schema로 미리 볼 수 있게 한다.
- 구현 방식: 입력은 우선 `plan_id` 기준으로 단순화한다. 필요하면 `symbol/tf`는 후속으로 추가한다.
- 완료 기준: 특정 `plan_id`에 대해 실제 `ExecutablePlan` 응답이 반환된다.
- 검증: API smoke에서 정상 plan, 없는 plan, 만료 plan 경로를 검증한다.

## 4. Auto Trading Phase 1C — Approval Layer
- [x] `ExecutionApproval` schema 추가
- 목적: 자동승인/수동승인/shadow/block를 기존 deployment/playbook 언어와 함께 기록한다.
- 구현 방식: `ApprovalReason`, `ExecutionApproval` schema를 추가하고, `approval_state`, `allowed_execution_mode`, `deployment_*`, `playbook_*`, `approval_reasons`, `approved_at`, `expires_at`를 고정한다.
- 완료 기준: approval 응답이 단순 bool이 아니라 운영 문구까지 포함하는 계약으로 고정된다.
- 검증: schema smoke 및 serialization test를 추가한다.

- [x] `ApprovalService` 추가
- 목적: 새 truth를 만드는 게 아니라, 기존 runtime/validation/portfolio/lock contract를 합성해 최종 승인 상태를 계산한다.
- 구현 방식: 판단 순서는 `plan load -> stale/expired -> strategy_mode -> runtime candidate/portfolio gate -> deployment_* -> operating_lock -> risk_reason/risk_state -> thesis dedupe -> allowlist -> validation summary`로 고정한다.
- 구현 방식: `validation/report`를 이 경로에서 직접 재실행하지 않는다. alert side effect 없는 기존 metrics/checklist/runtime snapshot만 사용한다.
- 구현 방식: 상태 판정은 아래처럼 고정한다.
- 구현 방식: `APPROVED_AUTO`: runtime GO + allowlist 통과 + lock 없음 + strategy_mode 허용 + auto_trading_enabled + execution_mode live 허용
- 구현 방식: `APPROVED_MANUAL`: MANUAL_REVIEW 또는 throttled 또는 validation/live grade 조건 미달
- 구현 방식: `APPROVED_SHADOW`: `RESEARCH` 또는 global shadow mode
- 구현 방식: `BLOCKED`: stale/expired, operating lock, deployment NO_GO, allowlist 밖, thesis duplicate, close-only 등
- 완료 기준: 기존 deployment/playbook contract를 유지한 채 execution approval만 별도로 읽을 수 있다.
- 검증: `operating_lock`, `MANUAL_REVIEW`, `RESEARCH`, `NO_GO`, allowlist mismatch, stale plan 케이스를 각각 unit test로 고정한다.

- [x] `POST /execution/approve-plan` 추가
- 목적: 특정 plan이 지금 자동매매 가능한지 최종 승인 상태를 읽는다.
- 구현 방식: 입력은 `plan_id`만 받고, 출력은 실제 `ExecutionApproval` payload를 반환한다.
- 완료 기준: approve-plan route가 `deployment/playbook/approval_reasons`를 포함한 최종 승인 상태를 직접 반환한다.
- 검증: unit test에서 `operating_lock`, `MANUAL_REVIEW`, `RESEARCH`, `NO_GO`, allowlist mismatch, stale plan`을 고정하고 API smoke에서 응답 존재를 검증한다.

## 5. Auto Trading Phase 1D — Order Intent Ledger
- [x] `order_intents` DB 모델/리포지토리 추가
- 목적: 승인과 제출을 분리하고, 왜 주문했는지 또는 왜 안 했는지를 남긴다.
- 구현 방식: `app/db/models.py`와 `app/db/repositories.py`에 additive로 `order_intents`를 추가한다.
- 구현 방식: 최소 필드는 `intent_id`, `plan_id`, `symbol`, `strategy_family`, `execution_mode`, `approval_state`, `submit_decision`, `decision_reason_code`, `decision_reason_message`, `thesis_fingerprint`, `dedupe_result`, `session_guidance`, `created_at`다.
- 완료 기준: submit 전 단계의 intent ledger가 남는다.
- 검증: repository create/get/list 회귀를 추가한다.

- [x] `OrderIntent` schema 및 service 추가
- 목적: 승인 결과와 실행 모드를 반영해 실제 submit decision을 기록한다.
- 구현 방식: `OrderIntentCreateRequest`, `OrderIntentResponse`, `QualitySnapshot`을 추가한다.
- 구현 방식: `OrderIntentService.create_intent(...)`는 approval 재조회, stale 재확인, dedupe 재확인, safety state 확인 후 `SUBMIT / SKIP_*`를 결정한다.
- 구현 방식: duplicate thesis 판정은 execution-layer 우선으로 고정한다. 먼저 열린 `order_intents + order_submissions`를 같은 `thesis_fingerprint` 기준으로 확인하고, 동일 symbol 또는 동일 `thesis_primary_symbol` 범위에서 열린 intent/submission이 있으면 `SKIP_DUPLICATE`로 처리한다. runtime active-plan dedupe는 fallback으로만 사용한다.
- 구현 방식: 1차 매핑은 아래처럼 고정한다.
- 구현 방식: `APPROVED_AUTO + MICRO_LIVE/LIVE -> SUBMIT`
- 구현 방식: `APPROVED_MANUAL -> SKIP_MANUAL_ONLY`
- 구현 방식: `APPROVED_SHADOW -> SKIP_SHADOW_ONLY`
- 구현 방식: `BLOCKED -> SKIP_BLOCKED`
- 구현 방식: stale -> `SKIP_STALE_PLAN`, duplicate thesis -> `SKIP_DUPLICATE`
- 구현 방식: intent ledger와 response에는 approval snapshot을 함께 남긴다. 최소 `allowed_execution_mode`, `deployment_go_no_go`, `deployment_code`, `playbook_go_no_go`, `playbook_code`, `playbook_action`, `playbook_message`, `source_of_truth_hint=execution_approval_snapshot`을 저장/반환한다.
- 완료 기준: 실제 submit 전에 decision ledger가 남고, 왜 skip/subimt 됐는지 설명 가능하다.
- 검증: duplicate thesis(open intent 우선, active-plan fallback), stale plan, manual/shadow/blocked mapping unit test를 추가한다.

- [x] `POST /execution/order-intents` 추가
- 목적: submit 전 의도 기록과 submit decision을 API로 생성한다.
- 구현 방식: 입력은 `plan_id`, `execution_mode`, 출력은 실제 persistence가 반영된 `OrderIntentResponse`로 고정한다.
- 구현 방식: top-level response는 nested approval snapshot을 다시 파싱하지 않아도 되도록 `allowed_execution_mode`, `deployment_*`, `playbook_*`, `source_of_truth_hint`를 additive passthrough로 직접 노출한다.
- 완료 기준: order-intents route가 approval 재조회, dedupe/stale 판정, intent persistence를 한 번에 수행한다.
- 검증: repository/service/API 회귀에서 create/get/list, stale/duplicate/manual/shadow/live decision mapping과 top-level approval snapshot passthrough를 검증한다.

## 6. Auto Trading Phase 1E — Rollout Policy Bootstrap
- [x] family rollout bootstrap contract 추가
- 목적: family별 execution mode cap을 코드 하드코딩 대신 운영 정책 레이어로 분리한다.
- 구현 방식: Phase 1에서는 DB가 아니라 config/bootstrap dict로 시작한다.
- 구현 방식: 초기 기본값은 `trend_continuation -> MICRO_LIVE`, `sweep_reversal -> PAPER`, `range_rotation -> SHADOW`로 고정한다.
- 구현 방식: `live_enabled`, `max_execution_mode`, `max_risk_r`, `allowed_sessions`, `min_quality_score` 필드를 계약으로 고정한다.
- 완료 기준: approval service가 family별 rollout cap을 읽을 수 있다.
- 검증: family별 allow/deny 테스트를 추가한다.

## 7. Auto Trading Phase 2A — Submit Coordinator + Submission Ledger
- [x] `order_submissions` DB 모델/리포지토리 추가
- 목적: 실제 거래소 제출 단계의 ack/reject/cancel을 order-level lifecycle로 남긴다.
- 구현 방식: 최소 필드는 `submission_id`, `intent_id`, `symbol`, `client_order_id`, `exchange_order_id`, `state`, `submit_status`, `message`, `submitted_at`, `acknowledged_at`, `cancelled_at`다.
- 완료 기준: position state와 별개로 order lifecycle이 분리 기록된다.
- 검증: repository CRUD와 lifecycle transition 회귀를 추가한다.

- [x] `ExecutionCoordinator.submit_intent(...)` 추가
- 목적: intent를 실제 exchange adapter 호출 직전까지 번역한다.
- 구현 방식: `intent load -> plan load -> live submit 가능 여부 재검사 -> client_order_id 생성 -> exchange adapter submit -> ack 저장 -> 후속 stop/tp attach 예약` 순서로 고정한다.
- 구현 방식: `idempotency`는 `intent_id` 기준으로 고정하고, 중복 submit을 막는다.
- 완료 기준: 실제 submit path가 order-intent와 분리된 coordinator 위에서 돈다.
- 검증: idempotency, live disabled, bad approval state, submission state 전이 회귀를 추가한다.

- [x] `POST /execution/submit` 추가
- 목적: intent를 실제 제출 경로로 넘긴다.
- 구현 방식: `live=true`라도 `BINANCE_TRADE_LIVE_ENABLED=true`, approval auto, kill switch inactive, execution mode live 허용을 모두 만족해야 한다.
- 완료 기준: submit route가 approval/intents와 분리된 상태로 동작한다.
- 검증: `live=true` 단독으로는 submit 금지되는 회귀를 추가한다.

## 8. Auto Trading Phase 2B — Paper Adapter + Execution State
- [x] paper/mock exchange adapter 추가
- 목적: 실주문 전에 coordinator/state machine/recovery를 live-like로 검증한다.
- 구현 방식: partial fill, timeout, cancel, tp/sl attach failure를 재현하는 paper adapter를 추가한다.
- 완료 기준: SHADOW가 아닌 PAPER에서 실제 order-level lifecycle을 검증할 수 있다.
- 검증: partial fill / timeout / cancel 회귀를 추가한다.

- [x] order lifecycle과 기존 position state machine 연결
- 목적: `CREATED/SUBMITTED/ACKNOWLEDGED/PARTIALLY_FILLED/FILLED/CANCELLED/REJECTED`와 `TRIGGERED/ENTERED/PARTIAL_EXIT/CLOSED`를 분리하되 연동한다.
- 구현 방식: 기존 position state machine은 유지하고, order lifecycle을 별도 레이어로 추가한다.
- 완료 기준: order-level과 position-level state를 동시에 설명할 수 있다.
- 검증: `ENTRY -> PARTIAL_EXIT -> CLOSED`와 order ack/fill/cancel 경로를 통합 테스트로 고정한다.

## 9. Auto Trading Phase 3A — Reconciliation Foundation
- [x] reconciliation schema / DB event 추가
- 목적: local 상태와 exchange 상태 불일치를 기록하고 severity를 분리한다.
- 구현 방식: `ReconciliationMismatch`, `ReconciliationResponse` schema를 추가하고, 필요 시 `execution_reconciliation_events` 테이블을 additive로 추가한다.
- 구현 방식: mismatch 종류는 최소 `ORPHAN_ORDER_EXCHANGE`, `ORPHAN_ORDER_LOCAL`, `ORPHAN_POSITION_EXCHANGE`, `POSITION_SIZE_MISMATCH`, `MISSING_STOP_ORDER`, `MISSING_TP_ORDER`, `FILL_EVENT_GAP`, `USER_STREAM_STALE`를 지원한다.
- 완료 기준: 불일치를 경고가 아니라 event로 기록할 수 있다.
- 검증: mismatch serialization/unit test를 추가한다.

- [x] `POST /execution/reconcile` 추가
- 목적: 특정 symbol의 local/exchange 상태를 비교하고 lock 필요 여부를 반환한다.
- 구현 방식: `local open orders vs exchange open orders`, `local open positions vs exchange positions`, `stop/tp 존재 여부`, `recent fill event gap`, `user-stream freshness`를 확인한다.
- 구현 방식: `auto_resolve`, `apply_lock`는 query option으로 두되 Phase 3 초기에는 conservative default를 사용한다.
- 완료 기준: 운영자가 mismatch와 severity를 API에서 직접 볼 수 있다.
- 검증: missing stop order, stale user-stream, size mismatch 테스트를 추가한다.

## 10. Auto Trading Phase 3B — Safety Locks + Control Plane
- [x] `safety_locks` DB 모델/리포지토리 및 service 추가
- 목적: bool lock가 아니라 scope/reason/severity 기반 lock를 남긴다.
- 구현 방식: `GLOBAL`, `SYMBOL`, `FAMILY`, `SESSION` scope를 지원하고, `active`, `unlock_at`, `released_at`를 기록한다.
- 완료 기준: close-only / kill-switch / symbol/family/session lock를 공통 contract로 저장할 수 있다.
- 검증: set/release/is_new_entry_allowed 회귀를 추가한다.

- [x] control-plane endpoint 추가
- 목적: 운영자가 신규 진입 차단 정책을 수동으로 제어한다.
- 구현 방식: `POST /execution/control/kill-switch`, `POST /execution/control/close-only`, `POST /execution/control/rollout-policy`, `GET /execution/safety-state`를 추가한다.
- 완료 기준: execution safety state를 API에서 읽고 수동 조작할 수 있다.
- 검증: global close-only, family lock, symbol lock, unlock_at 테스트를 추가한다.

## 11. Auto Trading Phase 4A — Binance Live Hookup (Micro Live)
- [x] Binance live submit path를 coordinator에 연결
- 목적: 이미 있는 Binance order adapter를 approval/intent/coordinator 뒤에 연결한다.
- 구현 방식: `MICRO_LIVE`에서만 열고, 허용 symbol/family/session을 강하게 제한한다.
- 구현 방식: `BTCUSDC`, `ETHUSDC`, `trend_continuation`, `A_ONLY`, `max concurrent positions 1~2`, `max daily new entries low`를 초기 기본값으로 둔다.
- 완료 기준: 극소액 live submit이 approval-intent-safety path를 통과한 뒤에만 실행된다.
- 검증: live submit gating, symbol/family allowlist, close-only active 시 block 회귀를 추가한다.

## 12. Auto Trading Phase 4B — Reconciliation Hard Gate + Rollout DB Policy
- [x] family rollout policy를 DB-backed로 승격
- 목적: 운영 중 family/session/live cap을 코드 변경 없이 조정한다.
- 구현 방식: `family_rollout_policy` table과 repository/service를 추가한다.
- 완료 기준: family별 `live_enabled`, `max_execution_mode`, `max_risk_r`, `allowed_sessions`, `min_quality_score`를 DB에서 관리한다.
- 검증: CRUD와 approval integration 테스트를 추가한다.

- [x] reconciliation critical mismatch를 hard lock으로 승격
- 목적: mismatch를 경고에서 끝내지 않고 신규 진입 차단과 연결한다.
- 구현 방식: `ORPHAN_POSITION_EXCHANGE`, `MISSING_STOP_ORDER`, `USER_STREAM_STALE`, `FILL_EVENT_GAP` 같은 critical mismatch는 `apply_lock=true`에서 자동 symbol/global lock을 건다.
- 완료 기준: live 운영에서 unresolved mismatch가 있으면 자동 진입이 막힌다.
- 검증: `missing stop order -> symbol lock`, `user-stream stale repeated -> global/family lock` 회귀를 추가한다.

## 13. 장기 구조 리팩터 목표
- [x] execution 도메인/서비스/리포지토리/route 분리
- 목적: Phase 1~4 contract가 안정화된 뒤 유지보수 구조를 정리한다.
- 구현 방식: 아래 목표 구조로 점진 이동한다.
- 구현 방식: `app/api/routes/execution*.py`, `app/services/execution/*`, `app/repositories/*`, `app/models/schema/execution_*`, `app/domain/execution/*`, `app/exchange/*`
- 구현 방식: 리팩터는 contract와 tests가 먼저 안정화된 뒤에만 한다.
- 완료 기준: 파일 구조가 실행 계층 기준으로 분리되고, 기존 public API contract는 유지된다.
- 검증: 리팩터 전후 API smoke와 regression suite가 동일하게 통과한다.

## 14. Operator Telemetry / 운영 절차 / 라이브 전환 문서
- [x] execution operator dashboard 추가
- 목적: operator가 신규 진입 허용 여부, 현재 open order/position, 최근 intent/reconciliation 상태를 하나의 runtime surface에서 본다.
- 구현 방식: `GET /execution/operator-dashboard`를 추가해 `new_entries_allowed`, `blocking_reason_code/message`, `active_locks`, `rollout_policies`, `recent_intents`, `open_orders`, `open_positions`, `recent_reconciliation_summary`, `portfolio_summary`, `alert_summary`, `execution_quality_summary`를 반환한다.
- 완료 기준: approval/intent/reconcile/safety state를 개별 API를 다시 열지 않고 한 payload로 확인할 수 있다.
- 검증: `tests/test_execution_operator_dashboard.py`, `tests/test_api_smoke.py` 회귀를 통과한다.

- [x] 운영 runbook 문서 추가
- 목적: shadow/paper/micro-live 운영자가 pre-flight, candidate review, preview/approve/intent/submit, reconcile, close-only, kill-switch 절차를 고정된 순서로 수행한다.
- 구현 방식: `docs/AUTO_TRADING_OPERATING_RUNBOOK.md`에 source-of-truth hierarchy, 단계별 명령어, 운영 중 점검 절차를 문서화한다.
- 완료 기준: 운영자가 대화 없이도 일일 실행 절차를 따라갈 수 있다.
- 검증: 문서 명령어와 현재 API surface가 일치하는지 수동 검수한다.

- [x] 라이브 전환 체크리스트 문서 추가
- 목적: `SHADOW -> PAPER -> MICRO_LIVE -> LIVE` 승격 조건과 no-go 조건을 고정한다.
- 구현 방식: `docs/AUTO_TRADING_LIVE_GO_LIVE_CHECKLIST.md`에 environment prerequisite, exit criteria, no-go condition, first live-session 절차를 문서화한다.
- 완료 기준: 라이브 전환 여부를 문서 기준으로 일관되게 판단할 수 있다.
- 검증: checklist 문구가 `validation/report`, `operations/checklist`, `execution/operator-dashboard` 계약과 일치하는지 수동 검수한다.

- [x] incident drill / failover rehearsal 스크립트와 플레이북 추가
- 목적: 운영자가 `dashboard`, `reconcile`, `kill_switch`, `close_only`, `rollout_block` 시나리오를 같은 절차로 반복 실행하고 복구 가능 상태를 검증한다.
- 구현 방식: `scripts/run_execution_incident_drill.py`를 추가해 read-only/dashboard/control-plane drill을 실행하고, `docs/AUTO_TRADING_INCIDENT_DRILL_PLAYBOOK.md`에 선행 조건, 성공 기준, 복구 절차를 문서화한다.
- 구현 방식: reconcile drill은 runtime bug 없이 실행돼야 하므로, `OrderSubmission.submitted_at`의 naive/aware UTC 정규화와 `FILL_EVENT_GAP` 회귀 테스트를 함께 고정한다.
- 완료 기준: `python scripts/run_execution_incident_drill.py --symbol BTCUSDC --scenario dashboard --scenario reconcile`가 실제 payload를 반환하고, 관련 문서가 운영 문서 목록에 포함된다.
- 검증: `tests/test_execution_transition.py`의 naive timestamp fill-gap 회귀, drill script 실실행, README/docs 링크 갱신으로 확인한다.

- [x] execution operator UI route 추가
- 목적: operator가 JSON payload를 직접 jq로 읽지 않고도 `dashboard + validation + checklist`를 한 화면에서 확인한다.
- 구현 방식: `GET /execution/operator-ui`를 추가해 브라우저에서 `GET /execution/operator-dashboard`, `POST /operations/checklist`, `POST /validation/report`를 같은 origin으로 읽어 카드/테이블/원시 payload로 렌더링한다.
- 구현 방식: 새 판단을 만들지 않고 기존 runtime contract를 그대로 소비하며, 화면 상단에 `operator surface only`와 최종 승인 source-of-truth 문구를 고정한다.
- 완료 기준: `http://127.0.0.1:8000/execution/operator-ui?symbol=BTCUSDC&universe=usdc_perp_top30&days=7`를 열면 신규 진입 허용 여부, 배포 문구, playbook, locks, open orders/positions, reconcile 상태를 한 화면에서 볼 수 있다.
- 검증: `tests/test_api_smoke.py`에서 HTML route가 `text/html`로 열리고 dashboard/checklist/validation endpoint reference를 포함하는지 확인한다.

- [x] MICRO_LIVE preflight helper 추가
- 목적: live 전환 직전 operator가 `health/operator-dashboard/safety/validation/checklist/alerts/scanner`를 한 번에 점검하고, `READY_FOR_MICRO_LIVE` vs `NOT_READY`를 명시적으로 받는다.
- 구현 방식: `scripts/run_micro_live_preflight.py`를 추가해 `GET /health/ready`, `GET /execution/operator-dashboard`, `GET /execution/safety-state`, `POST /validation/report`, `POST /operations/checklist`, `GET /alerts/metrics`, `GET /scanner/top`를 호출한다.
- 구현 방식: 결과 payload는 `overall_status`, `summary_line`, `checks`, `candidate`, `approval_surfaces`, `edge_experiment_review`, `edge_evolution_rule`, `experiment_review_targets`, `representative_candidates`, `next_steps`를 고정하고, 옵션으로 `reports/operations/micro_live_preflight/*.md` 리포트를 생성한다.
- 구현 방식: `experiment_review_targets`가 있으면 `next_steps`에 `scripts/run_split_review_followup.py --action ...` 명령도 같이 싣는다.
- 구현 방식: stage snapshot과 session brief의 `entry_timing_review_target` / `execution_style_review_target`에도 같은 followup command를 실어 handoff 이후에도 review packet을 바로 생성할 수 있게 한다.
- 완료 기준: `./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDC --days 7` 한 번으로 live 전환 전 preflight 상태를 결정할 수 있다.
- 완료 기준: split review target이 잡힌 경우 `./.venv/bin/python scripts/run_split_review_followup.py --symbol BTCUSDC --days 7 --action auto`로 바로 review packet을 만들 수 있다.
- 검증: `py_compile`, `--help`, `--no-write-report`, markdown report write 경로를 실제로 확인한다.

- [x] split review followup ledger contract + closed-loop 강화
- 목적: split review packet 이력을 운영 surface에서 같은 의미로 읽고, 같은 packet 재생성을 억제하면서, 새 close가 쌓인 뒤에는 이전 review 방향이 실제로 확인됐는지 다시 규칙에 반영한다.
- 구현 방식: `scripts/run_split_review_followup.py`는 generation packet과 후속 decision transition을 같은 `reports/operations/split_review_followups/review_ledger.jsonl`에 기록하고, 요약 contract는 `last_generated_status`, `last_decision_status`, `last_effective_status`, `last_action`, `last_followup_command`, `recent_entry_count`, `recent_packets`, `latest_action_streak`를 고정한다.
- 구현 방식: `edge_evolution_rule`는 최신 `review_followup_ledger` packet과 현재 `edge_experiment_review.closed_trade_count / true_edge_ratio / edge_decay_rate`를 함께 읽어, 이전 review 이후 새 closes가 같은 방향으로 누적됐을 때만 `recommendation_strength`와 `closed_loop_confirmation_state`를 `promote / reduce / kill` 강화에 사용한다.
- 구현 방식: `operator_action_priority`는 같은 ledger summary를 읽어 `fresh READY packet`, 직전 `NO_TARGET`, 최근 3회 연속 동일 packet을 중복 억제 기준으로 사용한다. ledger는 packet history이며 approval authority가 아니다.
- 구현 방식: `edge_experiment_review`는 `sample_maturity_state`, `next_sample_target_closed_trades`, `remaining_closed_trades_to_next_target`, `regime_dependency_state`, `strongest_regime`, `weakest_regime`를 함께 노출해 “아직 directional인지 / 어느 regime에서 약한지”를 같은 contract에서 읽게 한다.
- 구현 방식: `edge_experiment_review.operating_discipline`는 `framework_quality_state=framework_ready`, `system_mode=operate_and_experiment`, `evaluation_focus=after_cost_edge_only`, `primary_goal=find_first_verified_edge`, `profit_claim_allowed`, `structure_change_review_allowed`, `single_experiment_only`를 함께 노출해 framework readiness와 edge proof를 혼동하지 않게 한다.
- 구현 방식: 같은 `operating_discipline`는 `early_loss_rewrite_embargo_active`, `loss_driven_rewrite_allowed`, `rollout_expansion_allowed`를 함께 노출해 early-loss rewrite와 regime-unstable expansion을 명시적으로 금지한다.
- 구현 방식: 같은 `operating_discipline`는 `current_system_identity=edge_proof_engine`, `next_system_stage=post_first_verified_edge`, `resilience_claim=harder_to_fail_from_self_deception`, `fail_safe_claim=false`, `realized_edge_dependency_domains=[market_edge, execution_quality, operating_discipline]`, `post_proof_scale_spec_id=edge_proof_capital_scale_v1`, `improvement_priority=prove_single_edge_before_density_or_strategy_expansion`, `alpha_generator_review_allowed`, `capital_scale_review_allowed`, `signal_density_control_review_allowed`, `execution_strategy_automation_review_allowed`, `multi_strategy_expansion_review_allowed`도 함께 노출해 alpha generation, capital scaling, density tuning, execution automation, 전략 확장을 edge proof 뒤로 미룬다.
- 구현 방식: `score_to_outcome_funnel_summary.operating_kpis`는 `runtime_to_accepted`, `submitted_to_filled`, `filled_to_closed`, `closed_to_post_cost_profitable`, `closed_trades_per_day`를 daily KPI contract로 노출한다.
- 구현 방식: `edge_experiment_review.experiment_sequence`는 `entry_timing (early_limit vs reaction_confirmed) -> execution_style (passive_limit vs market) -> exit_optimization` 순서를 노출하고, `exit_optimization_allowed=false` 동안에는 alpha-research exit review를 deferred hint로 읽게 한다.
- 구현 방식: `edge_evolution_rule`는 regime dependency가 아직 크면 `regime_guard_state=promotion_blocked_by_regime_dependency`로 promotion 해석을 research-only로 되돌린다.
- 구현 방식: `operator_action_priority`는 `experiment_execution_policy.mode=single_active_experiment`와 `deferred_experiment_actions`를 함께 내려, entry timing과 execution style을 동시에 돌리지 않고 한 번에 하나의 split만 active로 유지한다.
- 완료 기준: dashboard/validation/checklist/session brief/stage monitor/entry alert가 같은 ledger history vocabulary를 공유하고, evolution rule과 operator priority가 둘 다 같은 history로 closed-loop와 dedupe를 수행한다.
- 완료 기준: operator가 같은 surface에서 `sample target`, `regime guard`, `single active experiment` 정책을 같이 읽을 수 있다.
- 완료 기준: operator가 같은 surface에서 “framework is ready”와 “edge is proven”을 분리해서 읽고, `system_mode=operate_and_experiment`, `evaluation_focus=after_cost_edge_only`, `profit_claim_allowed=false` 구간에서는 구조 변경 대신 sample accumulation을 우선한다.
- 검증: `tests/test_split_review_followup_ledger.py`, `tests/test_edge_evolution_rule.py`, `tests/test_operator_action_priority.py`, `tests/test_edge_experiment_review.py`, `tests/test_split_review_followup.py`로 packet summary, closed-loop 강화, regime guard, single-active-experiment, script 회귀를 확인한다.

- [x] post-live pruning review helper 추가
- 목적: 첫 실제 live 운영 사이클 이후 contract pruning backlog를 다시 열어야 하는지 `filled live activity + reconciliation + validation/checklist` 기준으로 판단한다.
- 구현 방식: `scripts/run_post_live_pruning_review.py`를 추가해 local DB의 `order_submissions`와 `GET /execution/operator-dashboard`, `POST /validation/report`, `POST /operations/checklist`를 함께 읽는다.
- 구현 방식: 결과 payload는 `decision`, `rationale`, `checks`, `db_live_activity`, `operator_dashboard_summary`, `validation_summary`, `checklist_summary`, `approval_surfaces`, `next_steps`를 고정하고, 옵션으로 `reports/operations/pruning_reviews/*.md` 리포트를 생성한다.
- 완료 기준: `./.venv/bin/python scripts/run_post_live_pruning_review.py --symbol BTCUSDC --days 7` 한 번으로 pruning review를 reopen할지 keep hold할지 판단할 수 있다.
- 검증: `py_compile`, `--help`, `--no-write-report`, markdown report write 경로를 실제로 확인한다.

- [x] PAPER lineage watcher helper 추가
- 목적: London/New York 세션에 lineage 대상 family(`trend_continuation`, `sweep_reversal`) 후보가 나올 때까지 사람이 수동으로 drill을 반복하지 않게 한다.
- 구현 방식: `scripts/watch_paper_candidate_drill.py`를 추가해 `scripts/run_paper_candidate_drill.py --no-write-report`를 주기적으로 반복 호출하고, 첫 eligible candidate가 뜨면 종료한다.
- 구현 방식: 옵션으로 `--submit-paper`를 받아 첫 eligible candidate에 한해 `live=false` PAPER submit까지 이어지게 하고, 결과 payload는 `overall_status`, `summary_line`, `attempts`, `final_result`, `next_steps`를 고정한다.
- 구현 방식: markdown 리포트는 `reports/operations/paper_candidate_watch/*.md`에 저장한다.
- 완료 기준: `./.venv/bin/python scripts/watch_paper_candidate_drill.py --interval-seconds 900 --max-attempts 8 --submit-paper` 한 번으로 preferred session 동안 lineage 대상 family를 자동 감시할 수 있다.
- 검증: `py_compile`, `--max-attempts 1 --no-write-report` 실행, JSON 출력과 report write 경로를 확인한다.

## 15. Model Upgrade Phase 1A — Signal Funnel Instrumentation
- [x] runtime signal funnel 계측 추가
- 목적: `signal quality ↑ / trade frequency ↓` 문제를 감으로 해석하지 않고, `runtime candidate -> blocked -> intent -> open order/open position` 단계별 drop-off를 숫자로 본다.
- 구현 방식: `/execution/operator-dashboard`에 additive `signal_funnel` payload를 추가하고, 기존 runtime truth만 재사용한다.
- 구현 방식: `portfolio_summary`에서 `accepted_candidate_count`, `blocked_candidate_count`, `blocked_reason_counts`를 읽고, `recent_intents`의 `submit_decision` 집계를 함께 노출한다.
- 구현 방식: `open_orders`, `open_positions`는 별도 활성 상태 지표로 포함해, 후보가 submit 이후 실제 order/position 상태까지 이어졌는지 같은 payload에서 읽게 한다.
- 구현 방식: 기존 전략 산식(`plan_generator`, `expected_*`, validation gate, rollout policy)은 이번 phase에서 바꾸지 않는다.
- 완료 기준: operator dashboard만 봐도 `runtime candidate가 어디서 얼마나 줄어드는지`, `어떤 blocked reason이 가장 큰 병목인지`, `intent 이후 실제 order/position까지 얼마나 이어졌는지`를 읽을 수 있다.
- 검증: unit test에서 `runtime_candidates == accepted + blocked`, `blocked_reason_counts`, `submit_decision_counts`를 고정하고, API smoke에서 `signal_funnel` 존재를 확인한다.
- [x] signal funnel을 operator UI에 직접 노출
- 목적: raw dashboard JSON을 열지 않아도 운영 화면에서 바로 `후보 감소 병목`과 `Family / Regime / Session 통과율`을 읽게 한다.
- 구현 방식: `app/services/execution_operator_ui.py`가 `dashboard.signal_funnel`을 읽어 `신호 퍼널` 섹션과 `Family / Regime / Session 통과율` 테이블을 렌더링한다.
- 구현 방식: 새 섹션은 runtime/accepted/blocked/intent/open-order/open-position 요약 카드와 함께 pass-rate를 같은 화면에 배치하고, source-of-truth는 계속 `/execution/operator-dashboard.signal_funnel`로 고정한다.
- 완료 기준: `/execution/operator-ui`에서 `runtime candidate -> blocked -> intent -> open order/open position` 흐름과 `Family / Regime / Session 통과율`을 한 화면에서 읽을 수 있다.
- 검증: operator UI는 dashboard의 `signal_funnel`만 소비하고, `tests/test_execution_operator_dashboard.py`, `tests/test_api_smoke.py`, `py_compile` 회귀가 유지된다.
- [x] signal funnel blocked reason을 gate-group으로 분류
- 목적: frequency 문제를 `안전성 하드 블록`과 `품질 게이트`로 분리해서 읽고, softening 후보를 감으로 고르지 않게 한다.
- 구현 방식: `/execution/operator-dashboard.signal_funnel`에 `blocked_gate_group_counts`, `blocked_gate_groups`, `current_entry_gate_group`, `current_entry_gate_reason`를 additive로 추가한다.
- 구현 방식: gate-group은 `safety / structural / rollout / quality / unknown`으로 고정하고, 기존 blocked reason code를 이 분류로 매핑한다.
- 구현 방식: `/execution/operator-ui`는 `게이트 유형별 차단` 섹션과 `현재 신규 진입 차단 유형` 요약 카드를 추가해 같은 분류를 바로 노출한다.
- 구현 방식: 같은 payload에 `hard_block_summary`, `softening_candidate_summary`, `rollout_block_summary`를 추가하고, UI는 이를 `유지해야 하는 hard gate`, `완화 검토 후보`, `운영 정책 차단` 카드/표로 노출한다.
- 완료 기준: operator dashboard/UI만 봐도 어떤 차단이 `절대 유지할 safety/structural gate`인지, 어떤 차단이 `quality softening 후보`인지 구분할 수 있다.
- 검증: `tests/test_execution_operator_dashboard.py`는 대표 reason code가 기대 gate-group으로 매핑되는지 고정하고, `tests/test_api_smoke.py`는 dashboard payload와 UI 섹션 존재를 회귀로 잠근다.
- [x] quality gate softening priority와 family/regime/session 병목을 같은 runtime surface에 노출
- 목적: softening 후보를 단순 reason count가 아니라 `현재 blocked 분포와 pass-rate 병목` 기준으로 우선순위화하고, 어떤 family/regime/session이 실제로 frequency를 죽이는지 바로 읽게 한다.
- 구현 방식: `/execution/operator-dashboard.signal_funnel`에 `quality_softening_priorities`, `family_bottlenecks`, `regime_bottlenecks`, `session_bottlenecks`를 additive로 추가한다.
- 구현 방식: `quality_softening_priorities`는 `quality` gate-group reason만 대상으로 하고, blocked count / share / representative family-regime-session을 함께 노출한다.
- 구현 방식: `family_bottlenecks`, `regime_bottlenecks`, `session_bottlenecks`는 각 축의 `runtime / accepted / blocked / pass_rate`를 계산하고 pass-rate 오름차순으로 상위 병목을 노출한다.
- 구현 방식: `/execution/operator-ui`는 이를 `완화 우선순위`, `Family 병목 상위`, `Regime 병목 상위`, `Session 병목 상위` 카드와 표로 렌더링한다.
- 완료 기준: operator UI만 봐도 `무엇을 먼저 softening 검토할지`와 `어느 family/regime/session에서 병목이 심한지`를 바로 읽을 수 있다.
- 검증: `tests/test_execution_operator_dashboard.py`는 quality reason/family/regime/session 대표값을 고정하고, `tests/test_api_smoke.py`는 새 payload 키와 UI 텍스트 존재를 회귀로 잠근다.

## Phase 1 Acceptance Criteria
- 기존 `plans/scanner/validation` contract 회귀가 없어야 한다.
- 동일 plan에 대해 approval 결과가 결정적이고 재현 가능해야 한다.
- intent 생성 시 submit 여부가 approval state와 policy에 일관되게 대응해야 한다.
- duplicate/stale/lock/manual/shadow 경로가 모두 테스트로 커버되어야 한다.
- Phase 1에서는 exchange submit이 발생하지 않아야 한다.
- PR1 당시 route skeleton은 approval/intent mock 결과를 반환하지 않고 provisional metadata만 노출해야 했다. 현재 기준선에서는 `preview/approve-plan/order-intents` semantics가 활성화돼 있으며, 이후 phase는 이 실제 contract를 additive로만 확장한다.

## 권장 PR 순서
1. PR1 `enum/config/schema/route scaffold`
2. PR2 `ExecutablePlan preview builder`
3. PR3 `ApprovalService + approve-plan semantics`
4. PR4 `order_intents persistence + order-intents semantics`
5. PR5 `regression/docs`
