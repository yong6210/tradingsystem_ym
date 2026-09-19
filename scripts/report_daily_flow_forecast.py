"""E040: publish only the fixed prediction-pair economics actually measured."""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/e040_daily_flow_forecast_20260919'


def main():
    s=json.loads((OUT/'summary.json').read_text());v=json.loads((OUT/'verification.json').read_text())
    for name,h in v['artifacts'].items():
        if hashlib.sha256((OUT/name).read_bytes()).hexdigest()!=h:raise ValueError('changed artifact '+name)
    if s['account_gate_pass']:raise ValueError('this failure report must not replace the registered account stage')
    rows=[];calibration={}
    for model in ('PRICE','FLOW'):
        sig=json.loads((OUT/(model+'_signals.json')).read_text());active=[r for r in sig if r['side']]
        calibration[model]=dict(selected_days=len(active),mean_predicted_gross_bps=sum(abs(r['prediction_bps']) for r in active)/len(active))
        for cost in ('base','stress'):
            r=s['results'][cost+'_'+model]
            rows.append(dict(model=model,cost=cost,active=r['active_days'],gross=r['mean_gross_bps_active_days'],
                             cost_bps=r['mean_cost_bps_active_days'],net=r['mean_net_bps_active_days'],
                             calendar_net=r['mean_net_bps_all_days']))
    mse_improvement=100*(1-s['results']['base_FLOW']['forecast_mse_bps_squared']/s['results']['base_PRICE']['forecast_mse_bps_squared'])
    with (OUT/'report_calculations.json').open('x') as f:json.dump(dict(calibration=calibration,mse_improvement_pct=mse_improvement),f,indent=2)
    report=ROOT/'docs/research/experiments/E040_RESULTS_2026_09_19.md'
    text=['# E040 결과 — 일별 체결 압력 예측의 비용 후 추가 가치 미확인','',
        '**체결 압력을 추가한 FLOW 모델은 기본·스트레스 모두 순손실이고 PRICE 대조보다 나빴다.** 사전 경제성 필요조건을 통과하지 못해 계좌·주문 구현으로 확대하지 않는다. 수익 후보 발견은 여전히 미완료다.','',
        '평가 범위는 기존 BTCUSDC 2024-09-01~2026-09-01 미만 자료에서 다음 날 청산이 가능한 729일이다. 각 판단은 직전 완료 가격/체결량과 이미 결과가 확정된 과거 180일로만 계산했다. 하루의 학습 간격을 두고 현재/미래 목표값을 제외했으나, 전체 자료는 연구에서 이미 본 기간이므로 독립 전진 성과가 아니다.','',
        '## 사건 경제성','',
        '아래는 진입한 날들의 동일 명목금액 기준 거래당 평균이다. 1bp=0.01%. 수수료·슬리피지·펀딩을 포함하고 운영비·계좌 손절·수량 제약은 적용 전이다. 초기 1,000 USDC의 계좌 수익률이나 손익 금액이 아니다.','',
        '| 예측 정보 | 비용 | 거래일 | 가격 이익 bp | 비용 bp | 순손익 bp |',
        '|---|---|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['model']} | {r['cost']} | {r['active']} | {r['gross']:+.2f} | {r['cost_bps']:.2f} | {r['net']:+.2f} |")
    text+=['',
        'PRICE는 완료 1일/7일 수익률과 1일 실현 변동성 3개를 사용한다. FLOW는 동일 모델에 직전 일 taker 매수·매도 BTC량 불균형 1개만 추가한다. 예측 수익 절댓값이 사전 비용 문턱을 넘으면 그 방향으로 다음 분 시가부터 보유하고 다음 날 자정 청산한다. 모수·학습 기간·비용 문턱을 결과에 맞춰 재검색하지 않았다.','',
        'FLOW는 288일(매수 157/매도 131), PRICE는 293일(매수 167/매도 126)에 진입했다. 서로 거래일과 방향이 다르므로 활성 거래 평균끼리의 차이를 동일 사건의 추가 정보 효과로 해석하지 않는다. 대기일을 0으로 둔 같은 729일의 차이도 아래처럼 함께 계산했다.','',
        '| 비용 | FLOW 일평균 순손익 bp | PRICE 일평균 순손익 bp | FLOW−PRICE bp | 차이의 탐색 95% 구간 bp |','|---|---:|---:|---:|---:|']
    for cost in ('base','stress'):
        a,b=s['results'][cost+'_FLOW'],s['results'][cost+'_PRICE'];p=s['paired_flow_minus_price'][cost];lo,hi=p['interval_bps']
        text.append(f"| {cost} | {a['mean_net_bps_all_days']:+.2f} | {b['mean_net_bps_all_days']:+.2f} | {p['mean_bps']:+.2f} | [{lo:+.2f}, {hi:+.2f}] |")
    text+=['',
        '차이의 구간은 28일 순환 블록 2,000회이며 양·음수를 모두 포함한다. 이 기간에서 추가 순익을 확보하지 못했다는 판단이며 모든 시기·모든 주문 흐름 모델에서 예측력이 없다는 증명은 아니다. 다중 연구와 자료 재사용 선택 편향을 보정한 확증 구간도 아니다.','',
        '## 예측 점수와 수익은 다르다','',
        f"FLOW의 전체 예측 평균제곱오차는 PRICE보다 {mse_improvement:.3f}% 작았지만 비용 후 수익은 악화됐다. FLOW가 선택한 날의 예측 방향 기대 가격 움직임은 평균 {calibration['FLOW']['mean_predicted_gross_bps']:.2f}bp였으나 실제 평균은 5.63bp였다. 예측값이 비용 문턱을 넘는 것 자체는 거래 후 비용을 감당한다는 증거가 아니다.",'',
        'FLOW의 스트레스 달력 일평균 순손익은 2024년 일부 +5.29bp, 2025년 −3.97bp, 2026년 일부 −11.68bp였다. PRICE도 2025/2026 스트레스가 음수다. 전체 평균이나 예측 오차 하나로 최근 기간의 손실을 감추지 않는다.','',
        '## 연구 범위와 검산','',
        '기존 S06A는 돌파 사건의 체결 방향 필터였고, 이번 모델은 돌파와 무관한 일별 예측이다. 호가 취소·대기열·순서 정보를 사용하지 않았으므로 E032 호가 흡수나 시장조성의 검증을 대신하지 않는다. 캐리·쌍매매는 기존 경제성 실패를 보존하고, 뉴스·온체인·옵션은 필요한 당시 자료가 미확보다. 연구 전체가 여섯 개 또는 이번 두 예측 모델로 끝난 것은 아니다.','',
        '초단기 문헌을 확인했지만 사용자 거래비용을 넘는 직접 근거가 없어 10초 전략은 구현하지 않았다. 해당 문헌의 4~12시간 회귀계수를 거래 수익으로 가져오거나, 이번 일별 규칙을 논문 복제라고 부르지 않는다.','',
        f"32개 공식 체결량 원본의 해시/스키마와 가격 자료 일치를 재확인했다. 완료 일별 특징을 분 단위 직접 집계와 대조하고, {v['forecasts']:,}개 순차 예측에서 학습 시각과 서로 다른 ridge 계산식을 확인했다. 관련 {v['focused_tests']}개 검사 및 별도 Decimal 사건 가격·수수료·펀딩 산술을 통과했다. 미래 입력 변경의 영향 검사는 작은 부동소수점 오차를 허용하며 계좌 수익의 증명이 아니다.",'',
        '**결정: STOP_NO_COST_NET_INCREMENTAL_EDGE.** 계좌 실행 0, 채택 0, 결합 0, 실주문 0. 계좌 최대 낙폭을 측정하지 않았으므로 5% 기준 충족 여부를 주장하지 않는다. 비용 전 가격 이익이 기본 거래비용에도 못 미치는 이 규칙은 추가 운영 개발이나 위험 확대의 근거가 되지 않는다. 같은 표본의 학습 창·특징·정규화·문턱 튜닝은 종료한다.','',
        '[사전 명세 및 범위 지도](E040_DAILY_FLOW_FORECAST.md) · [결과](../../../reports/validation/e040_daily_flow_forecast_20260919/summary.json) · [검산](../../../reports/validation/e040_daily_flow_forecast_20260919/verification.json)','',
        '원본 집계 정의: [Binance Public Data](https://github.com/binance/binance-public-data). 문헌 적격성 검토: [The Quarter-Hour Effect](https://arxiv.org/html/2607.09426v1).']
    with report.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'daily-flow-forecast','title':'일별 체결 압력 추가 예측의 비용 후 경제성','queries':[{
        'id':'e040','source':{'label':'고정 PRICE/FLOW 순차 학습 사건 계산',
        'files':[{'label':str(OUT/'summary.json')},{'label':str(OUT/'verification.json')},{'label':str(report)}],
        'metricDefinitions':[{'label':'활성 거래 평균 순손익 bp','definition':'진입한 날들의 가격 손익 − 실제 가정 체결비용·수수료·역사적 및 스트레스 펀딩. 진입 기준 명목금액으로 정규화.'},
                             {'label':'달력 평균 순손익 bp','definition':'대기일을 0으로 포함한 동일 729일 평균. 계좌 수익률이 아님.'}],
        'filters':['BTCUSDC, 과거 180일 학습 및 하루 간격','같은 비용 문턱·편도 수수료 2.5bp, 기본/스트레스 체결비용'],
        'caveats':['기존 자료 재사용으로 독립 전진 성과가 아니다.','손절·수량·운영비를 통합한 계좌가 아니며 5% 낙폭 적격성을 측정하지 않았다.',
                   '두 모델의 진입 날짜가 달라 같은 달력 기준 차이도 별도 공개했다.','분봉 체결 집계는 호가·대기열 모델이 아니다.'],
        'evidenceFlow':[{'kind':'validation','title':'과거 정보와 비용 검산','detail':'공식 원본 해시, 직접 분 집계, 순차 학습 시각·수치 대조, 별도 Decimal 사건 비용 검산.'}]},
        'reportingPeriod':'2024-09-01~2026-08-30 진입, 마지막 청산 2026-08-31 UTC',
        'columns':[{'field':'model','label':'모델'},{'field':'cost','label':'비용'},{'field':'active','label':'거래일'},
                   {'field':'gross','label':'가격 이익 bp'},{'field':'cost_bps','label':'비용 bp'},{'field':'net','label':'순손익 bp'}],
        'rows':rows,'methods':[{'language':'calculation','code':'net_bps = (side*(exit_fill-entry_fill)-fees-funding)/entry_reference*10000; active mean excludes cash days, paired comparison includes them.'}]}]}]}
    with (OUT/'delivery_sources.json').open('x') as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
    print(report)


if __name__=='__main__':main()
