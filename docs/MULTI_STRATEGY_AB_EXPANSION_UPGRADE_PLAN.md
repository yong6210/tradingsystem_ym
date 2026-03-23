# Multi Strategy AB Expansion Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`A_ONLY -> A+B 멀티 전략 확장`

## 2. 배경
- 현재 live stance는 사실상 `A_ONLY` 성격이 강하다.
- control, governance, promotion 계층은 많이 올라왔지만, alpha source 자체는 여전히 reversal 편중이 남아 있다.
- 다음 핵심 갭은 `A 전략(reversal)`과 `B 전략(continuation / breakout)`을 같은 runtime language 안에 공존시키는 것이다.

## 3. 목표
1. `A`와 `B` 전략 family contract를 분리한다.
2. scanner / ranking / portfolio / outcome decomposition이 multi-strategy를 읽게 만든다.
3. 첫 단계는 compare-only와 shadow/probation 중심으로 시작한다.

## 4. 포함 범위
1. strategy family contract
2. strategy coexistence patch plan
3. validation / checklist / dashboard / README 반영
4. 테스트 및 문서 동기화

## 5. 제외 범위
1. 무조건 live rollout 강제
2. approval authority 급변경
3. 대규모 DB migration

## 6. 다음 작업
- 전체 완료
