# Auto Trading Live Go-Live 체크리스트

최종 갱신: 2026-04-17

## 1. 범위
- 이 문서는 `SHADOW -> PAPER -> MICRO_LIVE -> LIVE` 전환 전 점검 항목을 고정한다.
- 기본 원칙: `MICRO_LIVE` 전환 전까지는 신규 진입보다 `approval / intent / reconcile / safety`의 안정성이 먼저다.

## 2. 공통 전제
- `chart score != deployment approval`
- `chart plan != live order instruction`
- source-of-truth:
  - runtime operator 상태: `GET /execution/operator-dashboard`
  - 브라우저 operator 표면: `GET /execution/operator-ui`
  - 최종 승인: `POST /validation/report`, `POST /operations/checklist`
  - safety/lock 상태: `GET /execution/safety-state`

## 3. 환경 점검
- [ ] `BINANCE_API_KEY`, `BINANCE_API_SECRET` 설정 완료
- [ ] `BINANCE_TRADE_LIVE_ENABLED` 의도한 값으로 설정 완료
- [ ] `pip install -e '.[integration]'`로 user-stream 의존성 설치 완료
- [ ] Discord/Telegram/Push 중 최소 1개 alert channel 동작 확인
- [ ] 서버 시간/UTC 저장 규칙 확인
- [ ] DB 백업/복구 절차 확인
- [ ] 테스트는 항상 temp DB로만 돌고, `pytest`가 실 [trading.db](/Users/yumin/Documents/trading/trading.db)를 건드리지 않음 (`tests/conftest.py`, `DATABASE_URL` 격리 확인)

## 4. SHADOW 진입 기준
- [ ] `GET /execution/operator-dashboard`에서 `new_entries_allowed` 계산이 정상
- [ ] `GET /execution/operator-ui`에서 dashboard/checklist/validation 요약이 동시에 표시됨
- [ ] `POST /execution/approve-plan`가 plan별로 결정적 결과를 반환
- [ ] `POST /execution/order-intents`가 `SUBMIT / SKIP_*`를 일관되게 기록
- [ ] duplicate thesis, stale plan, manual/shadow/blocked 경로 테스트 완료
- [ ] `GET /alerts/metrics`에서 validation alert 경로 정상

SHADOW exit criteria:
- [ ] blocked reason logging이 충분히 쌓임
- [ ] intent decision이 runtime state와 충돌하지 않음
- [ ] approval/intent replay debugging이 가능함

## 5. PAPER 진입 기준
- [ ] paper adapter에서 `partial fill / timeout / cancel` 테스트 통과
- [ ] `POST /execution/submit`가 paper submit 경로에서만 동작
- [ ] order lifecycle과 position lifecycle이 함께 추적됨
- [ ] `ENTRY -> PARTIAL_EXIT -> CLOSED`와 order ack/fill/cancel 경로 회귀 통과
- [ ] restart 이후 state restore / idempotent submit 확인

PAPER exit criteria:
- [ ] state machine 오류 없음
- [ ] stop/tp attach 실패가 경고/lock 경로로 잡힘
- [ ] paper/live-like drift가 허용 범위 내
- [ ] 최근 reconciliation mismatch가 낮음

## 6. MICRO_LIVE 진입 기준
- [ ] 실사용 live 계약은 `BTCUSDC`만 허용
- [ ] 실사용 live family는 `sweep_reversal`만 허용
- [ ] 실사용 live variant는 `LIMIT`만 허용
- [ ] 방향 계약은 `BTCUSDC LONG|SHORT`
- [ ] `trend_continuation + LIMIT`는 별도 `trend proof lane`으로만 추적하고 아직 live 제출 계약에는 넣지 않음
- [ ] `A_ONLY`만 허용
- [ ] `max concurrent positions`가 1~2로 제한됨
- [ ] 현재 canary pacing이 `1 concurrent position` 기준임을 이해함
- [ ] `max daily new entries == 0`이면 일일 상한이 꺼진 상태이고, 다음 진입은 포지션 종료 후 approval / safety / reconciliation 재평가로만 열림을 이해함
- [ ] `GET /execution/safety-state`에서 `kill_switch_active == false`
- [ ] `GET /execution/safety-state`에서 `close_only_active == false`
- [ ] `POST /validation/report` 결과가 최소 `MANUAL_REVIEW` 이상이고, 운영자가 승인함
- [ ] `POST /operations/checklist` 결과가 신규 진입 가능 상태를 가리킴
- [ ] `GET /execution/operator-dashboard`에서 `recent_reconciliation_summary.healthy == true`
- [ ] `runtime_decision_band == AMBER_CONDITIONAL`
- [ ] `runtime_effective_action == conditional_micro_live_signoff`
- [ ] `runtime_allowed_reopen_scope == MICRO_LIVE_ONLY`
- [ ] `runtime_preflight_summary.status == READY_FOR_MICRO_LIVE`
- [ ] `runtime_operator_signoff_summary.status == ready_for_manual_micro_live_signoff`
- [ ] `runtime_operator_signoff_summary.contract_scope == limit_only`
- [ ] 후보가 `auto_trading_micro_live_allowed_symbols`, `auto_trading_micro_live_allowed_families`, `auto_trading_micro_live_allowed_sessions` 계약 안에 있음
- [ ] `runtime_self_heal_summary`에 반복 stale cleanup / stale unblock 이상 징후가 없음
- [ ] 운영 순서를 `preflight -> signoff review -> order-intents(MICRO_LIVE) -> submit(live=true)`로만 따른다
- [ ] `live_eligible_post_patch_closed_trade_count >= 15`
- [ ] `live_eligible_post_patch_sample_summary.replay_max_drawdown_r < 4.5`
- [ ] `live_eligible_post_patch_sample_summary.replay_p5_r >= -1.05`
- [ ] `live_eligible_post_patch_sample_summary.stop_loss_share < 0.45`
- [ ] `live_eligible_post_patch_sample_summary.worst_loss_streak < 5`
- [ ] `runtime_live_contract_scope.proof_source`가 현재 gate source를 명확히 보여줌
- [ ] `live_execution_post_patch_closed_trade_count < 5`인 bootstrap 구간에서는 `live_eligible_post_patch_sample_summary`를 gate proof로 사용하고 있음을 이해함
- [ ] `historical_execution_contract_proof_summary`는 advisory-only historical context이며, live gate count로 합산하지 않음을 이해함
- [ ] `historical_execution_contract_proof_summary`가 `BTCUSDC + sweep_reversal + LIMIT` 계약의 장기 과거 성적을 별도 보여준다는 점을 확인함
- [ ] `historical_walk_forward_execution_contract_proof_summary`는 candle-by-candle advisory walk-forward lane이며, `actual execution subset`과 별도 증거라는 점을 이해함
- [ ] `historical_walk_forward_execution_contract_proof_summary.baseline_ts / simulation_start_ts / simulation_end_ts`로 시뮬레이션 구간을 확인함
- [ ] `historical_walk_forward_strategy_proof_summary`는 `BTCUSDC` 중심 raw candle strategy-level replay lane이며, large-sample 전략 적합성 확인용이지 live execution gate count로 직접 합산하지 않음을 이해함
- [ ] `trend_proof_post_patch_closed_trade_count`와 `trend_proof_candidate_summary`를 별도 관찰 대상으로 유지함
- [ ] `historical_walk_forward_trend_proof_summary`는 `trend_continuation + LIMIT`의 advisory walk-forward lane이며 live gate count로 합산하지 않음을 이해함
- [ ] `live_family_cluster_window_cap_reached` blocker 없음
- [ ] `live_family_loss_cooldown_active` blocker 없음
- [ ] `run_paper_candidate_drill.py` 기준 `family_cluster_guard_summary.active_families`가 비어 있음
- [ ] same-window alt reversal cluster가 PAPER lineage 표본을 다시 악화시키지 않도록 family guard가 clear 상태임
- [ ] major macro blackout (`FOMC`, `CPI`, `NFP`) 일정이 현재 분기 기준으로 반영돼 있고, blackout 동안 신규 `MICRO_LIVE` 진입이 막히는 구조를 이해함

MICRO_LIVE exit criteria:
- [ ] fee/slippage 포함 후 기대치 유지
- [ ] fill quality와 time failure 비율이 허용 범위 내
- [ ] critical incident 없음
- [ ] close-only / kill-switch / lock 동작 실전 검증 완료

## 7. LIVE 확대 기준
- [ ] family별 recent quality score가 안정적
- [ ] reconciliation mismatch가 누적되지 않음
- [ ] user-stream stale / missing stop / fill gap 사고가 해결됨
- [ ] threshold lineage / replay-backed approval 기준이 운영상 충분히 해석 가능
- [ ] operator runbook이 실제 운영 과정과 어긋나지 않음
- [ ] `runtime_decision_band == AMBER_CONDITIONAL` 또는 `GREEN_PROCEED`
- [ ] `runtime_effective_action == conditional_full_live_signoff` 또는 `proceed_to_operator_signoff`
- [ ] `runtime_allowed_reopen_scope == MICRO_LIVE_OR_LIVE`
- [ ] `runtime_preflight_summary.status == READY_FOR_MICRO_LIVE`
- [ ] `runtime_operator_signoff_summary.status == ready_for_manual_full_live_signoff` 또는 `ready_for_operator_signoff`
- [ ] `live_eligible_post_patch_closed_trade_count >= 30`
- [ ] `live_eligible_post_patch_sample_summary.replay_max_drawdown_r < 4.5`
- [ ] `live_eligible_post_patch_sample_summary.replay_p5_r >= -1.05`
- [ ] `live_eligible_post_patch_sample_summary.stop_loss_share < 0.40`
- [ ] `live_eligible_post_patch_sample_summary.worst_loss_streak < 5`
- [ ] `live_execution_post_patch_closed_trade_count >= 5`여서 더 이상 bootstrap proof가 아님
- [ ] `trend_proof_post_patch_closed_trade_count >= 5` 또는 추세장 proof 부재를 운영자가 명시적으로 받아들임
- [ ] `live_family_cluster_window_cap_reached` blocker 없음
- [ ] `live_family_loss_cooldown_active` blocker 없음
- [ ] PAPER lineage drill의 `family_cluster_guard_summary.active_families`가 비어 있음

## 8. 즉시 NO-GO 조건
- [ ] `validation/report`가 `NO_GO`
- [ ] `operations/checklist`가 신규 진입 차단 상태
- [ ] `GET /execution/safety-state`에 active global kill-switch 존재
- [ ] unresolved reconciliation critical mismatch 존재
- [ ] missing stop order on live position
- [ ] repeated user-stream stale
- [ ] exchange auth/order API degraded
- [ ] slippage anomaly / fee anomaly

## 9. 첫 라이브 세션 전 명령 순서
```bash
curl -s "http://127.0.0.1:8000/health/ready" | jq
curl -s "http://127.0.0.1:8000/execution/operator-dashboard?universe=usdc_perp_top30&days=7" | jq
curl -s "http://127.0.0.1:8000/execution/safety-state" | jq
curl -s -X POST "http://127.0.0.1:8000/validation/report?symbol=BTCUSDC" | jq
curl -s -X POST "http://127.0.0.1:8000/operations/checklist?symbol=BTCUSDC" | jq
curl -s "http://127.0.0.1:8000/alerts/metrics?days=7&write_report=false" | jq
```

자동 점검 스크립트:
```bash
./.venv/bin/python scripts/run_micro_live_preflight.py --symbol BTCUSDC --days 7
```

## 10. 운영 원칙
- live 전환은 기능 완성 여부가 아니라 `reconciliation / safety / operator visibility`가 충분한지로 판단한다.
- `MICRO_LIVE`는 검증 단계다. 수익 극대화 모드가 아니다.
- `legacy` 전체 replay와 full `post-patch` cohort는 계속 advisory truth로 유지한다. 실제 live go/no-go는 `live_eligible_post_patch_sample_summary`를 따로 본다.
- 현재 live 계약은 `BTCUSDC/ETHUSDC + sweep_reversal + LIMIT`다. `CONFIRM` / `SWEEP_CONFIRM`은 paper 또는 research로만 유지한다.
- raw BTC strategy proof 기준 현재 우선순위는 `BTCUSDC sweep_reversal LIMIT`이다. `ETHUSDC`는 advisory/proof 비교용으로만 남기고, `CONFIRM`은 운영 계약에서 제외한다.
- `trend_continuation + LIMIT`는 live 계약이 아니라 `trend proof lane`이다. proof가 쌓이기 전에는 실거래 판단 근거로 과신하지 않는다.
- `MICRO_LIVE`는 `limit_only post-patch 15+`, `maxDD < 4.5R`, `p5 >= -1.05`, `stop_loss_share < 45%`, `worst_loss_streak < 5`일 때만 검토한다.
- `FULL LIVE`는 `limit_only post-patch 30+`, `maxDD < 4.5R`, `p5 >= -1.05`, `stop_loss_share < 40%`, `worst_loss_streak < 5`를 따로 충족할 때만 검토한다.
- `actual execution subset`이 `5 distinct plans`를 넘기기 전까지는 live gate proof가 bootstrap 단계라는 점을 운영자가 항상 인지한다.
- `historical execution contract proof`는 빠르게 쌓이는 advisory lane이다. `actual execution subset`이 얇을 때 참고용으로만 쓰고, live reopen gate source로 직접 승격하지 않는다.
- `historical walk-forward execution proof`는 실제 과거 캔들을 순차 replay한 advisory lane이다. `actual execution subset`을 대체하지는 않지만, live 계약이 너무 느리게 쌓일 때 `BTCUSDC` 계약 적합성을 더 빨리 읽는 용도로 쓴다.
- `historical walk-forward strategy proof`는 `BTCUSDC` 중심 raw candle strategy-level replay lane이다. large-sample 전략 edge 확인용으로 쓰고, `actual execution subset`과 같은 품질로 해석하면 안 된다.
- `historical walk-forward trend proof`는 `BTCUSDC/ETHUSDC + trend_continuation + LIMIT`를 같은 방식으로 순차 replay한 lane이다. count가 0이면 추세 lane은 아직 미증명으로 본다.
- unresolved mismatch가 있으면 “조금 더 지켜본다”가 아니라 즉시 `close-only` 또는 `kill-switch`를 고려한다.
