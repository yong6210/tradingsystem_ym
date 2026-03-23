# Strategy v2 Method Absorption Doc Patch Plan

최종 갱신: 2026-03-23
상태: Checklist item 3 draft completed

## 1. 목적
- 외부 방법론에서 흡수하기로 한 개념을 기존 핵심 전략 문서에 어떤 표현으로 반영할지 결정한다.
- core 문서 수정 전, 추가 문구와 유지할 금지 문구를 먼저 고정한다.

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
1. `Top-down means HTF location first, LTF execution second` 문구
2. `session box / opening range / premarket range`는 `location refinement` 또는 `session liquidity reference`라는 설명
3. `BOS/CHoCH`는 독립 신호가 아니라 `continuation/reaction evidence`라는 설명
4. `1m close outside level`은 `acceptance/rejection evidence candidate`라는 설명

유지할 금지 문구:
1. `Execution zone is secondary`
2. `OB/FVG는 실행 도구이지 전략 자체가 아니다`
3. `No-trade is a valid output`

권장 반영 예시:
- 핵심 원칙에 추가:
  - `Top-down is structural, not pattern-led: HTF location and liquidity come first, while LTF structure only refines execution.`
- 전략 계층 `Layer 2. Location`에 추가:
  - `session opening range / premarket box (as session liquidity reference only)`
- 중요도 체계 역할 정의에 추가:
  - `BOS/CHoCH: 반응 해석 보조 증거`

### 3.2 A-Only Playbook
대상 섹션:
1. `## 4. 진입 전 10문항`
2. `## 5. A급 최소 기준`
3. `## 7. 금지 규칙`

추가할 내용:
1. HTF level 도달 후 LTF는 `확인 레이어`라는 운영 문구
2. `session box breakout`은 단독 진입 사유가 아니라는 문구
3. `1m CHoCH/BOS`는 `confirm only` 또는 `reaction evidence`로만 쓴다는 문구

유지/강화할 금지 문구:
1. `OB-only`
2. `FVG-only`
3. `trendline-led`
4. 추가 권장:
   - `1m breakout-only`
   - `box breakout-only`
   - `indicator stack-led`

권장 반영 예시:
- 진입 전 10문항 아래 운영 메모 추가:
  - `하위 시간대 구조는 진입 확인용이다. 상위 위치와 유동성 narrative 없이 1m 구조만으로 진입하지 않는다.`
- 금지 규칙에 추가:
  - `1m breakout-only`
  - `session box breakout-only`
  - `indicator stack-led`

### 3.3 Operating Manual
대상 섹션:
1. `8.7 Acceptance/Rejection Classifier 운영 규칙`
2. 신규 소절 후보: `8.7A External Vocabulary Translation`

추가할 내용:
1. 운영자가 외부 용어를 봤을 때 어떤 runtime contract로 읽어야 하는지 명시
2. `BOS/CHoCH -> reaction evidence`
3. `FVG/OB -> execution zone`
4. `session box -> session liquidity reference`
5. `1m close outside level -> acceptance candidate, not standalone approval`

권장 반영 예시:
- 신규 소절:
  - `외부 방법론의 BOS/CHoCH는 운영 해석상 독립 신호가 아니라 reaction evidence로만 읽는다.`
  - `session box breakout은 location 보조 정보이며, deployment/playbook/risk gating을 우회하지 않는다.`

## 4. 이번 단계에서 일부러 하지 않는 것
1. `docs/STRATEGY_V2_BLUEPRINT.md` 본문 직접 수정
2. `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md` 본문 직접 수정
3. runtime contract나 테스트 추가

## 5. 다음 단계 준비물
1. 위 반영안 중 어떤 문구를 실제 본문에 넣을지 선택
2. 금지 규칙 추가가 기존 문서 톤과 충돌하지 않는지 확인
3. 운영 매뉴얼에서는 새 소절 추가 vs 기존 소절 확장 중 하나를 결정
