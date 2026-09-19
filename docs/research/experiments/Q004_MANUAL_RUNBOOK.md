# Q004 수동 이어가기 — 시각 순서와 누락 처리

Q004 v1에는 자동 일정이 없다. 이 문서는 운영 인계용이며 고정한 [명세](Q004_PROSPECTIVE_FORECAST.md)·정책·예측 코드를 변경하지 않는다. 날짜마다 새 예측을 만들려면 해당 경계 전에 이 작업이 실제로 실행 중이어야 한다.

## 한국 시각 2026-09-20의 순서

1. **09:00 이전:** `prepare --boundary 2026-09-20`. 9월 19일 첫 예측을 재생성하지 않고 다음 날짜의 입력을 준비한다. 완료 분봉만 사용한다.
2. **09:00:05~09:00:50:** `publish --boundary 2026-09-20`. 다음 예측을 09:01 가격 형성 전에 기록한다. 이어서 별도 감사기에 `2026-09-20`을 전달한다.
3. **09:01 이후:** `score --boundary 2026-09-19`. 전날 예측의 목표 종료 분봉과 펀딩 자료를 조회한다. 원래/강한 선택, 기본/스트레스 비용, 평균/0 예측 대조를 함께 확인한다.

따라서 첫 결과만 확인하려고 09:01 이후 작업을 시작하면 그날의 새 예측 기한은 이미 지났다. 이 경우 다음 예측을 소급 작성하지 않는다. `status`에서 미공표 날짜를 확인하고 전날의 유효 예측만 채점한다. 날짜는 모두 명령의 UTC 판단 경계 날짜이며 한국 시각의 해당 날짜 09:00에 대응한다.

## 명령과 증거

저장소 루트에서 Python 실행기로 `scripts/run_prospective_price_forecast.py`를 호출한다. `register`는 이미 실행했으므로 반복하지 않는다.

```text
scripts/run_prospective_price_forecast.py status
scripts/run_prospective_price_forecast.py prepare --boundary 2026-09-20
scripts/run_prospective_price_forecast.py publish --boundary 2026-09-20
scripts/audit_prospective_price_forecast.py 2026-09-20
scripts/run_prospective_price_forecast.py score --boundary 2026-09-19
```

명령의 순서만 적었으며 그대로 연속 실행하라는 뜻은 아니다. 각 시각 조건을 지켜야 한다. 90일 자동 기동이나 예약 명령은 없다. 결과 해석에는 해당 날짜 `publish/forecast.json`, `publication_receipt.json`, `verification.json`, `score/outcome.json`을 사용한다. 첫날 전용 보고서 생성기는 이후 날짜 집계기로 사용하지 않는다.

## 실패와 수정

- 늦은 실행·누락된 예측은 무신호/수익 0이 아닌 미공표다. 뒤늦은 예측을 만들지 않는다.
- 펀딩이나 목표 가격이 불완전하면 결과 미확인이다. `score_failure.json` 등 실패 원문을 보존한다.
- v1은 날짜별 prepare/publish/score 폴더를 덮어쓰지 않는다. 실패한 디렉터리를 지워 재시도하거나 경계 시각을 옮기지 않는다. 추후 재조회가 필요하면 원기록을 보존하는 별도 결과 보완 절차를 작성하고, 원래 예측·목표·비용 규칙의 동일성을 검산해야 한다.
- 입력/모델/비용 규칙의 오류를 발견하면 기존 등록을 편집하지 않는다. 오류와 영향 범위를 기록하고 변경 버전은 별도의 미래 시작일로 고정한다.
- 첫 결과가 양수여도 수익성 확증·계좌 적격·손실 5% 달성을 선언하지 않는다. 과거 문턱 선택의 영향, 유효/누락 날짜, 거래 수와 불확실성을 유지한다.
