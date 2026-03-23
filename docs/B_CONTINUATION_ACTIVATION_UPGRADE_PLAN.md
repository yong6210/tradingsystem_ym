# B Continuation Activation Upgrade Plan

최종 갱신: 2026-03-23
상태: 전체 완료

## 1. 작업명
`strategy v2`에 first-wave `B continuation activation` 계층 추가

## 2. 배경
- 현재 엔진은 `multi_strategy_ab`로 A/B 공존은 읽을 수 있지만, `trend_continuation`이 지금 research-only인지, blocked인지, guarded probation인지, activation review 가능한지까지는 한 객체로 압축하지 못했다.
- operator는 여전히 `multi_strategy_ab`, rollout, lifecycle, promotion stack을 다시 합쳐 읽어야 한다.

## 3. 목표
1. `trend_continuation`의 first-wave activation posture를 같은 언어로 요약한다.
2. scanner / portfolio row drill-down과 validation / checklist / dashboard aggregate summary를 같은 기준으로 맞춘다.
3. 이번 라운드도 compare-only layer로만 유지한다.

## 4. 핵심 개선 축
1. activation contract
2. activation derivation
3. scanner / portfolio / validation / checklist / dashboard / README 반영
4. 테스트 및 self-check

## 5. 구현 범위
포함:
1. `b_continuation_activation.py`
2. scanner / portfolio row additive field `b_continuation_activation`
3. validation `b_continuation_activation_summary`
4. checklist / dashboard / README 반영
5. 테스트와 문서 동기화

제외:
1. approval hard authority 변경
2. rollout DB auto-write
3. sizing source-of-truth 변경
4. operator kill-switch 우회
