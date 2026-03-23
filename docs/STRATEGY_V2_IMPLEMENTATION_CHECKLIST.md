# Strategy v2 Implementation Checklist

최종 갱신: 2026-03-09
상태: Implementation complete (핵심 엔진/전략/검증/운영 contract 완료, 남은 항목은 첫 라이브 운영 사이클 이후 contract pruning optional hold만 존재)

## 1. 상태 엔진
- [x] `transition` regime 정의 추가
- [x] regime 분류 로깅 필드 추가
- [x] `shock/transition` lock 규칙을 엔진에 연결

## 2. Signal Spec
- [x] acceptance/rejection classifier 서비스 추가
- [x] classifier 입력 계약 고정(ATR, reclaim bars, outside closes, dwell time)
- [x] `mixed = no-trade` 하드 게이트 연결

## 3. Strategy Family Routing
- [x] `Sweep Reversal` 분기 추가
- [x] `Trend Continuation Pullback` 분기 강화
- [x] `Range Rotation` 연구 모드 분리
- [x] `OB-only/FVG-only/trendline-led` 차단

## 4. Scoring
- [x] 전략군별 A/B/C 점수표 반영
- [x] `Location`, `Liquidity`, `Reaction`, `Invalidation`, `Session` 세부 점수 필드 저장
- [x] `trendline`을 bonus-only로 축소

## 5. Sizing
- [x] `grade_risk x regime_factor x reaction_factor x thesis_factor x execution_factor` 구현
- [x] thesis active count 기반 size clamp 추가
- [x] `transition=0.00R` 고정

## 6. Exit Engine
- [x] exit reason enum 확장(`target`, `structure_failure`, `time_failure`, `information_failure`)
- [x] 전략군별 time stop 추가
- [x] `rejection -> acceptance` 반전 시 강제 청산 추가
- [x] exit reason 리포트 연동

## 7. Daily Lock
- [x] `-2R`, `3연속 손실`, `A급 2연속 실패` 잠금 구현
- [x] session lock(London/NY) 추가
- [x] unlock cooldown 정책 정의

## 8. Thesis Dedupe
- [x] thesis fingerprint 정의(direction/regime/narrative/time cluster)
- [x] same thesis full-size 1개 규칙 구현
- [x] scanner / execution 모두에 공유 적용

## 9. A-Only Mode
- [x] 운영 모드 설정(`A_ONLY`, `A_PLUS_B`, `RESEARCH`) 추가
- [x] mode별 허용 전략군 / 최대 거래 수 / 동시 노출 적용
- [x] mode별 리포트 분리

## 10. Validation
- [x] A-only vs A+B 비교 리포트
- [x] transition/shock lock 적용 전후 비교
- [x] thesis dedupe 적용 전후 drawdown 비교
- [x] cost x1.5 / slippage x2 stress report
- [x] latency +1 bar / partial fills only / shock concentration stress 축 추가
- [x] stress full-replay replacement assessment 추가
- [x] stress replay writer/runtime lineage 입력 계약 추가
- [x] stress full replay 최소 runner/worker 계약 추가
- [x] full replay writer/runtime lineage와 stress scenario lineage의 lineage writer 연결
- [x] stress full replay prototype worker 실행 경로 연결
- [x] PBO / DSR 검증 설계 추가
- [x] PBO / DSR runtime artifact store contract 추가
- [x] PBO / DSR trial/fold writer 실전 validation 루프 연결
- [x] threshold-sweep family를 runtime proxy writer 위에 확장
- [x] true threshold-sweep runner를 runtime proxy writer와 분리된 lineage로 연결
- [x] replay worker output artifact를 validation stress 비교 payload에 연결
- [x] replay worker output artifact를 deployment recommendation gate에 반영
- [x] threshold lineage winner와 replay-derived worst scenario를 deployment approval template에 직접 교차 표시
- [x] proxy lineage selected-trial warning을 deployment approval template에 직접 고정
- [x] replay output lineage alignment warning을 approval template top-level 문구에 직접 연결
- [x] winner / worst / promotion action one-line summary를 approval template top-level에 추가
- [x] approval template warning code를 운영 playbook의 go/no-go 문구와 1:1 매핑
- [x] approval template top-level 문구를 scanner/ops checklist 배포 판단과 공통 언어로 정렬
- [x] approval template one-line summary를 validation alert payload에도 동일하게 반영
- [x] approval template playbook mapping을 validation alert payload에도 동일하게 반영
- [x] approval template deployment language를 portfolio budget/report 요약에도 직접 반영
- [x] validation alert payload의 deployment language를 alert metrics/ops checklist evidence에도 직접 반영
- [x] validation alert payload의 playbook mapping을 alert metrics evidence에도 직접 반영
- [x] portfolio budget/report summary의 deployment language를 operations checklist portfolio evidence에도 직접 반영
- [x] validation alert payload의 deployment language를 notification formatter summary에도 직접 반영
- [x] validation alert payload의 playbook mapping을 validation_alert_delivery evidence에도 직접 반영
- [x] portfolio budget/report summary의 playbook-style 운영 문구를 직접 반영
- [x] notification formatter summary에 playbook action까지 직접 반영
- [x] validation alert payload의 playbook mapping을 alert test/manual test 경로에도 같은 수준으로 직접 반영
- [x] portfolio budget/report summary의 playbook mapping을 operations checklist portfolio evidence에도 직접 반영
- [x] operations checklist top-level summary에도 playbook-style 운영 문구를 직접 반영
- [x] alert subscribe/manual subscribe 경로에도 deployment/playbook contract를 직접 반영
- [x] validation/operations/report top-level contract 최종 정리
- [x] prototype replay worker -> true market replay runner readiness gate 세분화
- [x] PBO / DSR metric 계산 루프 추가
- [x] proxy writer vs true threshold runner lineage audit를 deployment gate에 반영
- [x] replay-derived stress divergence threshold를 deployment policy에 고정
- [x] true market replay runner 실행 lineage와 threshold lineage를 배포 판정에 함께 연결
- [x] selection-universe count를 full parameter-sweep universe 기준으로 분리 기록
- [x] best-trial Sharpe bias adjustment를 threshold-sweep universe 기준으로 재검증
- [x] true market replay runner output lineage를 selected trial source audit와 deployment summary에 더 직접 결합

## 11. 문서/운영
- [x] `docs/STRATEGY_V2_BLUEPRINT.md` 기준과 코드 계약 1:1 동기화
- [x] 실전 운영 체크리스트를 API/리포트 항목과 연결
- [x] 운영 체크리스트에 session/dead-session guidance 연결
- [x] session/dead-session guidance를 scanner/portfolio 후보 수준까지 승격(`session_guidance`, `session_penalty`, soft penalty only)
- [x] 변경 시 `SELF_CHECK_LOG`와 CHANGELOG 동기화
