# Persistent Promotion Lifecycle History Upgrade Patch Plan

최종 갱신: 2026-03-23

## 1. 목적
- persistent lifecycle history를 validation / checklist / dashboard / README에 어떤 wording과 shape로 넣을지 먼저 고정한다.
- durable store와 runtime explanation surface를 분리한다.

## 2. validation 반영
추가 필드:
1. `promotion_lifecycle_history_available`
2. `promotion_lifecycle_history_summary`

추가 섹션:
1. `## Promotion Lifecycle History`

최소 표기 필드:
1. `history_state`
2. `family`
3. `latest_event_type`
4. `latest_event_ts`
5. `event_count_30d`
6. `recent_transitions`
7. `summary`
8. `reason_codes`

## 3. checklist 반영
새 item:
1. `promotion_lifecycle_history`

규칙:
1. blocking item이 아니라 informational item으로 유지한다.
2. `history_attention_required`는 `WARN`까지만 허용한다.
3. history summary는 current approval authority를 대체하지 않는다.

## 4. dashboard 반영
허용 위치:
1. `signal_funnel.promotion_lifecycle_history`

비허용 위치:
1. recent intents
2. approval snapshot
3. scanner row
4. `/portfolio/budget` candidate row

## 5. README 반영
위치:
1. `Auto Promotion Rollout Execution` 뒤
2. `Positive Evidence Expansion` 앞

핵심 문구:
1. persistent history는 current posture가 아니라 lineage layer다.
2. first implementation은 immutable event insert와 recent aggregate summary까지만 다룬다.
3. approval / sizing / rollout DB authority는 여전히 비범위다.

## 6. patch 방향
1. 새 persistent model / repository / service를 추가한다.
2. strategy engine은 promotion stack에서 history row candidate를 만들고 append-only insert를 시도한다.
3. validation / checklist / dashboard는 aggregate history summary만 읽는다.
4. persistence failure는 runtime summary를 깨지 않게 soft-fail 처리한다.
