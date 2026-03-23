# Strategy v2 Method Absorption Plan

최종 갱신: 2026-03-23
상태: Item 1 completed, remaining items pending approval flow

## 1. 목적
- 외부 트레이딩 방법론에서 `시장 구조 / 유동성 / 실행 규율`처럼 재사용 가치가 있는 요소만 흡수한다.
- 현재 `strategy v2`의 핵심 축인 `상태 -> 위치 -> 유동성 -> 반응 -> 실행` 구조를 유지한다.
- 새 개념을 곧바로 라이브 확대 적용하지 않고, 문서/계약/검증 순서로만 반영한다.

## 2. 작업 범위
1. 채택 원칙 / 배제 원칙 확정
2. 외부 방법론을 `strategy v2` 언어로 매핑
3. 문서 반영안 작성
4. runtime feature / contract 후보 정리
5. 검증 항목과 비교 실험안 정의
6. 구현 또는 문서 반영 실행
7. self-check 및 최종 적용 보고

## 3. 비범위
- 새 라이브 전략군 추가
- short-term influencer rule의 즉시 채택
- `승률` 중심의 단기 확대 해석
- `1m breakout` 단독 전략 전환

## 4. 현재 결정
- 이번 단계에서는 `좋은 표현`이 아니라 `정량화 가능한 규칙`만 흡수 대상으로 본다.
- 현재 표본이 얇고 execution advisory가 `manual_review` 상태이므로, 새 개념은 우선 문서/실험 계층에만 반영한다.

## 5. 완료 기준
- 채택할 개념과 배제할 개념이 문서상 명시된다.
- 이후 항목은 위 원칙을 깨지 않는 범위에서만 진행한다.
- 검증 기준은 기존처럼 `EV / p5 / max drawdown / 운영 적합성` 중심으로 유지한다.

## 6. 현재 산출물
- 원칙 기준선: `docs/STRATEGY_V2_METHOD_ABSORPTION_CONTEXT_NOTE.md`
- 용어 매핑: `docs/STRATEGY_V2_METHOD_ABSORPTION_MAPPING.md`
- 문서 반영안: `docs/STRATEGY_V2_METHOD_ABSORPTION_DOC_PATCH_PLAN.md`
- runtime 후보: `docs/STRATEGY_V2_METHOD_ABSORPTION_RUNTIME_CANDIDATES.md`
- 비교 실험안: `docs/STRATEGY_V2_METHOD_ABSORPTION_EXPERIMENT_PLAN.md`
- 진행 상태: `docs/STRATEGY_V2_METHOD_ABSORPTION_CHECKLIST.md`
