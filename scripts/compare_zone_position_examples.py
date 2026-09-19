"""Attach labelled hypothetical inventory states to a real observed zone card."""
from pathlib import Path
import sys,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.position_alternatives import PositionExample, ExampleCosts, alternative
from app.research.recovery.models import dec, jsonable


def run():
    source=ROOT/'reports/validation/frozen_zone_path_48h_20260919/events.jsonl'
    raw=source.read_bytes()
    events=[json.loads(x) for x in raw.splitlines()]
    event=next(e for e in events if e['zone_id']=='Z01' and 'close_inside_to_above' in e['labels'])
    mark=dec(event['close'])
    costs=ExampleCosts('.0004','.00005','.0002','.1','.001','2')
    def seeded(side,qty,avg):
        qty=dec(qty);avg=None if avg is None else dec(avg)
        entry_cost=qty*(avg or 0)*costs.fee
        return PositionExample(side,qty,avg,0,entry_cost,entry_cost,10000)
    cases=[('flat_long_assumption','무포지션·롱 방향 가정',seeded(1,0,None)),
           ('base_long','최초 롱만 보유한 가정',seeded(1,'.1',63300)),
           ('added_long','롱 추가 후 총 0.2 BTC 가정',seeded(1,'.2',63050)),
           ('added_short','별도 숏 방향·총 0.2 BTC 가정',seeded(-1,'.2',62800))]
    rows=[]
    for key,label,position in cases:
        actions=[('wait',0),('increase','.1')]
        if position.quantity:
            actions += [('retracement_reduce',position.quantity/2),
                        ('partial_loss_example','.02' if position.quantity==dec('.1') else '.05')]
        results=[alternative(position,costs,mark=mark,action=a,quantity=q,stress_moves=(2000,3000)) for a,q in actions]
        for r in results:
            assert r['change_at_same_mark']<=0
        rows.append(dict(id=key,label=label,initial=position,alternatives=results))
    # Retain realized loss in a subsequent re-add instead of resetting the campaign.
    half=next(r for r in rows[2]['alternatives'] if r['action']=='retracement_reduce')
    readd=alternative(half['after'],costs,mark=mark,action='increase',quantity='.1',stress_moves=(2000,3000))
    artifact=dict(status='hypothetical_action_arithmetic_not_trading_advice_or_backtest',
                  observed_market_event=event,assumptions=dict(costs=costs,starting_equity=10000,
                  position_sizes_and_entry_prices='invented for comparison; not historical fills',
                  direction='conditional scenario, not inferred from this candle or a single timeframe',
                  partial_loss_quantity='comparison only, not an approved weak-stop rule',
                  funding='zero in this arithmetic example; not a claim that historical funding was zero',
                  margin='equity minus notional/leverage proxy, not exchange margin or liquidation capacity'),
                  cases=rows,immediate_readd_after_half=readd,
                  source_event_sha256=hashlib.sha256(raw).hexdigest(),
                  source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
                      [Path(__file__),ROOT/'app/research/recovery/position_alternatives.py']})
    out=ROOT/'reports/validation/zone_position_examples_20260919'
    out.mkdir(parents=True,exist_ok=False)
    (out/'comparison.json').write_text(json.dumps(jsonable(artifact),ensure_ascii=False,indent=2)+'\n')
    names=dict(wait='대기',increase='0.1 BTC 추가',retracement_reduce='총수량 절반 축소',partial_loss_example='일부 손실 확정 예시')
    lines=['# 같은 가격, 다른 보유 상태 — 비교 계산','',
           f'실제 관찰 가격 {mark:,.1f} USDC, 2026-08-15 09:28 UTC. 계좌·보유량·진입가는 설명용 가정이다.',
           '수수료 편도 4bp, 반스프레드 0.5bp, 슬리피지 2bp, 가격 단위 0.1, 수량 단위 0.001. 증거금은 2배 단순 산식이다.',
           '실제 주문 추천·손익 백테스트가 아니다. 약손절 기준과 수량도 확정하지 않았다.','']
    for case in rows:
        lines += ['## '+case['label'],'',
                  '| 행동 | 보유 BTC | 통합평단 | 누적 실현총손익 | 전체 순손익 | 여력 변화(가정) | 전체 회복 체결가 | 추가 $3,000 역행 시 순손익 |',
                  '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
        for r in case['alternatives']:
            p=r['after'];be=r['campaign_break_even_fill']
            lines.append(f"| {names[r['action']]} | {p.quantity:.3f} | {p.average if p.average is not None else '—'} | {p.realized_gross:.2f} | {r['total_net']:.2f} | {r['free_margin_change']:+.2f} | {f'{be:.2f}' if be else '—'} | {r['adverse_scenarios'][-1]['pnl']:.2f} |")
        lines.append('')
    lines += ['## 판정에 사용할 구분','',
              '- 같은 가격에서 물량을 줄인다고 이미 발생한 손실이 사라지지 않는다. 비용만큼 순손익이 감소하고 이후 가격 민감도·필요 증거금이 줄어든다.',
              '- 추가하면 평균가가 유리해질 수 있지만 노출·추가 역행 손실도 커진다. 평균가 개선을 이익 또는 위험 감소로 취급하지 않는다.',
              '- 전체 회복 체결가는 과거 실현손익과 비용을 포함한다. 여기서는 미래 종료 수수료를 포함하지만 체결가 자체를 출력하므로 호가·가격 단위까지 반영한 주문 가격이 아니다.',
              '- 여력 변화는 단순 증거금 산식의 변화다. 유지증거금·교차/격리·다른 포지션·거래소 예약을 반영하지 않는다.',
              '- 마지막 스트레스 열은 추가 $3,000 역행 시 평가손익 포함 전체 순손익이며 그때의 미래 종료 비용은 제외한다. 종료 비용 포함 값은 JSON에 별도 기록했다.',
              '- 일부 손실 확정 예시는 총수량 절반 축소와 다른 행동이다. 이 수량을 약손절 기본값으로 채택하지 않는다.',
              '- 이 구간에서 롱·숏 중 무엇이 맞는지는 이 산식이 정하지 않는다. 주된 방향과 매물대 반응, 대응 여력을 결합해야 한다.','',
              f"추가 롱 예시에서 절반 축소 직후 같은 기준 가격에 0.1 BTC를 즉시 재추가하면 전체 손익은 {half['total_net']:.2f} → {readd['total_net']:.2f}로 변한다. 줄였다가 바로 다시 늘리는 데 드는 비용을 보여주는 비교이며 실제 재진입 추천이 아니다."]
    (out/'comparison.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(jsonable(dict(mark=mark,cases=len(rows),actions=sum(len(c['alternatives']) for c in rows),
        added_long=[{k:r[k] for k in ('action','total_net','free_margin_change','campaign_break_even_fill')} for r in rows[2]['alternatives']]))))


if __name__=='__main__':run()
