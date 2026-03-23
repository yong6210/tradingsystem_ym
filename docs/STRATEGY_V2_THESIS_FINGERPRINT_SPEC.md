# Strategy v2 Thesis Fingerprint Spec

최종 갱신: 2026-03-07
상태: Specification frozen

## 1. 목적
- 같은 아이디어를 여러 심볼에 중복 배치하는 문제를 줄인다.
- 포트폴리오를 심볼 기준이 아니라 `thesis cluster` 기준으로 관리한다.

## 2. Fingerprint 구성 필드
기본 fingerprint:
1. `direction`
2. `regime`
3. `strategy_family`
4. `liquidity_narrative`
5. `event_classification`
6. `time_bucket`
7. `correlation_cluster`

## 3. 필드 정의
### direction
- `long`
- `short`

### regime
- `trend`
- `range`
- `shock`
- `transition`

### strategy_family
- `sweep_reversal`
- `trend_continuation`
- `range_rotation`

### liquidity_narrative
허용 값:
1. `pdh_sweep`
2. `pdl_sweep`
3. `session_high_sweep`
4. `session_low_sweep`
5. `equal_highs_sweep`
6. `equal_lows_sweep`
7. `trend_pullback_to_discount`
8. `trend_pullback_to_premium`
9. `range_upper_reject`
10. `range_lower_reject`

### event_classification
- `rejection_confirmed`
- `rejection_tentative`
- `acceptance_confirmed`
- `acceptance_tentative`
- `mixed`

### time_bucket
- 30분 단위 bucket
- 예: `2026-03-07T09:00Z_30m`

### correlation_cluster
- `btc_beta`
- `eth_beta`
- `majors`
- `others`

기본값:
- 상관도 `>= 0.80`면 같은 cluster
- 알트가 BTC와 `>= 0.85`면 `btc_beta`

## 4. 동일 Thesis 판정
아래를 모두 만족하면 같은 thesis:
1. `direction` 동일
2. `regime` 동일
3. `strategy_family` 동일
4. `liquidity_narrative` 동일 또는 동등 클래스
5. `event_classification`이 같은 그룹
6. `time_bucket` 동일 또는 인접 bucket
7. `correlation_cluster` 동일

`event_classification` 그룹:
- rejection 그룹: `rejection_confirmed`, `rejection_tentative`
- acceptance 그룹: `acceptance_confirmed`, `acceptance_tentative`

## 5. 동등 클래스
다음은 동등 narrative로 본다.
1. `pdh_sweep` == `session_high_sweep`
2. `pdl_sweep` == `session_low_sweep`
3. `equal_highs_sweep` == `session_high_sweep`
4. `equal_lows_sweep` == `session_low_sweep`

## 6. Exposure Rules
같은 thesis cluster에서:
1. full-size `1개`만 허용
2. 추가 후보는 `0.50x` 이하
3. active thesis가 2개면 신규 진입 금지

우선 선택:
1. shorter invalidation
2. higher EV
3. lower cost
4. better execution quality
5. deeper liquidity

## 7. 로그 필드
1. `thesis_fingerprint`
2. `thesis_cluster_id`
3. `thesis_cluster_size`
4. `thesis_primary_symbol`
5. `thesis_rejected_reason`

## 8. 구현 메모
1. fingerprint는 plan 생성 시점에 저장
2. scanner와 execution이 같은 fingerprint 함수를 공유
3. active thesis cluster는 30분 기준으로 유지하되, open position이 있으면 cluster를 연장
