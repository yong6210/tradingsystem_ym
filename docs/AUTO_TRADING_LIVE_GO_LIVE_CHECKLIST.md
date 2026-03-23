# Auto Trading Live Go-Live 체크리스트

최종 갱신: 2026-03-09

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
- [ ] `trend_continuation`만 허용
- [ ] `BTCUSDC`, `ETHUSDC`만 허용
- [ ] `A_ONLY`만 허용
- [ ] `max concurrent positions`가 1~2로 제한됨
- [ ] `max daily new entries`가 낮게 고정됨
- [ ] `GET /execution/safety-state`에서 `kill_switch_active == false`
- [ ] `GET /execution/safety-state`에서 `close_only_active == false`
- [ ] `POST /validation/report` 결과가 최소 `MANUAL_REVIEW` 이상이고, 운영자가 승인함
- [ ] `POST /operations/checklist` 결과가 신규 진입 가능 상태를 가리킴
- [ ] `GET /execution/operator-dashboard`에서 `recent_reconciliation_summary.healthy == true`

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
- unresolved mismatch가 있으면 “조금 더 지켜본다”가 아니라 즉시 `close-only` 또는 `kill-switch`를 고려한다.
