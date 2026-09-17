"""Independent Decimal sizing/ledger checks and E012 diagnostic report."""
from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/e012_account_constraints_20260917'
PRIOR=ROOT/'reports/validation/e011_trend_pullback_20260917'
DATA=ROOT/'data/historical/btcusdc_public_20260917'


def read(path):return json.loads(path.read_text())
def rows(path):return [json.loads(line) for line in path.read_text().splitlines()]
def near(a,b,tolerance='0.000001'):
    if abs(D(str(a))-D(str(b)))>D(tolerance):raise ValueError(f'Decimal mismatch: {a} vs {b}')


def rounding(value,step,up=False):
    return (value/step).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR)*step


def sizing(a,costs,risk,proposal):
    price,close,atr,equity=(D(str(a[k])) for k in ('reference','close','atr','equity'))
    tick=D(str(costs['tick']));side=a['side'];slip=D(str(costs['slippage_bps']))/10000;fee=D(str(costs['fee_bps']))/10000
    entry=rounding(price*(1+side*slip),tick,side==1)
    stop=rounding(close-side*D(str(risk['stop_atr']))*atr,tick,side==-1)
    if stop<=0 or side*(entry-stop)<=0:
        if proposal['approved'] or proposal['reason']!='invalid_stop':raise ValueError('invalid stop mismatch')
        return
    stop_fill=rounding(stop*(1-side*slip),tick,side==-1)
    loss=side*(entry-stop_fill)+(entry+stop_fill)*fee
    fraction=min(D(str(risk['cycle_fraction'])),D(str(risk['aggregate_fraction'])))
    multiplier=D(str(risk['warning_multiplier'])) if a['warned'] else D(1)
    budget=equity*fraction*multiplier;step=D(str(risk['step']));exposure=D(str(risk['exposure_multiple']))
    qty=rounding(min(budget/loss,equity*exposure/entry),step)
    minimum=rounding(max(D(str(risk['minimum_qty'])),D(str(risk['minimum_notional']))/entry),step,True)
    approved=qty>=minimum
    if approved!=proposal['approved']:raise ValueError('sizing approval mismatch')
    required=max(minimum*entry/exposure,minimum*loss/(fraction*multiplier))
    near(proposal['required_equity'],required)
    if approved:
        for k,v in [('quantity',qty),('entry',entry),('stop',stop),('budget',budget),('planned_loss',qty*loss)]:near(proposal[k],v,'0.0000001')
        if qty*loss>budget+D('1e-8'):raise ValueError('budget breached')
    elif proposal['reason']!='size_constraint':raise ValueError('wrong rejection reason')


def ledger(folder,m,funding):
    cash=D(1000);qty=entry=fees=paid=gross=D(0)
    step=D(str(m['risk']['step']));fee=D(str(m['costs']['fee_bps']))/10000
    events=rows(folder/'events.jsonl')
    for e in events:
        if e['kind']=='entry':
            if qty:raise ValueError('entry while held')
            qty=D(str(e['qty']))*e['side'];entry=D(str(e['price']))
            if abs(qty)%step:raise ValueError('off-step quantity')
            charge=abs(qty)*entry*fee;near(e['fee'],charge);cash-=charge;fees+=charge
        elif e['kind']=='exit':
            if not qty or e['side']*qty>=0:raise ValueError('bad exit')
            near(e['qty'],abs(qty));price=D(str(e['price']))
            pnl=qty*(price-entry);charge=abs(qty)*price*fee
            near(e['pnl'],pnl);near(e['fee'],charge);cash+=pnl-charge;gross+=pnl;fees+=charge;qty=entry=D(0)
        elif e['kind']=='funding':
            source=funding[e['settlement_ms']];mark=D(str(source['markPrice']));rate=D(str(source['fundingRate']))
            near(e['mark'],mark);near(e['rate'],rate)
            amount=qty*mark*rate+abs(qty)*mark*D(str(m['costs']['funding_bps_8h']))/10000
            near(e['amount'],amount);cash-=amount;paid+=amount
        else:raise ValueError('unknown event')
        near(e['balance'],cash);near(e['quantity'],qty);near(e['average'],entry)
    if qty:raise ValueError('unclosed final position')
    for key,v in [('final_equity',cash),('fees',fees),('funding',paid),('realized',gross)]:near(m[key],v)
    trades=rows(folder/'trades.jsonl')
    if len(trades)!=m['cycles']:raise ValueError('trade count mismatch')
    near(sum(D(str(t['net_pnl'])) for t in trades),cash-1000)
    for t in trades:
        if D(str(t['planned_loss']))>D(str(t['budget']))+D('1e-8'):raise ValueError('planned risk breached')
    return dict(events=len(events),cycles=len(trades),status='PASS')


def main():
    registration,summary=read(OUT/'registration.json'),read(OUT/'summary.json')
    for name,digest in registration['source_hashes'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise ValueError('changed source: '+name)
    profiles=summary['settings']['profiles']
    if read(OUT/'status.json')['status']!='COMPLETE' or len(summary['runs'])!=8:raise ValueError('incomplete diagnosis')
    funding={}
    for record in read(DATA/'manifest.json')['funding_sources']:
        raw=(ROOT/record['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('funding bytes changed')
        for e in json.loads(raw):
            if e['fundingTime'] in funding and funding[e['fundingTime']]!=e:raise ValueError('conflicting funding')
            funding[e['fundingTime']]=e
    checks={};sizing_checks=0;snapshot_checks=0
    for key,m in summary['runs'].items():
        folder=OUT/key
        if read(folder/'metrics.json')!=m:raise ValueError('summary mismatch')
        checks[key]=ledger(folder,m,funding)
        attempts=rows(folder/'sizing_attempts.jsonl')
        for a in attempts:sizing(a,m['costs'],m['risk'],a['proposal']);sizing_checks+=1
        if sum(not a['proposal']['approved'] for a in attempts)!=len(rows(folder/'rejections.jsonl')):raise ValueError('rejection count mismatch')
        if len(rows(folder/'risk_transitions.jsonl'))!=int(m['warned']):raise ValueError('warning count mismatch')
        if key.endswith('contract_half'):
            saved=rows(folder/'snapshot_choices.jsonl')
            if len(saved)!=len(attempts):raise ValueError('snapshot count mismatch')
            counts=dict(attempts=len(attempts),warned_attempts=0,baseline_rejected=0,rescued_by_full=0,rescued_by_fine=0,rescued_by_both=0)
            for a,s in zip(attempts,saved):
                if a['time']!=s['time']:raise ValueError('snapshot time mismatch')
                for p in profiles:sizing(a,m['costs'],summary['settings']['risk'][p],s['choices'][p]);snapshot_checks+=1
                counts['warned_attempts']+=int(a['warned'])
                if not a['proposal']['approved']:
                    counts['baseline_rejected']+=1
                    for p,c in [('contract_full','rescued_by_full'),('fine_half','rescued_by_fine'),('fine_full','rescued_by_both')]:counts[c]+=int(s['choices'][p]['approved'])
            scenario=key.split('_')[0]
            if counts!=summary['snapshot_checks'][scenario]:raise ValueError('snapshot summary mismatch')
            for name in ('events.jsonl','trades.jsonl','daily.jsonl','rejections.jsonl','metrics.json'):
                if (folder/name).read_bytes()!=(PRIOR/f'{scenario}_P4'/name).read_bytes():raise ValueError('baseline changed')
    for s in ('base','stress'):
        a,b,c,d=(D(str(summary['runs'][f'{s}_{p}']['return_pct'])) for p in profiles)
        values=dict(full_minus_half_contract_pp=b-a,fine_minus_contract_half_pp=c-a,interaction_pp=d-b-c+a,both_minus_baseline_pp=d-a)
        for k,v in values.items():near(summary['contrasts'][s][k],v)
    evidence=dict(status='PASS_SCOPED_DIAGNOSTIC',runs=checks,sizing_checks=sizing_checks,snapshot_checks=snapshot_checks,
                  total_events=sum(v['events'] for v in checks.values()),total_cycles=sum(v['cycles'] for v in checks.values()),
                  registered_sources=len(registration['source_hashes']),baseline='EXACT_E011_P4_BOTH_COSTS')
    artifacts=list(OUT.glob('*/*.jsonl'))+list(OUT.glob('*/metrics.json'))+[OUT/'registration.json',OUT/'summary.json']
    evidence['artifact_hashes']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
    (OUT/'independent_verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
    report=['# E012 위험 축소·주문 제약 진단 — 2026-09-17','',
            '**결론: E011 P4의 비용 민감도에는 위험 경고와 주문 단위의 상호작용이 크게 관여했다. 위험 축소 제거를 최종 설정으로 채택하지 않는다.**','',
            'BTCUSDC2024-09-01~2026-09-01 UTC 미만730일, 초기1,000 USDC. P4 진입/청산 의도는 고정하고4진단 조건×2비용8회 수행. 실제 체결·자본 경로는 조건마다 달라진다. 아래 수익은 연환산이 아닌2년 누적이다.','',
            '| 조건 | 기본 수익 | 기본 최대DD | 스트레스 수익 | 스트레스 최대DD | 스트레스 거래 |',
            '|---|---:|---:|---:|---:|---:|']
    labels=dict(contract_half='현재 제약·경고 후 절반',contract_full='현재 제약·경고 후 축소 없음',fine_half='가상 미세 단위·절반',fine_full='가상 미세 단위·축소 없음')
    for p in profiles:
        a,b=(summary['runs'][f'{s}_{p}'] for s in ('base','stress'))
        report.append(f"| {labels[p]} | {a['return_pct']:+.2f}% | {a['max_drawdown_pct']:.2f}% | {b['return_pct']:+.2f}% | {b['max_drawdown_pct']:.2f}% | {b['cycles']} |")
    report+=['','가상 미세 단위는 최소수량·증분·최소명목을 각각1e-8로 둔 **실제 Binance 주문 불가능 조건**이다. 고정된 수량 제약의 영향을 분리하기 위한 대용이며 해당 수익을 운용 성과로 제시하지 않는다. 경고 축소 제거 조건도 일손실2%·DD8% 중단·주기.5%·명목1배는 유지했다. 실제 주문/설정은 변경하지 않았다.','',
             '## 같은 상태에서 무엇 때문에 진입이 막혔는가','',
             '| 원본 경로 | 수량 판단 | 경고 후 판단 | 거절 | 축소만 해제하면 적격 | 미세 단위면 적격 |',
             '|---|---:|---:|---:|---:|---:|']
    for s,c in summary['snapshot_checks'].items():report.append(f"| {s} | {c['attempts']} | {c['warned_attempts']} | {c['baseline_rejected']} | {c['rescued_by_full']} | {c['rescued_by_fine']} |")
    report+=['','각 거절 시점의 동일 자산·가격·ATR·방향에서 수량만 재계산한 수치다.754건의 적격 전환은754개의 추가 수익 거래를 뜻하지 않는다. 이후 보유 충돌·하드 중단·수량·자본 경로까지 반영한 결과는 첫 표의 별도 전체 실행이다.','',
             '스트레스 원본의 최초 경고는2025-10-21 14:56 UTC였다. 평가자산975.22, 당시고점1,026.67로 낙폭5.01%였다. 경고 이후 위험 예산 절반은 회복해도 유지되는 기존 정책이다. 따라서 단순 수수료 차감뿐 아니라 주문 가능한 최소 수량을 넘느냐가 달라졌다.','',
             '## 경로 차이와 상호작용','',
             '| 비용 | 축소 해제 차이 pp | 제약 완화 차이 pp | 상호작용 pp | 둘 다 변경 pp |',
             '|---|---:|---:|---:|---:|']
    for s,c in summary['contrasts'].items():report.append(f"| {s} | {c['full_minus_half_contract_pp']:+.3f} | {c['fine_minus_contract_half_pp']:+.3f} | {c['interaction_pp']:+.3f} | {c['both_minus_baseline_pp']:+.3f} |")
    report+=['','앞 세 항의 합이 마지막 항과 일치한다. 원장의 한 손실을 유일한 원인별로 나눈 것이 아니라 각 반사실 계좌 경로의 대비다. 기본 실제 제약에서는 경고가 없어 축소 해제 효과가0이지만, 가상 미세 단위에서는 다른 경로로 경고가 발생해 상호작용이 양수가 됐다. 효과가 조건에 따라 달라진다는 뜻이다.','',
             '| 조건 | 스트레스 수량 거절 | 보유 분 비율 | 최종자산 USDC |', '|---|---:|---:|---:|']
    for p in profiles:
        m=summary['runs'][f'stress_{p}'];report.append(f"| {labels[p]} | {m['actions'].get('size_constraint',0)} | {100*m['active_fraction']:.1f}% | {m['final_equity']:.2f} |")
    report+=['','## 이번 진단이 의미하는 것','',
             '- 신호가 나쁘다는 설명만으로 P4의 기본/스트레스 차이를 모두 설명할 수 없었다. 계좌 위험 정책과 최소 주문 조건의 기여도 따로 봐야 한다.',
             '- 축소를 제거하면 이번 스트레스 수익은+2.34%로 회복했지만 최대DD도6.19%로 증가했다. 비교 기준 T0의+4.87%·DD4.72%를 넘는 개선으로 볼 수 없다. 이 비교 역시 같은 노출의 순수 신호 비교가 아니다.',
             '- 위험 장치가 불필요하다는 결론은 성립하지 않는다. 회복 정책·경고 기준·자본금을 결과에 맞춰 다시 탐색하지 않았다. 새 위험 정책은 별도 목적/한계/검증 설계가 필요하다.',
             '- 기본5bp/2bp, 스트레스7bp/5bp 및 실제 펀딩+추가1bp 가정 유지. 지정가 수수료0 체결 성과·실제 계정 조건은 미검증이다.',
             '- 이 실험은 경제적 최소 효과/정밀도 합격 문턱을 둔 전략 선발이 아니다. 모든 결과의 분류는 DIAGNOSTIC_COUNTERFACTUAL_NOT_STRATEGY_SELECTION이다.','',
             '## 검증과 다음 작업','',
             f"등록 소스{evidence['registered_sources']}개 유지, E011 P4 양 비용 원장·거래·일별·거절·지표 정확 재현. 별도 Decimal 수량 판단{evidence['sizing_checks']:,}회와 동일 상태 반사실{evidence['snapshot_checks']:,}회, 회계{evidence['total_events']:,}이벤트/{evidence['total_cycles']:,}주기 검산 통과.",
             '분봉의 유리한 극값 순서를 포함한 실제 틱 최대낙폭·거래소 체결·현재 계약 필터의 전 기간 역사적 유효성은 별도 미검증이다. 기존 결과를 삭제/덮어쓰거나 실전 설정을 바꾸지 않았다.',
             '다음은 [진행 방향 검토](../RESEARCH_REVIEW_2026_09_17.md)의 우선순위를 따른다. 경제적 목표와 하방/회복 기준을 먼저 고정하고 연구 후보와 운영 검증 기준을 분리한다. 새로운 후보를 계속 추가하는 것만으로 문제를 해결하지 않는다.','',
             '[실행 전 설계](E012_ACCOUNT_CONSTRAINTS.md). 전체 원장·경고·수량 판단·반사실·검증: `reports/validation/e012_account_constraints_20260917/`.']
    destination=ROOT/'docs/research/experiments/E012_RESULTS_2026_09_17.md';destination.write_text('\n'.join(report)+'\n')
    print(json.dumps({k:v for k,v in evidence.items() if k!='artifact_hashes'},indent=2));print(destination)


if __name__=='__main__':main()
