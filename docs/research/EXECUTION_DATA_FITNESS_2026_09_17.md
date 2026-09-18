# 체결 자료 적격성 점검

2026-09-17. **가격·펀딩 백테스트 자료는 있지만, 지정가 체결률과 3초 대기 후 시장가 전환을 검증할 자료는 아직 부족하다.** 호가의 매수/매도 계산 행을 독립 체결 표본으로 세지 않는다.

범위: 등록된 BTCUSDC 공개 자료 묶음, 기존 BTCUSDC/BTCUSDT quote-shadow 파일 두 개와 생성 코드, 이번 공개 스트림 단기 관측. 저장소의 모든 과거 파일을 전수 조사한 결론은 아니다. [검사 코드](../../scripts/audit_execution_data.py)와 [수치/원본 해시](../../reports/validation/execution_data_fitness_20260917/data_fitness.json)에 재현 경로를 남겼다.

## 기존 자료

| 항목 | BTCUSDC | BTCUSDT |
|---|---:|---:|
| 요약 행 | 340 | 436 |
| symbol+정밀 timestamp별 호가 관측 | 170 | 218 |
| 관측마다 long/short 두 계산 | 170쌍 | 218쌍 |
| 서로 다른 decision_id | 178 | 162 |
| 완전히 동일한 중복 행 | 0 | 0 |
| 잘못된 bid/ask·필수 필드 누락 | 0 | 0 |
| 관측일 수(UTC) | 12일 | 19일 |
| 관측 범위(UTC) | 6월12일~9월8일 | 6월4일~9월8일 |
| 최대 관측 공백 | 6,755,960.50초 | 6,755,932.13초 |

BTCUSDC 관측 170회 중 150회가 6월12~13일에 몰려 있다. 최대 공백은 약 78.19일이다. 170개 호가 관측도 시간 의존성이 있어 독립 통계 표본 170개라는 뜻은 아니다.

**높은 중요도·높은 확신:** 자료 생성 코드는 한 번 받은 REST 호가에서 양방향 시장가 비용을 각각 계산한다. 따라서 340행을 340번의 주문 또는 체결 관측으로 해석하면 근거를 부풀린다. 기본 decision_id가 초 단위라 같은 초에 여러 요청이 있으면 ID도 반복된다. 이번 점검에서는 symbol+정밀 timestamp로 묶고 동일 시점 호가 충돌 여부를 확인했다. 향후 수집기는 별도 수집 ID와 단조 수신 시각을 저장한다.

**높은 중요도·높은 확신:** 저장된 값은 bid/ask·depth 명목 합·중간가 대비 가상 시장가 가격 차이다. 원시 depth, 업데이트 연결 순서, 공개 체결, 자기 주문 접수/체결, 대기열 우선순위가 없다. `latency_ms`는 REST 요청 왕복 소요 시간이며 주문 지연이나 이벤트 전송 지연이 아니다. `order_notional_usdt`는 기존 필드명으로, BTCUSDC에서는 quote 자산 USDC 명목 계산이다. USD/USDT/USDC 동일 가치가 검증됐다는 뜻은 아니다.

등록된 별도 역사 자료는 가격/마크/지수 각각 32개월(총 96 ZIP)과 펀딩 원본 3파일이다. 이 등록 묶음만으로는 분봉 안의 지정가 체결 순서·대기열·3초 취소 경쟁을 복원할 수 없다. 새 결과를 좋게 만들기 위해 메이커 무료 가정을 확정하거나 비용을 낮추지 않는다.

## 공개 스트림 단기 확인

공식 문서의 현재 경로에 따라 depth/bookTicker는 `/public`, aggTrade/markPrice는 `/market`으로 분리했다. 스트림을 먼저 열고 REST depth를 받은 뒤 스냅샷 이전 이벤트를 제외하고 최초 연결 및 `pu → 이전 u`를 검사했다. [공식 경로 변경 안내](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Important-WebSocket-Change-Notice), [공식 호가 연결 규칙](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly).

2026-09-17 13:05 UTC에 접속하고 REST 수신 뒤 12초 관측했다. 최초 버퍼 때문에 총 수집 시간/메시지 수를 정확히 12초의 정규 표본으로 해석하지 않는다.

- depth 112건: 스냅샷 이전 1건 제외, 나머지 111건의 연결 순서 통과. 확인된 연결 공백·형식 오류 0.
- bookTicker 1,791건, aggTrade 63건, markPrice 13건. 공개 연결/REST 오류 0.
- 원본 메시지, 로컬 UTC 수신 시각, 단조 수신 시각, REST 응답/요청 소요 시간을 보존했다. 실주문·개인 API 요청 0.

[원시 스트림](../../reports/validation/execution_data_fitness_20260917/public_events.jsonl), [REST 스냅샷](../../reports/validation/execution_data_fitness_20260917/depth_snapshot.json).

이것은 접속/순서 점검이다. 전체 호가 장부 재구성·장기 재연결·다양한 장세·시계 오차·실제 주문 지연·메이커 체결을 검증하지 않았다. 특히 공개 호가/체결만으로 자기 주문의 실제 queue 위치를 확정할 수 없다.

## 다음 자료 계약

1. **수집 품질 우선:** 새 경로에서 원본 이벤트·수집 ID·수신 단조 시각·거래소 시각·스냅샷·끊김/재동기화 구간을 저장한다. 연결 공백을 감추거나 앞뒤 장부를 그대로 잇지 않는다.
2. **읽기 전용 재생 검증:** 스냅샷/증분으로 전체 L2를 재구성해 0수량 삭제·절대 수량·스냅샷 경계·재연결·중복/순서 역전을 검사한다. L2만으로 대기열 위치나 체결을 확정하지 않는다.
3. **모의 정책 사전 고정:** 지연 3초는 최적값이 아닌 현재 초안. 수집 기간·장세/시간대 범위·관측 종료 조건·비용/체결 상하한·탈락 조건을 고정한 뒤 정책을 평가한다. 짧은 정상 접속을 보고 수집 기간 충분성을 주장하지 않는다.
4. **관측과 계정 증거 구분:** 실제 maker/taker 수수료·주문 접수/취소/체결은 공개 자료와 별개의 계정 증거다. 현재는 미확인으로 남기며 이 작업에서 키/계정 접근이나 주문을 실행하지 않았다.

재현: 프로젝트 `.venv`의 기존 `websockets` 의존성을 사용한다. `--capture-seconds 0`은 로컬 점검만, `1~30`은 명시적으로 한 번의 공개 관측이며 예약/백그라운드 수집을 설치하지 않는다.

```bash
.venv/bin/python scripts/audit_execution_data.py --output reports/validation/execution_data_new --capture-seconds 12
```
