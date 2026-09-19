"""E046: independently reconcile trades, concentration and cash risk limits."""
from decimal import Decimal as D
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.run_direction_controls import load,lines,save,digest
from scripts.run_time_exit_policy import check_hashes
OUT=ROOT/'reports/validation/e046_weekly_minimum_contract_20260919'
OLD=ROOT/'reports/validation/e039_weekly_long_operations_20260919'
REPORT=ROOT/'docs/research/experiments/E046_RESULTS_2026_09_19.md'


def close(a,b):
    if abs(D(str(a))-D(str(b)))>D('.000001'):raise ValueError('Decimal report reconciliation')


def main():
    reg=load(OUT/'registration.json');s=load(OUT/'summary.json');v=load(OUT/'verification.json')
    old=load(OLD/'summary.json');check_hashes(reg['source_hashes']);check_hashes(reg['input_hashes'])
    for folder in (OUT,OLD):
        for name,h in load(folder/'verification.json')['artifacts'].items():
            if digest(folder/name)!=h:raise ValueError('changed artifact '+str(folder/name))
    rows=[];audits={};cash_checks=0
    for key,r in s['runs'].items():
        prior=old['runs'][key];m=r['metrics'];p=s['paired'][key]
        new_trades=lines(OUT/key/'trades.jsonl');old_trades=lines(OLD/key/'trades.jsonl')
        a={t['entry_time']:t for t in old_trades};b={t['entry_time']:t for t in new_trades}
        added=sum((D(str(b[k]['net_pnl'])) for k in b.keys()-a.keys()),D(0))
        lost=sum((D(str(a[k]['net_pnl'])) for k in a.keys()-b.keys()),D(0))
        common=sum((D(str(b[k]['net_pnl']))-D(str(a[k]['net_pnl'])) for k in a.keys()&b.keys()),D(0))
        close(added-lost+common,p['difference']);close(added,p['added_realized_net'])
        events=lines(OUT/key/'events.jsonl');entries={e['time']:e for e in events if e['kind']=='entry'}
        for t in new_trades:
            e=entries[t['entry_time']];cash=D(str(e['balance']))+D(str(e['fee']))
            if min(abs(D(str(t['budget']))-cash*f) for f in (D('.005'),D('.0025')))>D('.000001'):
                raise ValueError('cash budget fraction')
            if D(str(t['planned_loss']))>cash*D('.005')+D('.000001') or D(str(t['quantity']))*D(str(t['entry_price']))>cash+D('.000001'):
                raise ValueError('cash risk/exposure limit')
            cash_checks+=1
        concentration={}
        for name,trades,data in [('old',old_trades,prior['diagnostics']['trading_concentration']),('new',new_trades,r['diagnostics']['concentration'])]:
            values=[D(str(t['net_pnl'])) for t in trades];positive=sorted((x for x in values if x>0),reverse=True)
            positive_sum=sum(positive,D(0));net=sum(values,D(0));top=sum(positive[:5],D(0))
            close(net,data['net']);close(top/positive_sum,data['top'][1]['positive_profit_share'])
            close(net-top,data['top'][1]['arithmetic_net_without_top'])
            concentration[name]=dict(top5_positive_profit_pct=float(top/positive_sum*100),
                account_net_without_top5=float(net-top-D(str(m['operating_cost']))))
        post_halt_cost=D(0)
        if m['halt_time']:
            later=[e for e in events if e['time']>m['halt_time']]
            if any(e['kind']!='operating' for e in later):raise ValueError('orders after halt')
            post_halt_cost=sum((D(str(e['amount'])) for e in later),D(0))
            last=[e for e in events if e['time']<=m['halt_time']][-1]
            close(D(str(last['balance']))-post_halt_cost,m['final_equity'])
        audits[key]=dict(added_net=str(added),lost_net=str(lost),common_change=str(common),concentration=concentration,
            post_halt_operating_cost=str(post_halt_cost),changed_common=[dict(time=k,old_qty=a[k]['quantity'],new_qty=b[k]['quantity'],
                old_exit=a[k]['exit_time'],new_exit=b[k]['exit_time'],net_change=b[k]['net_pnl']-a[k]['net_pnl'])
                for k in sorted(a.keys()&b.keys()) if abs(a[k]['net_pnl']-b[k]['net_pnl'])>1e-7])
        if key.endswith('OHLC'):
            if r!=s['runs'][key[:-4]+'OLHC']:raise ValueError('separate paths required')
            rows.append(dict(cost=key.split('_')[0],monthly_operations=m['operating_cost']/24,
                old_net=p['old_net'],new_net=p['new_net'],old_dd=prior['metrics']['max_drawdown_pct'],new_dd=m['max_drawdown_pct'],
                old_trades=prior['metrics']['cycles'],new_trades=m['cycles'],old_underwater=prior['diagnostics']['calendar_risk']['longest_underwater_days'],
                new_underwater=r['diagnostics']['calendar_risk']['longest_underwater_days'],
                top5_old=concentration['old']['top5_positive_profit_pct'],top5_new=concentration['new']['top5_positive_profit_pct'],
                without_top5_new=concentration['new']['account_net_without_top5'],added_net=float(added),lost_net=float(lost),common_change=float(common)))
    if any(r['new_net']>=r['old_net'] for r in rows):raise ValueError('report conclusion requires all net results lower')
    save(OUT/'delivery_audit.json',dict(status='PASS_DECIMAL_TRADE_BRIDGE_CONCENTRATION_AND_CASH_LIMITS',
        cash_entry_checks=cash_checks,checks=audits,rows=rows))
    text=['# E046 결과 — 최소 계약으로 거래를 늘려도 주간 매수는 개선되지 않음','',
        '**같은 주간 매수 신호에 기존 E044의 최소 계약 정책을 적용했지만 네 비용 조합 모두 순익이 줄고 최대 낙폭이 커졌다. 운영비 0·스트레스에서 38→52회로 거래가 늘었으나 2년 순익은 +53.41→+41.01 USDC, 최대 낙폭은 1.97→3.16%, 최장 미회복은 218→315일로 악화됐다. 이 변경은 채택하지 않는다.**','',
        '초기 1,000 USDC, BTCUSDC, 2024-09-01~2026-09-01 미만 730일. 기존 E039의 104주 신호·4시간 3ATR·예정 보유·재진입 금지는 동일하다. 편도 수수료 0.025%, 슬리피지 기본 2/스트레스 5bp, 실제 펀딩 및 스트레스 정산당 1bp를 포함한다. 월 운영비 0/2는 미확정 연구 시나리오다.','',
        'E039의 거래당 0.25% 예산 내 수량에서, E044의 0.5% 계획손실 한도 내 최소 적격 수량 정책으로 바꾼 묶음 비교다. 수량과 위험 한도의 순수 효과를 분리한 실험은 아니다. 0.5%는 사용자 확정값도 미래 손실 상한도 아니다. 이후 밝혀진 주문 제약 문제 때문에 E039의 위험 탐색 중단 결정을 이 한 번의 원인 진단에 한정해 재검토했으며, 과거 결과·전역 기본값은 그대로 보존한다.','',
        '## 동일 신호의 계좌 비교','',
        '| 거래 비용 | 월비용 | 2년 순익 기존→신규 | 최대 낙폭 기존→신규 | 거래 수 | 최장 미회복 |',
        '|---|---:|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['cost']} | {r['monthly_operations']:.0f} | {r['old_net']:+.2f}→{r['new_net']:+.2f} USDC | {r['old_dd']:.2f}→{r['new_dd']:.2f}% | {r['old_trades']}→{r['new_trades']} | {r['old_underwater']}→{r['new_underwater']}일 |")
    text+=['','신규 8계좌와 동결 E039 8계좌를 비교했다. OHLC/OLHC 집계가 같아 표에 한 번 표시했다. 최장 미회복은 일별 종가 기준이고 기간말 미회복을 포함한다. 손실 5% 선호는 계좌 고점 대비 낙폭으로 임시 해석했다. 월 2·스트레스 신규 낙폭은 5.56%로 이 기준도 넘었다.','',
        '## 거래가 늘었는데 순익이 줄어든 이유','',
        '| 조건 | 추가 거래 순손익 | 소실된 기존 거래 순손익 | 공통 거래 손익 변화 | 전체 순익 차이 |',
        '|---|---:|---:|---:|---:|']
    for r in rows:text.append(f"| {r['cost']} · 월{r['monthly_operations']:.0f} | {r['added_net']:+.2f} | {r['lost_net']:+.2f} | {r['common_change']:+.2f} | {r['new_net']-r['old_net']:+.2f} |")
    text+=['','단위는 USDC. 추가−소실+공통 변화=전체 순익 차이이며 양 정책의 총 운영비는 같다. 원장 손익의 회계 분해이지 각 정책 요소의 독립적인 인과효과 추정은 아니다.','',
        '운영비 0·스트레스에서 추가 14회가 만든 순익은 합계 +0.89 USDC에 그쳤다. 기존에 하던 38회는 모두 남았고 그중 2026-08-10·08-17 두 거래의 수량이 0.002→0.001 BTC로 줄었다. 두 거래의 청산 시각은 동일했고 손익 변화는 각각 +1.24/−14.53 USDC였다. 이 변화가 공통 거래 −13.29 USDC를 전부 설명한다. 더 많은 기회를 거래할 수 있다는 사실만으로 비용을 감당하는 수익 증가를 얻지는 못했다.','',
        '월 2·스트레스는 2025-12-29 진입 비용 후 중단됐고, 그 후에도 운영비 16 USDC가 계속 차감됐다. 4% 거래 중단이 총 계좌 낙폭 5%를 보장하지 않는 사례다. 중단 뒤 비용을 임의로 없애지 않았으며, 비용 지속과 사라진 후속 거래를 모두 결과에 남겼다.','',
        '## 집중도 감소와 회복 개선은 별개','',
        '| 조건 | 수익 상위 5회 비중 기존→신규 | 신규 상위 5회 산술 제외 후 계좌 순익 |',
        '|---|---:|---:|']
    for r in rows:text.append(f"| {r['cost']} · 월{r['monthly_operations']:.0f} | {r['top5_old']:.2f}→{r['top5_new']:.2f}% | {r['without_top5_new']:+.2f} USDC |")
    text+=['','상위 비중의 분모는 모든 수익 거래의 이익 합이며 전체 순익이 아니다. 산술 제외 수치는 운영비도 포함하고 재시뮬레이션은 아니다. 운영비 0·스트레스의 비중은 68.34→46.39%로 낮아졌지만 상위 5회 제외 후 순익은 여전히 −14.54 USDC다. 수익이 분산됐다는 지표만 보고 순익 감소와 낙폭·회복 악화를 개선으로 표시하지 않는다.','',
        '## 검산과 결정','',
        f"{v['focused_tests']}개 관련 검사, 104주 저장 신호 일치와 직접 분봉 Decimal ATR, 8계좌 원장·일 평가·월 비용·국소 손절·최소 적격 수량/계획손실, {cash_checks}개 실제 진입의 현금 기준 예산/명목 한도, 거래별 손익 분해와 집중도 독립 재계산을 통과했다. 동결 엔진과 최소 계약 엔진은 수량 함수 연결 외 본문 동일성을 확인했다. 소스 {v['source_hashes_unchanged']}개와 산출물 {len(v['artifacts'])}개의 해시를 보존했다.",'',
        '검산 범위 내 결과는 제한을 붙여 공유 가능하다. 실제 틱·계정/증거금·강제청산·계좌 최고점 전체 경로의 별도 엔진 재현은 미포함이다. 같은 과거 표본을 재사용하고 양수 결과를 보고 후보를 고른 사후 진단이다. 기존 0.25%가 최적이라고 증명하지도, 모든 위험 정책이 무효라고 일반화하지도 않는다.','',
        '**결정: 이번 최소 계약 변경은 불채택. 주간 매수의 추가 위험 배수·요일·손절 변경으로 구제하는 탐색은 종료한다.** 기존 E039 양수 결과는 조건부 참고로 보존한다. 다음 후보에는 기존보다 긴 회복·거래 의존을 실제로 줄일 독립적인 수익 근거가 필요하며, 순익과 낙폭을 악화시키는 설정 변경이나 근거 없는 결합을 진행하지 않는다. 실제 운영비와 월 수익 목표는 미정이다. 실용 순익 확보·새 자료 전진 수익성 검증·실운용 준비는 완료되지 않았다. 실주문·새 자료 요청·새 예약은 없다.','',
        '[실행 전 규칙](E046_WEEKLY_MINIMUM_CONTRACT.md) · [전체 결과](../../../reports/validation/e046_weekly_minimum_contract_20260919/summary.json) · [실행 검산](../../../reports/validation/e046_weekly_minimum_contract_20260919/verification.json) · [독립 손익·집중도 검산](../../../reports/validation/e046_weekly_minimum_contract_20260919/delivery_audit.json)']
    with REPORT.open('x') as f:f.write('\n'.join(text)+'\n')
    receipt={'schemaVersion':1,'items':[{'id':'e046','title':'주간 매수 최소 계약 정책의 순익·낙폭 비교','queries':[{
        'id':'paired-accounts','source':{'label':'동결 E039와 E046 동일 주간 신호 계좌',
        'files':[{'label':'E046_RESULTS_2026_09_19.md'},{'label':'summary.json'},{'label':'delivery_audit.json'}],
        'metricDefinitions':[{'label':'2년 순익 USDC','definition':'최종 계좌 자산−최초 1000. 수수료·체결·펀딩·해당 월 운영비 포함.'}],
        'filters':['같은 104주 신호·3ATR·보유 규칙','기존 0.25% 예산 수량 대 0.5% 한도의 최소 계약 정책'],
        'caveats':['양수 후보를 사후 선택한 기존 자료 진단이며 독립 검증이 아니다.','실제 운영비 미정. 위험/수량 묶음 변경이며 새 기본값으로 채택하지 않았다.','상위 거래 제거는 원장 산술이며 재시뮬레이션이 아니다.'],
        'evidenceFlow':[{'kind':'validation','title':'신호·원장·최소 수량·손익 기여 검산','detail':'동결 신호 및 해시, Decimal 원장/현금 예산/손익 분해/집중도, 비용 달력·중단 후 비용 확인.'}]},
        'reportingPeriod':'2024-09-01~2026-09-01 미만 UTC',
        'columns':[{'field':'cost','label':'거래 비용'},{'field':'monthly_operations','label':'월비용'},{'field':'old_net','label':'기존 순익'},{'field':'new_net','label':'신규 순익'},{'field':'new_dd','label':'신규 낙폭 %'}],
        'rows':rows,'methods':[{'language':'calculation','code':'added trade net - lost old trade net + shared trade net change = account net difference. Top-five share uses positive trading profit as denominator.'}]}]}]}
    save(OUT/'delivery_sources.json',receipt)
    save(OUT/'delivery_verification.json',dict(status='PASS_SCOPED_DELIVERY_WITH_POST_HOC_LIMITATIONS',
        prior_verification_sha256=digest(OUT/'verification.json'),old_verification_sha256=digest(OLD/'verification.json'),
        artifact_hashes={str(p.relative_to(ROOT)):digest(p) for p in (REPORT,Path(__file__),OUT/'delivery_audit.json',OUT/'delivery_sources.json')}))
    print(REPORT)


if __name__=='__main__':main()
