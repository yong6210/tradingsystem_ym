# MICRO_LIVE Near-100 Hardening Plan

최종 갱신: 2026-05-10

## 1. 목표 정의
이 문서의 `100%에 가까운 완성도`는 무손실이나 무버그를 뜻하지 않는다. 목표는 다음 상태에 최대한 가깝게 만드는 것이다.

- 주문은 모든 live gate, safety lock, reconciliation, liquidity, event blackout, exchange rule check가 통과할 때만 제출된다.
- 제출되지 않은 주문은 `no signal / approval blocked / intent skipped / submit failed / submitted no fill / reconciliation stale` 중 하나로 반드시 분류된다.
- 운영자는 raw log를 뒤지기 전에 `latest.md/latest.json` 고정 경로와 heartbeat 결과만으로 현재 위험 상태와 다음 액션을 읽을 수 있다.
- 알림은 중요한 `FAIL/WATCH/ALERT`만 짧게 보내고, 전송 실패가 cooldown 성공으로 기록되지 않는다.
- live 확대는 replay 평균값이 아니라 보수적 하한, slice 진단, 실제 live/paper 표본, reconciliation 안정성까지 같이 통과해야 한다.
- exchange/API/데이터/스케줄/알림 중 하나가 깨져도 silent success가 아니라 `FAIL` 또는 `WATCH`로 남는다.

## 2. 현재 기준선
현재 운영 하드닝 기준선은 다음으로 본다.

- `scripts/run_micro_live_runtime_guard.py`
- `scripts/run_micro_live_no_order_watchdog.py`
- `scripts/run_live_reconciliation_watchdog.py`
- `scripts/run_micro_live_synthetic_canary.py`
- `scripts/run_micro_live_boot_check.py`
- `scripts/run_micro_live_ops_heartbeat.py`
- `scripts/run_micro_live_failure_drill.py`
- `scripts/run_replay_validation_bridge.py`
- `scripts/run_session_impulse_retest_runtime_audit_report.py`
- `scripts/run_binance_rule_drift_snapshot.py`
- `scripts/build_micro_live_event_blackouts.py`
- `scripts/install_micro_live_ops_launchd.py`

현재 상태 해석은 `scripts/run_micro_live_ops_heartbeat.py --no-fail-exit`를 우선한다. `PASS`는 운영 리포트와 failure-contract drill이 최신이고 내부 status도 통과했다는 뜻이고, `WATCH`는 주문 차단/no-order/replay bridge 같은 검토 상태가 있다는 뜻이며, `FAIL`은 live routing 전에 즉시 조치해야 한다는 뜻이다.

## 3. 단계별 하드닝
### Phase 1. 단일 관측 경로
- 모든 운영 가드는 timestamp report와 함께 `latest.md/latest.json`을 atomic write로 남긴다.
- heartbeat는 report 파일의 freshness뿐 아니라 내부 `overall_status/status/evaluation.status`를 읽는다.
- macro blackout은 파일 존재가 아니라 live approval이 실제 쓰는 configured path와 future horizon을 확인한다.
- macro calendar refresh 스케줄은 configured path가 있으면 live approval이 실제 쓰는 blackout 계약 파일을 직접 갱신한다.
- live approval이 읽는 macro blackout, strategy-time contract, plan blocklist JSON은 builder에서 atomic write로 갱신한다.
- launchd plist 생성/설치도 atomic replace로 처리하고, `launchctl bootstrap` 실패는 non-zero exit로 드러낸다.
- 알림 cooldown state는 전송 성공이 확인된 경우에만 기록한다.

완료 기준:
- `runtime_guard`, `no_order_watchdog`, `reconciliation_watchdog`, `synthetic_canary`, `boot_check`, `ops_heartbeat`, `replay_validation_bridge`, `failure_drill`, `binance_rule_drift`가 고정 경로로 읽힌다.
- stale/malformed/missing report는 `PASS`로 숨지 않는다.

### Phase 2. 주문 경로 증명
- signal이 live 계약에 들어온 뒤 `approval -> intent -> submission -> ledger/fill` 중 어디서 끊겼는지 항상 audit row로 남긴다.
- `submit_ready > 0`인데 live submission이 없으면 no-order watchdog이 `intent_to_submission_gap`로 띄운다.
- exchange rejection, missing ledger, stale user-stream, open position stale은 reconciliation watchdog에서 hard failure로 분류한다.
- WS stream이 라우팅을 담당해 sync/manual route를 억제한 경우도 `ws_stream_active_route_suppressed` audit row로 남긴다.

완료 기준:
- “신호는 있었는데 왜 주문이 안 들어갔나”를 1개 리포트에서 확정할 수 있다.
- submit path synthetic canary가 실제 주문 없이 sizing, limit price normalize, liquidity gate 경로를 통과한다.
- `session_impulse_retest`는 refresh/auto_route audit report의 `latest.md/latest.json`으로 `signal_generated / no_fresh_candidates / intent_blocked / submitted / submit_error`를 확인할 수 있다.

### Phase 3. 검증 증거 보수화
- replay bridge는 평균 EV만 보지 않고 `ev_r_lower_95`, material slice(`direction/strategy_family/entry_model`)를 본다.
- slice warning은 clean pass가 아니라 manual review 대상으로 유지한다.
- live gate proof는 실제 execution subset이 충분해질 때까지 bootstrap/advisory 증거와 분리한다.

완료 기준:
- replay 결과가 좋아도 하한/표본/slice가 약하면 자동 live 개방이 되지 않는다.
- 100 closes 전에는 edge claim을 쓰지 않는다.

### Phase 4. 장애 훈련
정기적으로 다음 상황을 강제로 재현한다.

- report missing, stale, malformed
- macro blackout expired/short horizon/stale but horizon ok
- Discord/system alert delivery failure
- exchange rule drift
- synthetic canary sizing/liquidity failure
- stale open submission without Binance ledger
- user-stream stale open ledger/open position
- worker boot check failure

기본 non-live 검증은 `scripts/run_micro_live_failure_drill.py --no-fail-exit`로 실행한다. 이 스크립트는 실제 주문/실 DB/control switch를 건드리지 않고, missing/stale/malformed report, 짧은 macro horizon, 알림 전송 실패, stale submission, submit-ready gap, runtime audit hard failure가 `PASS`로 숨지 않는지만 검증한다.

완료 기준:
- 각 장애가 `PASS`로 숨지 않고 `WATCH` 또는 `FAIL`로 올라온다.
- 실패 알림이 실제 전송되지 않았으면 cooldown이 기록되지 않는다.

### Phase 5. 운영 승격 기준
MICRO_LIVE에서 LIVE로 확대하려면 다음을 동시에 본다.

- ops heartbeat hard failure 0
- runtime guard blocking failure 0
- reconciliation critical/stale issue 0
- no-order watchdog 원인이 설명 가능
- replay bridge clean pass 또는 slice warning 수동 검토 완료
- actual execution subset이 bootstrap 구간을 벗어남
- macro blackout horizon 충분
- Binance rule drift 없음
- 최근 알림 전송 경로 정상

## 4. NO-GO 원칙
아래 중 하나라도 있으면 live 확대 또는 신규 symbol 추가를 보류한다.

- `FAIL` heartbeat item 존재
- unresolved reconciliation critical mismatch
- open live position의 stop/ledger/user-stream 상태 불명확
- configured macro blackout horizon 부족 또는 만료
- exchange rule drift 미검토
- approval block 원인이 `unknown` 또는 raw log 없이는 설명 불가
- alert delivery failure가 cooldown으로 기록됨
- replay bridge가 평균만 좋고 lower bound 또는 material slice가 약함

## 5. 현재 우선순위
1. 모든 운영 가드의 `latest.md/latest.json` alias와 atomic write를 통일한다.
2. reconciliation watchdog도 알림 전송 성공 확인 후에만 cooldown state를 기록하게 한다.
3. boot/runtime/reconciliation/canary latest alias를 테스트로 고정한다.
4. Phase 2 주문 경로 audit row를 더 강화해 `신호 있음/승인 차단/intent 생성/submit 경계`를 DB에서 직접 재생 가능하게 한다.
5. Phase 4 장애 훈련 테스트를 늘려 silent success를 줄인다. 기본 계약 드릴은 `run_micro_live_failure_drill.py`가 담당한다.
