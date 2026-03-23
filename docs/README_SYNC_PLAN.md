# README Sync Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 목적
- 현재 `README.md`를 최신 전략 문서와 runtime surface에 맞게 동기화한다.
- 상위 구조 설명은 유지하되, `verification-first`, `operator-first`, `A_ONLY`, `reaction_evidence / location_reference / session_liquidity_reference`의 현재 의미를 README 수준에서 명확히 보이게 만든다.
- README가 전략 본체 문서를 대체하지 않도록, 개념 요약과 authority map 중심으로만 반영한다.

## 2. 작업 범위
1. README와 현재 전략/운영 문서 간 차이점 정리
2. README에 넣을 핵심 개념과 넣지 않을 세부 구현 경계 확정
3. README 구조 반영안 작성
4. `README.md` 수정
5. 필요 시 docs index 또는 관련 링크 정리
6. self-check 및 최종 반영 보고

## 3. 비범위
- strategy v2 core 문서의 추가 개정
- approval / sizing / runtime semantics 변경
- 새 validation report, operator UI, API contract 추가
- README에 세부 bucket 규칙이나 체크리스트 전문을 복사

## 4. 반영 원칙
1. README는 `entrypoint document`로 유지한다.
2. README는 현재 live source-of-truth와 compare-only alias를 구분해서 써야 한다.
3. `BOS/CHoCH/FVG`, `session box`, `outside close`는 README에서도 독립 신호처럼 보이면 안 된다.
4. README는 시스템 구조, operator decision flow, 현재 전략 철학, 주요 runtime surface를 빠르게 이해시키는 데 집중한다.
5. 세부 규칙은 blueprint/playbook/manual로 링크하고 README에는 요약만 둔다.

## 5. 우선 반영 후보
1. 한 줄 전략 정의
2. runtime lifecycle / architecture 흐름
3. execution outcome funnel
4. execution degradation -> operator advisory 연결
5. operator surface에 노출되는 compare-only alias 설명
6. docs index에서 strategy docs 접근 경로 강화

## 6. 참고 기준
- `README.md`
- `docs/STRATEGY_V2_BLUEPRINT.md`
- `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
- `docs/STRATEGY_OPERATING_MANUAL.md`
- `docs/STRATEGY_V2_SESSION_BOX_ALIAS_IMPLEMENTATION_PLAN.md`
- `docs/STRATEGY_V2_REACTION_EVIDENCE_ALIAS_IMPLEMENTATION_PLAN.md`

## 7. 예상 산출물
- 구현 기준선: `docs/README_SYNC_CONTEXT_NOTE.md`
- 구현 체크리스트: `docs/README_SYNC_CHECKLIST.md`
- gap analysis: `docs/README_SYNC_GAP_ANALYSIS.md`
- scope rules: `docs/README_SYNC_SCOPE_RULES.md`
- README 반영안: `docs/README_SYNC_PATCH_PLAN.md`
- 실제 수정 대상: `README.md`
