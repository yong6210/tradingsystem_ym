# Auto-Trading Incident Drill Playbook

## 목적

자동매매 운영 중 아래 질문에 대한 리허설을 고정한다.

- kill switch가 실제로 신규 진입을 막는가
- close-only가 실제로 신규 진입을 막는가
- family rollout block이 operator surface에 드러나는가
- reconcile 결과가 runtime surface와 함께 읽히는가

이 문서는 기존 control-plane과 runtime dashboard를 이용한 운영 리허설 기준이다.

## 원칙

- source-of-truth는 계속 서버다.
- incident drill은 기본적으로 `SHADOW/PAPER/MICRO_LIVE` 운영 준비를 위한 rehearsal이다.
- drill 중 변경한 kill switch / close-only / rollout policy는 종료 시 원복한다.
- live 진입이 열린 환경에서는 먼저 `close-only` 또는 `kill switch` 상태를 확인한다.

## 선행 확인

1. 서버가 실행 중이어야 한다.
2. DB가 초기화되어 있어야 한다.
3. operator dashboard와 safety-state가 읽혀야 한다.

```bash
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?symbol=BTCUSDT&universe=micro_live_usdt_11&days=7" | jq
curl -s "http://127.0.0.1:8000/execution/safety-state?symbol=BTCUSDT&family=session_impulse_retest" | jq
```

## 표준 drill 시나리오

### 1. Dashboard Snapshot

목적:
- 현재 신규 진입 허용 여부와 blocking reason을 baseline으로 저장한다.

확인 포인트:
- `new_entries_allowed`
- `blocking_reason_code`
- `active_locks`
- `recent_reconciliation_summary`

### 2. Reconcile Read-Only

목적:
- 현재 symbol 기준 불일치 상태를 read-only로 점검한다.

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/reconcile?auto_resolve=false&apply_lock=false" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTCUSDT"}' | jq
```

확인 포인트:
- `highest_severity`
- `lock_required`
- `mismatches[*].mismatch_type`

### 3. Kill Switch Drill

목적:
- global kill switch가 operator dashboard와 safety-state에 즉시 반영되는지 확인한다.

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/kill-switch" \
  -H "Content-Type: application/json" \
  -d '{"active":true,"reason_message":"Incident drill: manual kill switch","updated_by":"incident_drill"}' | jq
```

원복:

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/kill-switch" \
  -H "Content-Type: application/json" \
  -d '{"active":false,"reason_message":"Incident drill restore: manual kill switch","updated_by":"incident_drill"}' | jq
```

확인 포인트:
- `kill_switch_active == true`
- `new_entries_allowed == false`
- `blocking_reason_code`가 kill switch 계열인지 확인

### 4. Close-Only Drill

목적:
- close-only가 신규 진입 차단으로 반영되는지 확인한다.

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/close-only" \
  -H "Content-Type: application/json" \
  -d '{"active":true,"reason_message":"Incident drill: close-only","updated_by":"incident_drill"}' | jq
```

원복:

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/close-only" \
  -H "Content-Type: application/json" \
  -d '{"active":false,"reason_message":"Incident drill restore: close-only","updated_by":"incident_drill"}' | jq
```

확인 포인트:
- `close_only_active == true`
- `new_entries_allowed == false`
- `blocking_reason_code`가 close-only 계열인지 확인

### 5. Rollout Block Drill

목적:
- family rollout block이 operator surface에 반영되는지 확인한다.

예시: `session_impulse_retest`를 임시로 shadow cap으로 내린다.

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/rollout-policy" \
  -H "Content-Type: application/json" \
  -d '{
    "family":"session_impulse_retest",
    "live_enabled":false,
    "max_execution_mode":"SHADOW",
    "max_risk_r":0.0,
    "allowed_sessions":[],
    "min_quality_score":75.0,
    "updated_by":"incident_drill",
    "notes":"Incident drill: force rollout block"
  }' | jq
```

원복은 현재 운영 기준값으로 다시 올린다.

확인 포인트:
- `rollout_policies`에 변경 반영
- 해당 family의 신규 진입 허용 상태가 달라지는지 확인

## 자동 실행 스크립트

표준 drill은 아래 스크립트로 한 번에 돌릴 수 있다.

```bash
python scripts/run_execution_incident_drill.py \
  --symbol BTCUSDT \
  --family session_impulse_retest
```

주요 옵션:
- `--scenario dashboard`
- `--scenario reconcile`
- `--scenario kill_switch`
- `--scenario close_only`
- `--scenario rollout_block`
- `--no-restore` : 원복 없이 상태를 유지
- `--no-write-report` : markdown report 생성 생략

기본 출력:
- JSON stdout
- Markdown report: `reports/execution/incident_drills/execution_incident_drill_<SYMBOL>_<UTC>.md`

## MICRO_LIVE Failure Contract Drill

control-plane 상태를 바꾸지 않는 운영 장애 계약 검증은 아래 스크립트로 실행한다.

```bash
./.venv/bin/python scripts/run_micro_live_failure_drill.py --no-fail-exit
```

이 drill은 실제 주문, 실 DB 변경, kill switch/close-only 변경을 하지 않는다. 대신 temp 파일과 순수 평가 함수로 아래 실패가 `PASS`로 숨지 않는지 확인한다.

- missing/stale/malformed operating report
- macro blackout short horizon
- alert delivery failure cooldown contract
- stale submitted order without Binance ledger
- submit-ready intent without live submission
- session impulse retest runtime audit hard failure

기본 출력:
- JSON stdout
- Markdown report: `reports/operations/micro_live_failure_drill/micro_live_failure_drill_<UTC>.md`
- stable aliases: `reports/operations/micro_live_failure_drill/latest.md`, `latest.json`

## Drill 성공 기준

- kill switch 적용 시 `new_entries_allowed=false`
- close-only 적용 시 `new_entries_allowed=false`
- rollout block 적용 시 family cap 변화가 dashboard/safety-state에 보임
- reconcile read-only가 mismatch/lock-required를 일관되게 반환
- restore 후 기존 운영 상태로 복귀

## 주의

- live 운영 환경에서는 drill 전에 현재 open position/order를 확인한다.
- `--no-restore`는 운영 상태를 남기므로 rehearsal 목적이 아니면 쓰지 않는다.
- 이 문서는 operator rehearsal 기준이고, 최종 배포 승인 기준은 여전히 아래가 담당한다.
  - `POST /validation/report`
  - `POST /operations/checklist`
