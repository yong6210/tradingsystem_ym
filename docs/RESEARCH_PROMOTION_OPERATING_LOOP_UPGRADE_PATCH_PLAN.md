# Research Promotion Operating Loop Upgrade Patch Plan

최종 갱신: 2026-03-23

## 1. validation 반영
추가 필드:
1. `research_promotion_operating_loop_available`
2. `research_promotion_operating_loop_summary`

추가 섹션:
1. `## Research Promotion Operating Loop`

최소 표기 필드:
1. `family`
2. `loop_state`
3. `loop_bias`
4. `target_stage`
5. `recommended_action`
6. `shadow_experiment_id`
7. `watchlist_ready`
8. `summary`
9. `reason_codes`

## 2. checklist 반영
새 item:
1. `research_promotion_operating_loop`

규칙:
1. blocking item이 아니라 informational item으로 유지한다.
2. `research_backlog`와 `shadow_test_ready`는 `PASS/WARN` informational review만 허용한다.
3. 이 summary는 approval authority를 대체하지 않는다.

## 3. dashboard 반영
허용 위치:
1. `signal_funnel.research_promotion_operating_loop`

비허용 위치:
1. recent intents
2. approval snapshot
3. scanner row
4. `/portfolio/budget` candidate row

## 4. README 반영
위치:
1. `Promotion Lifecycle History` 뒤
2. `Positive Evidence Expansion` 앞

핵심 문구:
1. research backlog와 promotion stack을 같은 loop language로 묶는다.
2. first implementation은 compare-only loop summary까지만 다룬다.
3. approval / sizing / rollout DB authority는 여전히 비범위다.
