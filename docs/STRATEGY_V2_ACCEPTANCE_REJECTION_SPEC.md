# Strategy v2 Acceptance Rejection Spec

최종 갱신: 2026-03-07
상태: Signal specification frozen

## 1. 목적
- sweep 이후 움직임을 `rejection`, `acceptance`, `mixed`로 일관되게 분류한다.
- reversal 전략과 continuation 전략이 같은 이벤트를 반대로 해석하지 않게 만든다.

## 2. 입력 정의
필수 입력:
1. swept level
2. 최근 `n=3` bars close/open/high/low
3. `ATR(5m)`
4. reclaim 여부
5. inefficiency/FVG 생성 여부
6. retest hold 여부
7. level 바깥 체류 시간

## 3. Rejection 판정
### 하드 조건
1. sweep 후 `1~3 bar` 안에 level reclaim
2. 반대 방향 displacement `>= 1.2 x ATR(5m)`
3. reclaim 이후 swept level 바깥 close 수 `<= 1`

### 보조 조건
1. 반대 방향 inefficiency/FVG 생성
2. retest hold 성공
3. swept level 바깥 체류 시간이 짧음

### 판정
- 하드 조건 3개 모두 충족 + 보조 조건 1개 이상: `rejection_confirmed`
- 하드 조건 2개 충족: `rejection_tentative`
- 그 외: rejection 아님

## 4. Acceptance 판정
### 하드 조건
1. sweep 후 level 바깥에서 `2 bar 이상 close`
2. retest 후 continuation
3. reclaim 실패

### 보조 조건
1. breakout 방향 displacement 유지
2. 반대 반응 약함
3. level 바깥 체류 시간이 김

### 판정
- 하드 조건 3개 모두 충족 + 보조 조건 1개 이상: `acceptance_confirmed`
- 하드 조건 2개 충족: `acceptance_tentative`
- 그 외: acceptance 아님

## 5. Mixed 판정
다음이면 `mixed`:
1. reclaim은 있었지만 follow-through 부족
2. acceptance와 rejection 신호가 동시에 강함
3. body progress보다 wick noise가 큼
4. retest가 양방향 모두 실패

`mixed`는 기본 `no-trade`다.

## 6. 점수화
### Rejection Score
1. reclaim speed `0~20`
2. displacement strength `0~20`
3. close quality `0~15`
4. follow-through `0~15`
5. inefficiency creation `0~10`
6. dwell time penalty adjusted `0~10`
7. session quality `0~10`

판정:
- `75+`: `rejection_confirmed`
- `60~74`: `confirm_only`
- `<60`: `mixed/no-trade`

### Acceptance Score
1. close beyond level `0~20`
2. hold beyond level `0~20`
3. retest success `0~15`
4. continuation displacement `0~15`
5. opposite reclaim failure `0~15`
6. dwell time `0~10`
7. session quality `0~5`

판정:
- `70+`: `acceptance_confirmed`
- `55~69`: `breakout_bias_only`
- `<55`: `mixed/no-trade`

## 7. 전략 연동 규칙
1. `rejection_confirmed`면 `Sweep Reversal` 후보
2. `acceptance_confirmed`면 reversal 금지
3. `mixed`면 reversal/continuation 모두 금지
4. `Trend Continuation`은 acceptance가 아니라 `healthy pullback + continuation`로 별도 판정한다.

## 8. 로그 필드
저장 권장 필드:
1. `swept_level_type`
2. `reclaim_bars`
3. `displacement_atr`
4. `outside_close_count`
5. `dwell_time_bars`
6. `retest_hold`
7. `inefficiency_created`
8. `rejection_score`
9. `acceptance_score`
10. `classification`

## 9. 구현 메모
1. 판정은 바 마감 기준으로만 계산한다.
2. intrabar wick만으로 `confirmed`를 주지 않는다.
3. same-bar 재분류는 금지하고, 다음 bar close에서만 갱신한다.
