# NQ Futures CSV Backtest

`session_impulse_retest`를 `NQ/MNQ` 같은 외부 선물 1분봉 CSV에 태우는 방법입니다.

## 지원 입력 형식

다음 둘 중 하나면 됩니다.

1. 단일 타임스탬프 열

```csv
timestamp,open,high,low,close,volume
2026-04-24 08:30:00,20010.25,20012.00,20008.50,20011.75,1543
```

2. 날짜/시간 분리 열

```csv
date,time,open,high,low,close,volume
2026-04-24,08:30:00,20010.25,20012.00,20008.50,20011.75,1543
```

`NinjaTrader` 스타일 헤더도 그대로 읽습니다.

```csv
Time,Open,High,Low,Close,Volume
2026-04-24 08:30:00,20010.25,20012.00,20008.50,20011.75,1543
```

## 시간대

- `NQ/MNQ`는 보통 `America/Chicago`로 export 되는 경우가 많습니다.
- CSV 시간이 거래소 현지 시간이라면 `--timezone America/Chicago`를 유지하면 됩니다.
- CSV가 이미 UTC라면 `--timezone UTC`를 쓰면 됩니다.

## 실행 예시

```bash
uv run python /Users/yumin/Documents/trading/scripts/run_micro_main_futures_csv_backtest.py \
  --csv /absolute/path/to/NQ_1m.csv \
  --symbol NQ1! \
  --profile baseline \
  --timezone America/Chicago \
  --days 1825 \
  --write-report
```

전체 CSV를 그대로 쓰고 싶으면 `--days`를 빼도 됩니다.

특정 기간만 자르고 싶으면:

```bash
uv run python /Users/yumin/Documents/trading/scripts/run_micro_main_futures_csv_backtest.py \
  --csv /absolute/path/to/NQ_1m.csv \
  --symbol NQ1! \
  --profile baseline \
  --timezone America/Chicago \
  --start-ts 2021-04-27T00:00:00Z \
  --end-ts 2026-04-27T00:00:00Z
```

## 출력

결과 JSON에는 다음이 들어갑니다.

- `window`
  - 요청 구간
  - 실제 사용된 1m/5m 시작/종료 시각
  - 사용한 바 수
- `summary`
  - `closed`
  - `win_rate`
  - `ev_r`
  - `total_r`
  - `decision`

## 주의

- 이 러너는 **1분봉 CSV**를 기준으로 5분봉을 내부 재구성합니다.
- `NQ/MNQ`는 현재 crypto 전용 심볼별 오버라이드가 없기 때문에, 기본은 `--profile baseline`으로 시작하는 게 맞습니다.
- `Apex` 같은 프랍 수동 추종 용도로 쓸 땐, 결과를 그대로 자동매매 레버리지로 옮기지 말고 별도 리스크 캡을 두는 게 맞습니다.
