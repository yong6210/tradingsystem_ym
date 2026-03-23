# Strategy v2 Session Box Absorption Doc Patch Plan

최종 갱신: 2026-03-23
상태: Checklist item 3 draft completed

## 1. 목적
- 세션 박스 전략에서 흡수하기로 한 표현을 기존 핵심 전략 문서에 어떤 문구로 반영할지 결정한다.
- 공통 구조 원칙은 유지하고, 이번 라운드에서는 `session box / outside close / mechanical execution`에 한정된 추가 문구만 고정한다.

## 2. 반영 대상 문서
1. `docs/STRATEGY_V2_BLUEPRINT.md`
2. `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
3. `docs/STRATEGY_OPERATING_MANUAL.md`

## 3. 문서별 반영안
### 3.1 Blueprint
대상 섹션:
1. `## 2. 핵심 원칙`
2. `## 3. 전략 계층`
3. `## 5. 중요도 체계`

추가할 내용:
1. `session box / opening range / premarket range`는 `session liquidity reference`라는 설명
2. `close outside the box`는 `acceptance/rejection evidence candidate`라는 설명
3. `세션 박스 돌파는 location refinement이며 standalone trigger가 아니다`라는 문구

유지할 기존 원칙:
1. `Location first`
2. `Liquidity first`
3. `Reaction over pattern`
4. `Execution zone is secondary`
5. `No-trade is a valid output`

권장 반영 예시:
- 핵심 원칙 또는 전략 계층에 추가:
  - `Session opening range / premarket box can refine location, but does not override HTF location or liquidity narrative.`
- 중요도 체계 역할 정의에 추가:
  - `Outside-close relative to session box: acceptance/rejection evidence candidate, not standalone approval.`

### 3.2 A-Only Playbook
대상 섹션:
1. `## 4. 진입 전 10문항`
2. `## 5. A급 최소 기준`
3. `## 7. 금지 규칙`

추가할 내용:
1. `session box high/low`는 intraday liquidity reference라는 운영 메모
2. `outside close`는 `reaction evidence`로만 읽는다는 문구
3. `기계적 실행`은 유지하되, checklist override 없이 실행한다는 문구

유지/강화할 금지 문구:
1. `1m breakout-only`
2. `session box breakout-only`
3. `indicator stack-led`
4. `고승률이면 된다`는 사고
5. `저RR 고빈도 수익 모델`

권장 반영 예시:
- 진입 전 체크 아래 운영 메모:
  - `세션 박스 돌파는 intraday liquidity hint일 뿐이며, HTF 위치/유동성 narrative 없이 단독 진입 근거가 아니다.`
- 금지 규칙에 보강:
  - `session box outside-close only`
  - `small-win high-frequency model`

### 3.3 Operating Manual
대상 섹션:
1. 기존 `8.7A External Vocabulary Translation`
2. 필요 시 `acceptance / rejection` 운영 해석 문단

추가할 내용:
1. `session box / opening range / premarket box -> session liquidity reference`
2. `outside close -> acceptance evidence candidate`
3. `failed outside close / return inside -> rejection evidence candidate`
4. `mechanical execution`은 `operator checklist compliance`라는 해석

반영 방식:
1. 이미 존재하는 `8.7A`를 확장하고, 같은 주제의 신규 소절은 만들지 않는다.
2. `approval`, `risk`, `sizing` source-of-truth는 계속 기존 contract를 유지한다고 명시한다.

권장 반영 예시:
- `Session box vocabulary does not create a separate execution authority; it only refines session liquidity interpretation.`
- `Outside close beyond a session box is evidence, not approval. Failed acceptance remains a valid no-trade or reversal context depending on HTF location.`

## 4. 이번 단계에서 일부러 하지 않는 것
1. core 문서 본문 직접 수정
2. runtime alias 추가
3. compare-only surface 구현
4. validation/test 변경

## 5. 다음 단계 준비물
1. 위 반영안 중 실제 본문에 넣을 문구 선택
2. 기존 공통 흡수 문서와 겹치는 문구를 제거할지 판단
3. 운영 매뉴얼에서는 기존 `8.7A` 확장으로 충분한지 확인
