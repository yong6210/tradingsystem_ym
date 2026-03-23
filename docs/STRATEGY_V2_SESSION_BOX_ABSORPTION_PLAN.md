# Strategy v2 Session Box Absorption Plan

최종 갱신: 2026-03-23
상태: All checklist items completed

## 1. 목적
- `세션 박스 high/low`, `돌파 종가 확인`, `기계적 실행`처럼 현재 전략과 합치되는 요소만 흡수한다.
- `1m 저RR 고승률 breakout model`이나 `indicator stack-led` 해석은 배제한다.
- 현재 전략 v2의 `상태 -> 위치 -> 유동성 -> 반응 -> 실행` 구조 안에서만 재해석한다.

## 2. 작업 범위
1. 채택 원칙 / 배제 원칙 확정
2. 세션 박스 전략을 strategy v2 언어로 매핑
3. 문서 반영안 작성
4. runtime feature / contract 후보 정리
5. 검증 항목과 compare-only 실험안 정의
6. 실제 문서 반영 또는 최소 구현 실행
7. self-check 및 최종 적용 보고

## 3. 비범위
- 1분봉 breakout 전용 새 라이브 전략군 추가
- EMA/RSI/엘리어트/추세선/피보 기반 필터 채택
- `고승률이면 된다`는 방향의 평가 기준 변경
- `0.2R~0.25R` 저RR 구조 도입
- approval/risk/sizing semantics 변경

## 4. 목표 산출물
1. 세션 박스 전략에서 배울 것과 버릴 것을 문서로 고정
2. session box를 `liquidity reference`로 해석하는 기준 문구
3. compare-only runtime 후보와 검증 지표 정의
4. 승인 후 실제 문서 반영 또는 최소 alias 구현

## 5. 현재 결정
- `세션 유동성 / breakout close 확인 / 기계적 실행`만 흡수 대상으로 본다.
- `indicator stack / 고승률 저RR / 1m breakout-only`는 현재 전략과 충돌하므로 배제한다.
- 이번 단계는 원칙 확정까지만 수행하고, runtime/문서 반영은 다음 항목에서 별도로 진행한다.

## 6. 현재 산출물
- 원칙 기준선: `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_CONTEXT_NOTE.md`
- 용어 매핑: `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_MAPPING.md`
- 문서 반영안: `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_DOC_PATCH_PLAN.md`
- runtime 후보: `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_RUNTIME_CANDIDATES.md`
- 비교 실험안: `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_EXPERIMENT_PLAN.md`
- core 문서 반영:
  - `docs/STRATEGY_V2_BLUEPRINT.md`
  - `docs/STRATEGY_V2_A_ONLY_PLAYBOOK.md`
  - `docs/STRATEGY_OPERATING_MANUAL.md`
- 진행 상태: `docs/STRATEGY_V2_SESSION_BOX_ABSORPTION_CHECKLIST.md`
