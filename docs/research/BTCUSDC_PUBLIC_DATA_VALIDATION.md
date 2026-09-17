# BTCUSDC 공개 자료 검증 — 2026-09-17

## 결론

우선순위2의 공개 자료 확보와 결측 검사를 진행했다. 자료 상태는 **PARTIAL_COVERAGE**다. 실제 계정 조건 확인, 주문 어댑터 연결, 새 자료로 전략 재검증은 아직 완료하지 않았다. BTCUSDT 과거 성과를 BTCUSDC 성과로 바꾸어 표시하지 않는다.

## 확보한 증거

- 공식 USD-M 월별 ZIP 96개: 거래가격·마크가격·지수가격 각각 2024-01~2026-08의32개월. 모든 파일은 공식 CHECKSUM과 SHA256 일치. OHLC/시간/월 범위 검사를 수행했다.
- 거래가격의 실제 확보 범위: 2024-01-04 12:31 UTC~2026-09-01 00:00 UTC 미만. 이 범위의 월별 원본은 분 간격이 연속이다.
- 계약 onboardDate: 2024-01-03 12:30 UTC. 최초 거래가격과의24시간1분 차이는 초기 자료 미확보이며, 거래가 없었다는 증거가 아니다. REST 조회는 빈 목록이었다.
- 마크·지수 원본은 2024-01-03 00:00 UTC부터 시작한다. 계약 등록 전 가격을 거래 가능 시점으로 간주하지 않는다.
- 실제 펀딩2,914건: 2024-01-03 16:00 UTC~2026-08-31 16:00 UTC+1ms. 원래 밀리초 타임스탬프를 보존한다. 약8시간 간격이지만 정확한 정시로 강제 반올림하지 않는다.

## 결측과 보충

| 항목 | 원본 문제 | 공개 REST 조회 | 처리 |
|---|---|---|---|
| 마크·지수 각각 | 2026-06-29 UTC 하루1,440분 누락 | 각각1,440분 반환 | 정확한 시간 범위·고유 순서·양수 유한 OHLC·가격 관계·종료시간 검증 통과, 별도 보충 파일 |
| 마크·지수 각각 | 2024-08-12 10:02~10:04 UTC 미만2분 누락 | 빈 목록 | 미해결 결측, 보간 금지 |
| 거래가격 초기 | 등록 시점~2024-01-04 12:31 UTC 미만1,441분 | 빈 목록 | 초기 범위 미확보, 백테스트 시작 이전으로 제한 |

원본 ZIP을 고치지 않았다. `validated_overlay.json`에 보충 자료 경로·해시·검증 결과를 기록했다. 아직 엔진 입력 로더에 연결하지 않았으며, 원본 manifest의 REVIEW_REQUIRED도 그대로 보존한다. 남은 결측을 가로지르는 포지션을 평가할 때 임의 가격 대체나 결측 봉 삭제로 위험을 숨기지 않도록 별도 처리 계약이 필요하다.

## 거래 조건과 미확인 사항

현재 공개 스냅샷: BTCUSDC PERPETUAL, USDC 증거금, 거래 상태 TRADING. 가격 tick0.1, 수량 step0.001, 최소수량0.001, 최소명목50 USDC. 일반 LOT 최대800, MARKET_LOT 최대50으로 시장가 필터를 별도로 적용해야 한다. 이는 현재 필터이며 과거 전체 기간의 규격 증거는 아니다.

계정별 수수료, 레버리지 구간별 유지증거금, 포지션/증거금 모드, 사용 가능 잔고는 미확인이다. 사용자 maker0 가정은 검증된 계정 요율이 아니다. exchangeInfo의 maintMarginPercent/requiredMarginPercent는 공식 문서에서 무시하도록 명시한 필드이므로 실제 청산 계산에 쓰지 않는다. liquidationFee 역시 유지증거금률이 아니다.

수집기는 인증 없는 공개 GET만 사용했다. 실제 주문 및 서명된 테스트 주문을 보내지 않았다. 기존 `submit_order(live=False)`도 서명된 `/order/test` 요청이므로 오프라인 모의 주문으로 사용하지 않는다.

## 재현

- `scripts/collect_btcusdc_public.py`: 공개 자료 수집·체크섬·봉 검증·펀딩 페이지 보존.
- `scripts/check_btcusdc_archive_gaps.py`: 누락 시간대 공개 REST 조회, 원문 보존.
- `scripts/validate_btcusdc_gap_overlay.py`: 보충 후보의 해시·시간·OHLC 검증.
- 증거 디렉터리: `data/historical/btcusdc_public_20260917/`.
- `python3 -m unittest tests.test_btcusdc_gap_overlay tests.test_market_fallback tests.test_durable_fallback`: **28개 통과**. 새 결측 검사4개와 기존 주문 복구24개다. 실거래 검증이나 새 전략 성과 검증은 아니다.

공식 출처: [공개 데이터와 체크섬](https://github.com/binance/binance-public-data), [USD-M 시장 데이터 API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).


## 후속 진행

[E005 결과](experiments/E005_RESULTS_2026_09_17.md)에서 완전한2024-09~2026-08 구간의 가격·실제 펀딩 비교를 완료했다. 위 수집 당시의 미연결 상태는 역사 기록이며, 현재 로더 연결과 결측 거부 정책은 [입력 계약](BTCUSDC_EXECUTION_CONTRACT.md)에 기록했다. 전체 원본의 PARTIAL_COVERAGE 상태는 바꾸지 않았다.
