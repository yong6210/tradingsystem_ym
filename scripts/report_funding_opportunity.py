"""Independent integer checks and report for the fixed E037 funding screen."""
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/e037_funding_opportunity_20260919_v2'
SCALE=10**8


def main():
    summary=json.loads((OUT/'summary.json').read_text())
    proof=json.loads((OUT/'verification.json').read_text())
    for name,h in proof['artifacts'].items():
        if hashlib.sha256((OUT/name).read_bytes()).hexdigest()!=h:raise ValueError('changed result '+name)
    btc=[json.loads(line) for line in (ROOT/'reports/validation/e028_carry_rule_replay_20260919/funding_inputs.jsonl').read_text().splitlines()]
    data={'BTCUSDC':[D(e['rate']) for e in btc],
          'ETHUSDC':[D(e['fundingRate']) for e in json.loads((ROOT/'reports/validation/e029_pair_feasibility_20260919/eth_funding.json').read_text())],
          'SOLUSDC':[D(e['fundingRate']) for e in json.loads((OUT/'sol_funding.json').read_text())]}
    checks={}
    for symbol,rates in data.items():
        for scenario,extra,cost in [('base',D(0),D('1.32')),('stress',D('.0001'),D('1.80'))]:
            expected=summary['results'][symbol][scenario]
            values=[(r-extra)*400*SCALE for r in rates]
            if any(x!=int(x) for x in values):raise ValueError('nonintegral audit scale')
            payments=list(map(int,values));fee=int(cost*SCALE)
            prefix=[0]
            for payment in payments:prefix.append(prefix[-1]+payment)
            # Independent interval formulation: enumerate every possible last
            # holding interval, using the best completed schedule before it.
            best=[0]
            for end in range(1,len(prefix)):
                best.append(max(best[-1],max(best[start]+prefix[end]-prefix[start]-fee for start in range(end))))
            if D(best[-1])/SCALE!=D(expected['oracle_funding_after_switching_cost']):raise ValueError('oracle interval audit')
            if D(sum(max(x,0) for x in payments))/SCALE!=D(expected['oracle_positive_funding_before_cost']):raise ValueError('positive sum audit')
            selected=[];eligible=20
            for i in range(20,len(rates)-21):
                if i<eligible:continue
                if sum(rates[i-20:i+1])<=D('.0066'):continue
                selected.append(i);eligible=i+22
            if selected!=[t['decision_index'] for t in expected['causal_trades']]:raise ValueError('causal decision audit')
            net=sum((sum(payments[i+1:i+22])-fee for i in selected),0)
            if D(net)/SCALE!=D(expected['causal_net_before_operations']):raise ValueError('causal PnL audit')
            checks[symbol+'_'+scenario]=dict(status='PASS',events=len(rates),interval_pairs_checked=len(rates)*(len(rates)+1)//2,causal_cycles=len(selected))
    fixed=sum((max(D('.006')*D(e['mark'])*(D(e['rate'])-D('.0001')),D(0)) for e in btc),D(0))
    assert fixed==D(summary['fixed_0006_btc_oracle_positive_funding_before_cost']['stress'])
    with (OUT/'independent_audit.json').open('x') as f:json.dump(dict(status='PASS_INTEGER_INTERVAL_AND_CAUSAL_SCREEN',checks=checks),f,indent=2)
    rows=[]
    for symbol,scenarios in summary['results'].items():
        a,b=scenarios['base'],scenarios['stress']
        rows.append(dict(symbol=symbol,cycles=a['causal_cycles'],base_net=float(a['causal_net_before_operations']),
                         stress_net=float(b['causal_net_before_operations']),
                         base_oracle=float(a['oracle_funding_after_switching_cost']),stress_oracle=float(b['oracle_funding_after_switching_cost'])))
    lines=['# E037 결과 — 펀딩 선택 규칙의 추가 계좌 개발 중단','',
        '**BTC·ETH·SOL의 고정 과거 정보 필터에서 양 비용 모두 수익인 후보를 얻지 못했다.** 이 규칙의 주문·증거금 계좌 구현과 추가 문턱 탐색은 진행하지 않는다. 세 종목 밖의 모든 캐리 기회가 없다는 결론은 아니다.','',
        '기간은 2024-09-01~2026-09-01 미만 UTC, 종목별 확정 펀딩 2,190건이다. 최초 자금 1,000 USDC 연구에서 두 다리 각각 명목 400 USDC를 유지할 수 있다는 별도 가정을 사용했다. 아래 금액은 펀딩 수입에서 가정한 거래비용을 뺀 **성분 계산**이며 계좌 수익률·실제 체결 성과가 아니다.','',
        '| 종목 | 과거 정보 진입 횟수 | 기본 순액 USDC | 스트레스 순액 USDC |',
        '|---|---:|---:|---:|']
    for r in rows:lines.append(f"| {r['symbol']} | {r['cycles']} | {r['base_net']:+.4f} | {r['stress_net']:+.4f} |")
    lines+=['',
        'BTC·ETH의 0은 무거래다. SOL은 2024-12-05 08:00 정산을 확인한 뒤 다음 21개 정산만 보유했다. 이전 21개 펀딩 합 68.76bp가 비용 문턱 66bp를 넘었지만, 이후 수입은 400 USDC 기준 1.852468 USDC였다. 기본 왕복 비용 1.32 USDC를 빼면 +0.532468, 스트레스는 추가 펀딩 0.84와 왕복 비용 1.80을 빼면 −0.787532다. 한 거래로 예측력이나 안정성을 추정하지 않는다.','',
        '## 유리한 정산을 완벽하게 미리 알 때의 참고치','',
        '펀딩 성분만 놓고 미래 정산을 전부 알아 최적 진입·청산을 선택해도, 아래와 같다. 양 다리 명목 400 USDC, 무비용 수량 재조정, 가격 괴리 불변을 가정하고 진입·청산 비용만 뺀 값이다. 구현 가능한 전략이 아니며 베이시스를 포함한 총손익의 엄밀한 상한도 아니다.','',
        '| 종목 | 기본 예지 대조 USDC | 스트레스 예지 대조 USDC |','|---|---:|---:|']
    for r in rows:lines.append(f"| {r['symbol']} | {r['base_oracle']:.4f} | {r['stress_oracle']:.4f} |")
    lines+=['',
        '기본 조건에서도 위 단일 종목별 예지 대조는 2년간 월2 USDC 운영비 예시의 총48 USDC보다 작다. 월2 USDC는 실제 비용이 아니라 기존 연구와 같은 예시다. 운영비가 없거나 다른 수량·자본 배분이면 산술은 달라지므로 보편적인 수익 불가능성으로 확대하지 않는다.','',
        '기존 E028의 고정 0.006 BTC 수량을 그대로 쓰면, 스트레스 순펀딩이 양수인 정산만 미래를 알고 골랐을 때의 거래비용 전 수입도 3.668483 USDC다. 이 값은 위 명목 400 USDC 기준과 수량 정의가 다르므로 직접 비교하지 않는다.','',
        '## 비용·위험과 자료의 한계','',
        '- 과거21개 정산률로 다음21개 수입을 예측하는 한 규칙을 고정했다. 전체를 보고 구간을 고른 예지 대조와 분리했고 시간창·문턱·자산 배분을 최적화하지 않았다.',
        '- 현물 편도10bp, 선물 편도2.5bp, 양 다리 슬리피지 기본2bp/스트레스5bp다. 현물 및 ETH/SOL의 실제 계정 요율은 미확인 가정이다. 정산당1bp 추가 부담은 연구 스트레스이며 실제 추가 수수료가 아니다.',
        '- 가격 괴리, 체결 순서·지연, 수량단위, 자금 이전, 담보·강제청산, 운영비를 통합하지 않았다. 계좌 최대 낙폭을 계산하지 않았고 사용자5% 기준 충족도 주장하지 않는다.',
        '- 이미 본 과거 기간이다. SOL의 새 공개 다운로드가 독립 전진 자료를 의미하지 않는다. ETH/SOL은 비교 연구 종목이며 실운용 BTCUSDC 범위를 변경하지 않았다.','',
        '## 자료와 검산','',
        'BTC·ETH 기존 원본의 검증 해시를 확인했다. SOL은 공식 공개 API 3페이지(1,000+1,000+190건)를 받았고, 세 종목 모두 8시간 달력·중복·수치·시각 편차를 확인했다. 최초 실행은 첫 HTTP200 응답을 저장한 뒤 상대 경로를 절대 경로 기준으로 기록하려는 코드 오류로 종료했다. 원문·실패·소스 버전을 보존하고 v2에서 같은 첫 응답을 재사용해 남은2페이지만 받았다. 첫 페이지 중복 요청이나 자동 재시도는 없었다.','',
        '미래 정보 변경에 대한 진입 불변성과 작은 전수 보유 경로 대조를 확인했다. 전체 자료의 정수 산술·모든 마지막 보유 구간을 열거하는 별도 계산으로 예지 대조와 과거 정보 규칙을 재계산했다. 이것은 성분 산술 검산이며 거래소 실행 검증이 아니다.','',
        '[사전 범위와 BTC 예비 조회 구분](E037_FUNDING_OPPORTUNITY.md) · [계산 결과](../../../reports/validation/e037_funding_opportunity_20260919_v2/summary.json) · [독립 검산](../../../reports/validation/e037_funding_opportunity_20260919_v2/independent_audit.json)','',
        '자료 정의: [Binance 펀딩 기록 API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History). 배경 문헌: [BIS Crypto carry](https://www.bis.org/publications/working-paper-1087-crypto-carry). 위 고정 필터의 수익성을 문헌이 검증했다는 뜻은 아니다.']
    report=ROOT/'docs/research/experiments/E037_RESULTS_2026_09_19.md'
    with report.open('x') as f:f.write('\n'.join(lines)+'\n')
    payload={'schemaVersion':1,'items':[{'id':'funding-income-screen','title':'과거 정보로 선택한 펀딩 수입의 경제성','queries':[{
        'id':'e037-three-contracts','source':{'label':'E037 공식 펀딩 기록과 고정 비용 산술',
        'files':[{'label':str(OUT/'summary.json')},{'label':str(OUT/'independent_audit.json')},{'label':str(report)}],
        'metricDefinitions':[{'label':'조건부 순액','definition':'양 다리 각각 명목400 USDC를 가정한 역사적 펀딩 수입에서 가정한 진입·청산 비용과 스트레스 펀딩 차감.'}],
        'filters':['BTCUSDC, ETHUSDC, SOLUSDC의 확정 펀딩 각2,190건','이전21개 정산 합이66bp를 초과하면 다음21개 정산 보유'],
        'caveats':['가격 괴리·수량 조정·체결·담보·운영비가 통합된 계좌 수익이 아니다.','BTC·ETH의0은 무거래이며 SOL은1회뿐이다.',
                   '5% 낙폭 준수 및 미래 수익성을 검증하지 않았다.','정산당1bp 추가 부담은 연구 스트레스이며 실제 거래소 수수료가 아니다.'],
        'evidenceFlow':[{'kind':'validation','title':'시각·원본·산술 대조','detail':'기존 해시 및 공개 원문 보존,8시간 달력 확인, 정수 별도 계산으로 진입과 순액 대조.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'symbol','label':'종목'},{'field':'cycles','label':'진입 횟수'},{'field':'base_net','label':'기본 순액 USDC'},{'field':'stress_net','label':'스트레스 순액 USDC'}],
        'rows':[{k:r[k] for k in ['symbol','cycles','base_net','stress_net']} for r in rows],
        'methods':[{'language':'calculation','code':'400 × sum(selected future funding rates) − cycles × (1.32 base / 1.80 stress) − 0.04 × selected settlement count in stress. Historical rates available through decision time only select entries.'}]}]}]}
    with (OUT/'delivery_sources.json').open('x') as f:json.dump(payload,f,ensure_ascii=False,indent=2)
    print(report)


if __name__=='__main__':main()
