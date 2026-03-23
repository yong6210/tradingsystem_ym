# Research Promotion Operating Loop Upgrade Context Note

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 왜 이 작업을 하는가
- 지금은 좋은 research candidate가 보여도, 그게 어떤 시험 경로를 거쳐 live promotion으로 올라가는지 운영 루프가 명시적이지 않다.
- 이 공백 때문에 backlog가 쌓이거나, 반대로 promotion review와 research review가 서로 느슨하게 분리된다.
- 이번 라운드 목적은 research를 실제 promotion operating loop에 연결하는 것이다.

## 2. 절대 규칙
1. research와 live authority를 바로 합치지 않는다.
2. test / shadow / probation 단계를 명확히 둔다.
3. governance와 audit trail을 유지한다.
4. compare-only layer에서 시작하되 운영 루프를 실제로 이어야 한다.

## 3A. Item 1 계약 결론
1. operating loop는 `research_backlog / shadow_test_ready / probation_candidate / promotion_followthrough`만 허용한다.
2. output surface는 validation / checklist / dashboard / README로만 제한한다.
3. thin sample, manual review, history attention은 probation/promotion wording을 막는 guardrail로 둔다.

## 3B. Item 2 derivation 결론
1. research action anchor, shadow experiment anchor, watch anchor, promotion anchor, lineage anchor를 분리했다.
2. `promotion_followthrough -> probation_candidate -> shadow_test_ready -> research_backlog` precedence를 고정했다.
3. bias와 target_stage도 state에서 deterministic하게 파생되도록 못 박았다.

## 3C. Item 3 patch 결론
1. validation에는 `research_promotion_operating_loop_available`, `research_promotion_operating_loop_summary`, `## Research Promotion Operating Loop`를 추가하는 방향으로 고정했다.
2. checklist는 non-blocking informational item, dashboard는 `signal_funnel.research_promotion_operating_loop` aggregate summary만 허용한다.
3. README는 `Promotion Lifecycle History` 뒤, `Positive Evidence Expansion` 앞에 operating loop 설명을 넣는 방향으로 고정했다.

## 3D. Item 4 구현 결론
1. alpha research action, shadow experiment, promotion watchlist, promotion stack, lineage context를 묶는 `research_promotion_operating_loop` helper를 구현했다.
2. validation / checklist / dashboard가 같은 `family / loop_state / loop_bias / target_stage` summary를 읽도록 배선했다.
3. 이 layer는 compare-only로 유지했고 approval / sizing / rollout DB authority는 그대로 두었다.

## 3E. Item 5 테스트 및 문서 동기화 결론
1. helper unit test로 `shadow_test_ready`와 `promotion_followthrough` 판정을 고정했다.
2. validation, checklist, dashboard, API smoke에 새 key와 핵심 semantics를 추가했다.
3. README에도 research backlog와 promotion path 사이의 operating bridge 설명을 반영했다.

## 3F. Item 6 self-check 결론
1. `research_promotion_operating_loop`는 validation / checklist / dashboard / README에만 있고 approval / sizing / scanner / candidate row / rollout DB로는 번지지 않는다.
2. alpha research layer, promotion layer, lineage layer와의 역할 분리도 유지된다.
3. 누락, authority 경계 훼손, 과도한 영향 범위, 맥락 노트 위반은 현재 보이지 않는다.
