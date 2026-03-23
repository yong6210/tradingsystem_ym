# Strategy v2 Exit Event Schema

최종 갱신: 2026-03-07
상태: Schema frozen

## 1. 목적
- 청산을 단순 `TP/SL`이 아니라 `왜 나갔는가` 기준으로 기록한다.
- execution quality와 전략 검증에서 exit reason을 1급 지표로 사용한다.

## 2. Exit Reason Enum
허용 값:
1. `target_tp1`
2. `target_tp2`
3. `target_tp3`
4. `stop_loss`
5. `structure_failure`
6. `time_failure`
7. `information_failure`
8. `manual_flatten`
9. `risk_lock_flatten`
10. `session_end_flatten`

## 3. Reason 정의
### structure_failure
- protected high/low 붕괴
- impulse origin 깊은 재침범
- range boundary acceptance로 mean-reversion thesis 무효

### time_failure
- 전략군별 허용 bar 수 안에 follow-through 없음
- `Sweep Reversal`: `3~5 bars`
- `Trend Continuation`: `5~8 bars`
- `Range Rotation`: `3 bars`

### information_failure
- initial thesis가 `rejection -> acceptance`로 반전
- classifier가 `mixed` 또는 반대 classification으로 재분류
- 유동성 narrative가 invalidated

## 4. Exit Event Payload
필수 필드:
1. `plan_id`
2. `symbol`
3. `strategy_family`
4. `exit_reason`
5. `exit_ts`
6. `exit_price`
7. `remaining_qty`
8. `realized_r`
9. `held_bars`
10. `classification_before_exit`
11. `classification_after_exit`
12. `trigger_detail`

선택 필드:
1. `slippage_bps`
2. `latency_ms`
3. `fees`
4. `notes`

## 5. Trigger Detail Schema
### structure_failure
- `broken_level`
- `broken_by_close_count`
- `displacement_against_atr`

### time_failure
- `max_allowed_bars`
- `actual_held_bars`
- `progress_to_target_pct`

### information_failure
- `old_classification`
- `new_classification`
- `narrative_invalidated`
- `mixed_score`

## 6. 저장 규칙
1. 부분 청산은 `target_tp1/2/3`
2. 최종 청산은 반드시 하나의 `final_exit_reason`을 가진다
3. 부분 청산 후 남은 포지션이 `information_failure`면 최종 reason은 `information_failure`
4. 동일 bar에서 여러 트리거가 충돌하면 우선순위는:
   1. `risk_lock_flatten`
   2. `information_failure`
   3. `structure_failure`
   4. `time_failure`
   5. `target_tp*`

## 7. 리포트 연동
리포트에 반드시 포함:
1. exit reason 분포
2. strategy family별 exit reason 분포
3. `information_failure` 비율
4. `time_failure` 비율
5. target-based exit와 forced exit 비율

## 8. 구현 메모
1. exit reason은 outcome 저장 시점과 execution report 생성 시점에 동일하게 해석돼야 한다
2. 수동 종료도 명시적으로 기록한다
3. exit reason은 validation report의 하위 섹션으로 노출한다
