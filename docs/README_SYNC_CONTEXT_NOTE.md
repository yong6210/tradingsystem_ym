# README Sync Context Note

최종 갱신: 2026-03-23
상태: Final review verified, README synced

## 1. 왜 이 작업을 하는가
- 현재 `README.md`는 상위 구조는 잘 설명하지만, 최근 전략 흡수 작업과 runtime alias 구현까지는 아직 동기화되지 않았다.
- 특히 `top-down is structural`, `session reference refines, not overrides`, `reaction_evidence`, `location_reference`, `session_liquidity_reference` 같은 최신 언어가 README에는 없다.
- README는 신규 운영자와 기여자가 가장 먼저 읽는 문서이므로, 전략 본문을 전부 복사하지 않고 핵심 흐름만 정확히 드러내야 한다.

## 2. 절대 규칙
1. README는 여전히 `verification-first`, `operator-first` entrypoint여야 한다.
2. README는 final source-of-truth를 잘못 바꾸면 안 된다.
3. `POST /validation/report`와 `POST /operations/checklist`가 최종 승인 surface라는 점을 유지한다.
4. `reaction_evidence`, `location_reference`, `session_liquidity_reference`는 compare-only / readability alias로만 설명한다.
5. `BOS/CHoCH/FVG`, `session box`, `outside close`를 standalone signal처럼 쓰지 않는다.
6. README는 전략 철학을 요약하지만, 세부 규칙은 strategy docs로 링크한다.

## 3. README에 꼭 들어가야 할 것
1. 현재 전략 한 줄 요약
2. runtime architecture / lifecycle 흐름
3. outcome funnel
4. execution degradation이 operator advisory와 어떻게 연결되는지
5. scanner / portfolio surface에서 읽히는 compare-only alias의 의미

## 4. README에 넣지 않을 것
1. 세부 bucket derivation 표 전체
2. strategy playbook 10문항 전문
3. acceptance/rejection spec 전문
4. implementation checklist 전문
5. experimental branch의 세부 threshold 값

## 5. 참고 포인트
- `docs/STRATEGY_V2_BLUEPRINT.md`의 전략 철학
- `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`의 운영 해석
- `docs/STRATEGY_OPERATING_MANUAL.md`의 external vocabulary translation
- 현재 `README.md`의 authority map / core flow / operator surfaces
