"""Explicit hypothetical long campaigns on real observations; not a backtest."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.position_alternatives import PositionExample,ExampleCosts,alternative
from app.research.recovery.models import dec,jsonable


def stamp(s):return int(datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()*1000)
def utc(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()


def run_path(initial,costs,steps):
    position=initial;last=-1;history=[]
    for s in steps:
        if s['decision_ms']<=last or s['evidence_available_ms']>s['decision_ms']:
            raise ValueError('unordered decision or future evidence')
        action=s['action']
        quantity=position.quantity/2 if action=='retracement_reduce' else s.get('quantity',0)
        result=alternative(position,costs,mark=s['mark'],action=action,quantity=quantity,stress_moves=(2000,3000))
        history.append(dict(step=s,before=position,result=result))
        position=result['after'];last=s['decision_ms']
    return dict(initial=initial,history=history,final=position,orders_generated=0)


def run():
    events_source=ROOT/'reports/validation/frozen_zone_path_48h_20260919/events.jsonl'
    contacts_source=ROOT/'reports/validation/grouped_contact_positions_20260919/comparison.json'
    events=[json.loads(line) for line in events_source.read_text().splitlines()]
    contacts=json.loads(contacts_source.read_text())['cards']
    t1=stamp('2026-08-15T09:28:00Z');t2=stamp('2026-08-15T17:55:00Z');t3=stamp('2026-08-16T22:56:00Z')
    first=next(e for e in events if e['available_ms']==t1 and e['zone_id']=='Z01')
    second=next(c['contact'] for c in contacts if c['contact']['available_ms']==t2)
    third=next(e for e in events if e['available_ms']==t3 and e['zone_id']=='Z01')
    observations=[first,second,third]
    reasons=[
        '구간 상단 회복. 추가 물량을 덜어낼 되돌림으로 판단했다고 가정한다. 그 발동 기준은 아직 미확정이다.',
        '새 저점 62,971의 확인 후 접촉·위 마감. 재추가에 충분한 반응인지 미확정이므로 두 경로로 비교한다.',
        'Z01 아래에서 재접근·아래 마감. 반등에서 추가 물량을 덜기로 판단했다고 가정한다. 전체 추세 전환으로 취급하지 않는다.']
    costs=ExampleCosts('.0004','.00005','.0002','.1','.001','2')
    initial=PositionExample(1,'.2',63050,0,'5.044','5.044',10000)
    paths=[]
    for name,middle in [('readd_assumed','increase'),('readd_deferred','wait')]:
        steps=[]
        for i,(t,e,a) in enumerate(zip((t1,t2,t3),observations,('retracement_reduce',middle,'retracement_reduce'))):
            steps.append(dict(decision_ms=t,evidence_available_ms=e['available_ms'],mark=e['close'],action=a,
                quantity='.1' if a=='increase' else 0,reason=reasons[i],decision_status='explicit_hypothesis_not_signal'))
        path=run_path(initial,costs,steps);path['id']=name;paths.append(path)
    summary=[]
    for p in paths:
        final=p['history'][-1]['result']
        summary.append(dict(path=p['id'],quantity=p['final'].quantity,average=p['final'].average,
            realized_gross=p['final'].realized_gross,paid_costs=p['final'].paid_costs,total_net=final['total_net'],
            adverse_3000=final['adverse_scenarios'][-1]['pnl']))
    artifact=dict(status='conditional_inventory_path_not_historical_execution',paths=paths,summary=summary,
        observed_events=observations,assumptions=dict(costs=costs,
            direction='long maintained as an explicit hypothetical input; not inferred or verified',
            initial='added inventory .2 BTC at pooled 63050; no historical entry fills reconstructed',
            fills='instant mathematical execution around observation close with assumed costs; no actual quotes, liquidity or partial fills',
            funding='zero assumption across the period, not historical funding',
            margin='2x simple proxy; not exchange availability',
            comparison='different quantities and risks; no equal-risk strategy performance comparison'),
        orders_generated=0,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (events_source,contacts_source)},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/position_alternatives.py')})
    names={'readd_assumed':'새 반응에서 재추가한다고 가정','readd_deferred':'새 반응에서 재추가를 보류한다고 가정'}
    actions={'retracement_reduce':'당시 총수량 절반 축소','increase':'0.1 재추가','wait':'대기'}
    lines=['# 같은 방향 보유에서 구간 역할과 수량의 시간순 연결','',
        '실제 관찰 가격을 사용한 두 개의 가정 경로다. 주된 롱 방향 유지와 세 시점의 행동은 시험용 가정이며 매매 신호로 승인하지 않았다.',
        '출발: 롱 0.2 BTC, 통합평단 63,050, 초기 진입 비용 5.044 USDC, 초기 계좌 10,000. 과거 실제 진입 재현이 아니다.',
        '각 관찰 종가 주변에서 즉시 계산상 체결을 가정한다. 편도 수수료 4bp·반스프레드 0.5bp·슬리피지 2bp·펀딩 0. 실제 호가·유동성·부분 체결은 반영하지 않았다.',
        '모든 단계에서 이전 실현손익·비용·잔량을 다음 단계로 넘긴다. 이전 카드처럼 단계마다 계좌를 초기화하지 않는다.','']
    for p in paths:
        lines+=['## '+names[p['id']],'',
            '| 판단 UTC | 실제 관찰 종가 | 가정 행동 | 이전→이후 BTC | 잔여 평단 | 누적 실현총손익 | 누적 비용 | 전체 순손익 |',
            '| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |']
        for h in p['history']:
            s=h['step'];r=h['result'];after=r['after']
            lines.append(f"| {utc(s['decision_ms'])} | {dec(s['mark']):,.1f} | {actions[s['action']]} | {h['before'].quantity:.3f}→{after.quantity:.3f} | {after.average:.2f} | {after.realized_gross:.2f} | {after.paid_costs:.2f} | {r['total_net']:.2f} |")
        lines.append('')
    lines+=['## 各시점 판단 가정'.replace('各','각 '),'']
    for t,r in zip((t1,t2,t3),reasons):lines.append(f'- {utc(t)}: {r}')
    lines+=['','최종 잔량은 두 경로가 다르다. 최종 손익 차이를 전략의 우열·수익성 입증으로 해석하지 않는다.',
        '마지막 축소도 그 시점 총수량의 절반이다. 단순 새 봉마다 반복 축소한 것이 아니라 별도 되돌림 판단을 가정했다. 실제 발동 판정은 미완성이다.',
        '약손절·반대 방향 진입은 이 예시에 넣지 않았다. 국소 지지 근거가 약해졌다는 관찰만으로 전체 방향을 바꾸지 않는다.']
    out=ROOT/'reports/validation/cycling_role_examples_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'paths.json').write_text(json.dumps(jsonable(artifact),ensure_ascii=False,indent=2)+'\n')
    (out/'paths.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(jsonable(summary)))


if __name__=='__main__':run()
