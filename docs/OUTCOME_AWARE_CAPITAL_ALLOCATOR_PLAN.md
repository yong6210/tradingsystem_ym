# Outcome-Aware Capital Allocator Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`strategy v2`에 outcome-aware capital allocator 계층 추가

## 2. 배경
- 현재 시스템은 approval penalty, sizing clamp, portfolio ordering bias, rollout recommendation, opportunity capture, capture-aware operator priority까지 연결됐다.
- 하지만 아직 명시적인 `capital allocation` 계층은 없다.
- 즉 지금은 `좋은 후보를 더 앞에 두는 것`까지는 되지만, `family / regime / session` 기준으로 scarce capital을 얼마나 배분할지`는 별도 레이어로 관리하지 않는다.

## 3. 목표
1. `family` 중심의 outcome-aware capital allocation hint를 만든다.
2. `regime / session`은 allocator modifier로만 사용한다.
3. 이번 라운드는 compare-only allocator recommendation 또는 allowance layer로 먼저 설계한다.

## 4. 핵심 개선 축
1. Allocator contract
- `family allocation weight`, `allocator tier`, `capital pressure`, `allocation summary`를 정규화한다.

2. Runtime integration
- portfolio overlay가 `ordering bias`를 넘어서 `allocation allowance` 또는 `allocator recommendation`을 읽게 한다.

3. Surface alignment
- validation / checklist / dashboard / README가 같은 allocator 언어를 쓰게 한다.

## 5. 구현 범위
포함:
1. allocator contract / derivation
2. portfolio allocation layer 반영
3. validation/checklist/dashboard surface 동기화
4. 테스트와 README 동기화

제외:
1. strategy family 추가
2. approval hard block 재정의
3. rollout policy DB 자동 변경
4. threshold 자동 완화

## 6. 완료 기준
1. operator가 `어느 family에 더 capital을 실을지 / 덜 실을지`를 family 중심으로 읽을 수 있다.
2. allocator가 기존 approval / sizing / ordering과 역할이 분리된다.
3. thin sample bucket에는 공격적 capital tilt를 주지 않는다.

## 7. 예상 산출물
- `OUTCOME_AWARE_CAPITAL_ALLOCATOR_CONTEXT_NOTE.md`
- `OUTCOME_AWARE_CAPITAL_ALLOCATOR_CHECKLIST.md`
- `OUTCOME_AWARE_CAPITAL_ALLOCATOR_CONTRACT.md`
- `OUTCOME_AWARE_CAPITAL_ALLOCATOR_DERIVATION_RULES.md`
- `OUTCOME_AWARE_CAPITAL_ALLOCATOR_PATCH_PLAN.md`
- allocator derivation 문서
- allocator patch plan 문서
- portfolio allocator 관련 코드 수정
- 회귀 테스트
