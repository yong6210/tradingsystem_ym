"""E044 report: execution availability versus economic value, with paired entries."""
from decimal import Decimal as D
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import load,lines,save,digest
from scripts.run_time_exit_policy import check_hashes
OUT=ROOT/'reports/validation/e044_minimum_contract_20260919'
PRIOR=ROOT/'reports/validation/e043_funding_tail_20260919'
REPORT=ROOT/'docs/research/experiments/E044_RESULTS_2026_09_19.md'


def main():
    s=load(OUT/'summary.json');v=load(OUT/'verification.json');reg=load(OUT/'registration.json')
    check_hashes(reg['source_hashes']);check_hashes(reg['input_hashes'])
    for name,h in v['artifacts'].items():
        if digest(OUT/name)!=h:raise ValueError('changed E044 artifact')
    for name,h in load(PRIOR/'verification.json')['artifacts'].items():
        if digest(PRIOR/name)!=h:raise ValueError('changed E043 artifact')
    rows=[];cash_checks=0;post_halt=[]
    for key,r in s['runs'].items():
        if key.endswith('OHLC') and r!=s['runs'][key[:-4]+'OLHC']:raise ValueError('report separate paths')
        events=lines(OUT/key/'events.jsonl');entries={e['time']:e for e in events if e['kind']=='entry'}
        for t in lines(OUT/key/'trades.jsonl'):
            e=entries[t['entry_time']];cash=D(str(e['balance']))+D(str(e['fee']))
            budget=D(str(t['budget']));loss=D(str(t['planned_loss']))
            if min(abs(budget-cash*f) for f in (D('.005'),D('.0025')))>D('.000001'):raise ValueError('unregistered budget fraction')
            if loss>cash*D('.005')+D('.000001') or D(str(t['quantity']))*D(str(t['entry_price']))>cash+D('.000001'):
                raise ValueError('cash-based risk/notional limit')
            cash_checks+=1
        halt=r['metrics']['halt_time']
        if halt:
            later=[e for e in events if e['time']>halt]
            if any(e['kind']!='operating' for e in later):raise ValueError('post-halt order')
            cash=D(str([e for e in events if e['time']<=halt][-1]['balance']));expense=sum((D(str(e['amount'])) for e in later),D(0))
            if abs(cash-expense-D(str(r['metrics']['final_equity'])))>D('.000001'):raise ValueError('post-halt cash mismatch')
            post_halt.append(dict(run=key,subsequent_cost=str(expense)))
    for model in ('TAIL','LONG00'):
        for op in (0,2):
            for cost in ('base','stress'):
                key=f'{cost}_{model}_op{op}_OHLC';r=s['runs'][key];m=r['metrics'];d=r['diagnostics'];p=s['paired'][key]
                old=load(PRIOR/key/'metrics.json')
                rows.append(dict(model=model,op=op,cost=cost,old_net=p['old_net'],new_net=p['new_net'],
                    old_trades=old['cycles'],new_trades=m['cycles'],dd=m['max_drawdown_pct'],
                    longest_underwater_days=d['calendar_risk']['longest_underwater_days'],
                    rejected=m['actions'].get('size_constraint',0),halted_entries=m['actions'].get('halted_entry',0),
                    added_net=p['added_realized_net'],added_trades=p['added_entries']))
    save(OUT/'delivery_audit.json',dict(status='PASS_CASH_BASED_BUDGET_AND_PAIRED_ENTRY_REPORT',cash_based_entry_checks=cash_checks,
        post_halt=post_halt,rows=rows))
    text=['# E044 결과 — 주문 가능성은 개선됐지만 비용 여유는 부족','',
        '**E043의 거래당0.25% 제약이 실제로 대부분의 매매를 막았음을 확인했다. 최소 계약만 주문하고 계획손실 상한을0.5%로 둔 진단에서는 운영비0 후보 거래가7회에서128~130회로 늘었다. 그러나2년 순익은 +9.75~+16.12 USDC이며 월2 USDC 운영비 시나리오에서는 약−48 USDC다.** 거래 가능성과 비용을 감당하는 수익성은 별개로 판정한다.','',
        '사용자는 손실5% 선호를 말했고, 거래당0.25%·손절3ATR는 우리가 정했다. 이번0.5% 상한은 기존 총 계획위험0.5%를 단일 최소 계약의 허용 한도로 사용한 연구 가정이다. 이전 결과를 본 뒤 원인을 확인하기 위해 추가한 설정이므로 독립 수익성 검증이나 최적 위험 설정으로 소개하지 않는다. 신호·보유·손절·초기자본·명목상한은 유지했고 다른 위험 배수를 검색하지 않았다.','',
        '## 같은 기회의 기존 계좌와 최소 계약 진단','',
        '초기1,000 USDC, BTCUSDC, 2024-09-01~2026-09-01 미만730일. 모든 금액은2년 전체 USDC 순익이다. 편도 수수료0.025%, 슬리피지 기본2/스트레스5bp, 실제 펀딩 및 스트레스 정산당1bp. 운영비는 매월 계좌에서 먼저 차감한다.','',
        '| 규칙 | 월비용 가정 | 거래비용 | 기존 순익 | 최소 계약 순익 | 기존→신규 거래 수 | 신규 최대 낙폭 | 신규 최장 미회복 |',
        '|---|---:|---|---:|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['model']} | {r['op']} | {r['cost']} | {r['old_net']:+.2f} | {r['new_net']:+.2f} | {r['old_trades']}→{r['new_trades']} | {r['dd']:.2f}% | {r['longest_underwater_days']}일 |")
    text+=['',
        'TAIL은 펀딩 하위분위 후보, LONG00은 매일00시 단순 매수 대조다. OHLC/OLHC 집계가 같아 표는 한 번만 표시했다. 신규16계좌와 동결 E043의16계좌를 대조했다. 대조의월2 낙폭은 중단 후 비용 지속 때문에5%를 초과하며 이를 적격으로 표시하지 않았다. 후보월2 낙폭은5% 이내여도 수익 조건은 미통과다. 미회복은 일별 종가 기준이며 기간말까지 회복하지 못한 기간을 포함한다.','',
        '## 더 실행된 거래가 만든 손익','',
        '| 후보 조건 | 새로 실행한 거래 수 | 추가 거래의 원장 순손익 USDC | 두 계좌 전체 순익 차이 USDC |',
        '|---|---:|---:|---:|']
    for r in rows:
        if r['model']=='TAIL':text.append(f"| 월{r['op']} · {r['cost']} | {r['added_trades']} | {r['added_net']:+.2f} | {r['new_net']-r['old_net']:+.2f} |")
    text+=['',
        '이 후보에서는 공통 진입 거래의 손익이 같고 기존에 실행하던 거래의 소실이 없어, 전체 차이가 추가 진입 거래 손익과 정확히 일치했다. 운영비0에서 거래 기회 회복이 수익을 늘렸지만 월2에서는 추가 거래 합이 음수였다. 서로 다른 비용 시나리오 간에는 잔고·경고·후속 거래가 달라지므로 이 표를 모든 가능한 위험 정책의 인과효과로 일반화하지 않는다.','',
        '운영비0에서는152개 신호 중 기본22/스트레스24개만 수량 제약으로 거절됐다. 월2에서는 기본75/스트레스69회가 실행되고 수량 거절72/63개, 위험 중단 거절5/20개가 남았다. 경고2.5% 이후 예산절반과 중단4%를 유지했기 때문이다. 비용을 넣은 후보의 거래손익은 기본−0.03/스트레스−0.34 USDC이고 여기에 운영비48 USDC가 더해진다. 따라서 운영비0 순익에서48만 빼면 실제 계좌 경로를 재현하지 못한다.','',
        '운영비0 스트레스 후보의 최장 미회복은316일이다. 상위5개 거래 이익이 모든 수익 거래 이익에서 차지하는 비중은27.89%이고, 그 거래 손익을 원장에서 산술 제외하면−14.16 USDC다. 이는 재시뮬레이션이 아닌 집중도 진단이며 특정 거래를 사전에 제거할 수 있다는 뜻이 아니다. 기존 E043 사건 평균의 탐색구간도0을 포함하므로 신호 자체의 불확실성이 해소된 것은 아니다.','',
        '## 계약 조건과 검산','',
        '2026-09-19 KST의 공식 공개 exchangeInfo 조회에서 BTCUSDC의 LOT_SIZE/MARKET_LOT_SIZE 최소수량·단위0.001, 최소명목50 USDC, 가격단위0.1을 재확인했다. 기존 가정과 같아 모델 계약 조건을 바꾸지 않았다. 현재 조회가 역사적 계약 조건이나 실제 계정 요율·체결을 확인한 것은 아니다. [Binance 공식 API 정의](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).','',
        f"관련 {v['focused_tests']}개 검사, 기존 엔진 본문과 수량 함수 연결 외 동일성, 저장 신호·원본 해시,16계좌 Decimal 원장·일평가·비용 달력·최소 적격 수량·계획손실·국소 손절 검산을 완료했다. 추가로 실제 진입 전 현금에서 예산·명목 제한 {cash_checks}건과 중단 후 비용을 검산했다. OHLC/OLHC의 동일 거래를 독립 표본으로 세지 않는다. 실제 틱·마크 증거금·강제청산·전체 고점 경로의 독립 재현은 미포함이다.",'',
        '## 결정','',
        '**0.25% 가정 때문에 실행 가능한 전략을 과도하게 걸러낼 수 있다는 문제는 확인했다. 동시에 그 제약을 완화해도 이번 최소 계약 후보의 수익 여유는 작았다.** 실제 운영비는 미정이며 월0/2 모두 연구 시나리오다. 운영비0의 양수 결과는 조건부로 보존하고 월2 비용의 채택은 보류한다. 작은 양수를 실용 목표 달성으로 확정하거나 예시 비용을 실제 청구액으로 취급하지 않는다.','',
        '현재 실용 순익 후보 확보는 미완료다. 이번 설정을 새 기본값이나 최적 배수로 채택하지 않고 추가 배수·손절 검색도 종료한다. 실제 운영비를 확인해 경제성 판단을 맞추고, 다음 후보에는 최소 계약의 진입 가능성까지 사전 조건으로 포함한다. 위험 확대만으로 수익 목표를 대신하거나 근거 없는 결합·운영 확대를 진행하지 않는다. 실주문·예약·계정 접근·유료자료 없음.','',
        '[사전 명세](E044_MINIMUM_CONTRACT_DIAGNOSTIC.md) · [전체 결과와 거래 대조](../../../reports/validation/e044_minimum_contract_20260919/summary.json) · [계좌 검산](../../../reports/validation/e044_minimum_contract_20260919/verification.json) · [현금 기준 위험·중단 이후 검산](../../../reports/validation/e044_minimum_contract_20260919/delivery_audit.json) · [공개 계약 조건](../../../reports/validation/e044_contract_preflight_20260919/btcusdc_filters.json)']
    with REPORT.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'minimum-contract','title':'최소 주문 제약 완화의 수익 효과','queries':[{
        'id':'e044','source':{'label':'E043/E044 고정 신호 계좌 대조',
        'files':[{'label':'E044_RESULTS_2026_09_19.md'},{'label':'E044 summary.json'},{'label':'delivery_audit.json'}],
        'metricDefinitions':[{'label':'2년 순익 USDC','definition':'최종 청산 자산−최초1,000. 표시한 운영비와 거래비용 포함.'}],
        'filters':['같은 신호·3ATR·보유·재진입','최소 수량만 주문, 계획손실 상한0.5%, 경고2.5%·중단4% 유지'],
        'caveats':['사후 원인 진단이며 독립 수익성 검증이 아니다.','실제 운영비 미정, 월0/2는 연구 가정.','세부 위험값은 사용자 확정값이 아니다.','계약 분봉 가정 경로, 실제 체결·증거금 검증 미포함.'],
        'evidenceFlow':[{'kind':'validation','title':'동일 신호와 실제 최소 주문 산술','detail':'원본·공개 계약 응답 해시,16계좌 원장·비용·최소 수량·현금 예산 및 거래별 추가 손익 대조.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'model','label':'규칙'},{'field':'op','label':'월비용'},{'field':'cost','label':'비용조건'},
            {'field':'old_net','label':'기존 순익'},{'field':'new_net','label':'최소계약 순익'},{'field':'new_trades','label':'거래 수'},{'field':'dd','label':'최대낙폭 %'}],
        'rows':rows,'methods':[{'language':'calculation','code':'Paired entry attribution: added_trade_net - lost_old_trade_net + common_trade_net_difference = total_account_net_difference, with identical monthly operating charges.'}]}]}]}
    save(OUT/'delivery_sources.json',receipt)
    save(OUT/'delivery_verification.json',dict(status='PASS_SCOPED_DELIVERY_WITH_RESEARCH_LIMITATIONS',prior_verification_sha256=digest(OUT/'verification.json'),
        artifact_hashes={str(p.relative_to(ROOT)):digest(p) for p in (REPORT,Path(__file__),OUT/'delivery_audit.json',OUT/'delivery_sources.json')}))
    print(REPORT)


if __name__=='__main__':main()
