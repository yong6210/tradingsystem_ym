# Kill Condition Automation Live Runbook

최종 갱신: 2026-05-19

현재 운영 예시는 `USDT 11심볼 + session_impulse_retest` 기준이다. 예전 `BTCUSDC / usdc_perp_top30` 예시는 현재 live 계약이 아니다.

## 1. 목적
- `kill_condition_automation` proposal summary를 실제 `close-only` 또는 `kill-switch` live write로 번역할 때 같은 절차를 반복하게 만든다.
- first-wave는 끝까지 `explicit arm`이 있어야만 live write가 일어나게 유지한다.

## 2. 절대 규칙
1. 기본은 항상 dry-run이다.
2. `KILL_CONDITION_AUTOMATION_LIVE_ENABLED=1`만으로는 부족하다.
3. live write는 아래 4개가 동시에 필요하다.
- `dry_run=false`
- `allow_live_write=true`
- `KILL_CONDITION_AUTOMATION_LIVE_ENABLED=1`
- `arm_token == KILL_CONDITION_AUTOMATION_ARM_TOKEN`
4. `auto_throttle`는 first-wave에서 live write target이 아니다.
5. manual `close-only`, manual `kill-switch`, active lock이 이미 있으면 새 escalation보다 기존 override를 우선한다.

## 3. 사전 준비
환경 변수 또는 `.env`:

```bash
export KILL_CONDITION_AUTOMATION_LIVE_ENABLED=1
export KILL_CONDITION_AUTOMATION_ARM_TOKEN="replace-with-long-random-token"
```

사전 확인:

```bash
curl -s "http://127.0.0.1:8000/execution/safety-state?symbol=BTCUSDT" | jq
curl -s -X POST "http://127.0.0.1:8000/validation/report?symbol=BTCUSDT" | jq '{
  kill_condition_automation_available,
  kill_condition_automation_summary
}'
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?symbol=BTCUSDT&universe=micro_live_usdt_11&days=7" | jq '.signal_funnel.kill_condition_automation'
```

브라우저에서는 `GET /execution/operator-ui` 홈의 `Kill Condition Inspector`를 먼저 본다.

## 4. Dry-Run
스크립트 dry-run:

```bash
./.venv/bin/python scripts/run_kill_condition_automation.py \
  --symbol BTCUSDT \
  --universe micro_live_usdt_11 \
  --days 7
```

API dry-run:

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/kill-condition/apply" \
  -H "Content-Type: application/json" \
  -d '{
    "symbol":"BTCUSDT",
    "universe":"micro_live_usdt_11",
    "days":7,
    "dry_run":true,
    "allow_live_write":false,
    "updated_by":"operator_dry_run"
  }' | jq
```

해석 규칙:
- `kill_condition_state == "observe_only"`면 live write 대상이 아니다.
- `kill_condition_state == "throttle_review"`여도 first-wave에서는 proposal-only다.
- `effective_write_scope == "proposal_only"`면 아직 어떤 stop도 실제 적용되지 않는다.
- `active_manual_override == true`면 새 automation escalation보다 existing lock authority를 따른다.

## 5. Explicit-Arm Live Apply
### 5.1 스크립트
```bash
./.venv/bin/python scripts/run_kill_condition_automation.py \
  --symbol BTCUSDT \
  --universe micro_live_usdt_11 \
  --days 7 \
  --allow-live-write \
  --arm-token "$KILL_CONDITION_AUTOMATION_ARM_TOKEN" \
  --updated-by kill_condition_live_run \
  --unlock-at "2026-03-24T18:30:00+09:00" \
  --no-dry-run
```

### 5.2 API
```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/kill-condition/apply" \
  -H "Content-Type: application/json" \
  -d "{
    \"symbol\":\"BTCUSDT\",
    \"universe\":\"micro_live_usdt_11\",
    \"days\":7,
    \"dry_run\":false,
    \"allow_live_write\":true,
    \"arm_token\":\"$KILL_CONDITION_AUTOMATION_ARM_TOKEN\",
    \"updated_by\":\"operator_live_apply\"
  }" | jq
```

합격 기준:
- `eligible_for_live_write == true`
- `action_applied == true`
- `action_target`이 `close_only` 또는 `kill_switch`
- `safety_state_after.new_entry_allowed == false`

## 6. 적용 후 확인
```bash
curl -s "http://127.0.0.1:8000/execution/safety-state?symbol=BTCUSDT" | jq
```

추가 확인:
- `kill_switch_active`
- `close_only_active`
- `blocking_reason_code`
- `blocking_reason_message`
- `matching_locks`

script report는 기본적으로 `reports/operations/kill_condition_automation/` 아래에 남는다.

## 7. Clear 절차
automation은 first-wave에서 auto-clear를 하지 않는다. clear는 항상 manual control로 한다.

close-only 해제:

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/close-only" \
  -H "Content-Type: application/json" \
  -d '{"active":false,"reason_message":"manual clear after kill-condition review","updated_by":"operator"}' | jq
```

kill-switch 해제:

```bash
curl -s -X POST "http://127.0.0.1:8000/execution/control/kill-switch" \
  -H "Content-Type: application/json" \
  -d '{"active":false,"reason_message":"manual clear after kill-condition review","updated_by":"operator"}' | jq
```

## 8. Audit Trail
- source verdict: `signal_funnel.kill_condition_automation`
- live apply API: `POST /execution/control/kill-condition/apply`
- script wrapper: [run_kill_condition_automation.py](/Users/yumin/Documents/trading/scripts/run_kill_condition_automation.py)
- operator home card: `Kill Condition Inspector`
- manual clear authority: `POST /execution/control/close-only`, `POST /execution/control/kill-switch`
