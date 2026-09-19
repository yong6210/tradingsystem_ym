"""Deduplicated observed contacts with independent hypothetical inventory arithmetic."""
from pathlib import Path
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.contact_groups import group_contacts
from app.research.recovery.position_alternatives import PositionExample, ExampleCosts, alternative
from app.research.recovery.models import dec,jsonable
from scripts.review_decision_card_structure import utc


def run():
    source=ROOT/'reports/validation/post_confirmation_cases_20260919/cases.json'
    original=json.loads(source.read_text())
    groups=group_contacts(original['results'],asof_ms=original['end_ms'])
    costs=ExampleCosts('.0004','.00005','.0002','.1','.001','2')
    positions=[]
    for side,avg in ((1,63050),(-1,62800)):
        fee=dec('.2')*avg*costs.fee
        positions.append(PositionExample(side,'.2',avg,0,fee,fee,10000))
    cards=[]
    for group in groups:
        # A group's source count is provenance only; never an input to position sizing.
        cases=[]
        for position in positions:
            actions=[alternative(position,costs,mark=group['close'],action=a,quantity=q,stress_moves=(2000,3000))
                     for a,q in [('wait',0),('increase','.1'),('retracement_reduce','.1')]]
            for r in actions:
                assert r['total_net']==r['after'].realized_gross-r['after'].paid_costs+r['unrealized']
                assert r['change_at_same_mark']<=0
            cases.append(dict(side=position.side,initial=position,alternatives=actions))
        cards.append(dict(contact=group,cases=cases,selected_action=None,
            missing=['주된 방향과 무효화 조건','새 추가 또는 되돌림 축소 자리 판단','실제 체결 잔량·미체결·여력']))
    # Every as-of snapshot contains exactly the observed groups at that time.
    for group in groups:
        t=group['available_ms']
        assert group_contacts(original['results'],asof_ms=t)==[g for g in groups if g['available_ms']<=t]
    assert group_contacts(original['results']*2,asof_ms=original['end_ms'])==groups
    summary=dict(candidate_contacts=original['summary']['new_contacts'],exact_contact_groups=len(groups),
        distinct_minutes=len({g['available_ms'] for g in groups}),
        multi_source_groups=sum(g['source_count']>1 for g in groups),
        hypothetical_alternatives=len(groups)*len(positions)*3,orders_generated=0)
    output=dict(summary=summary,cards=cards,assumptions=dict(costs=costs,
        inventory='independent examples each contact: long .2 at 63050 or short .2 at 62800; not actual fills or continuous account path',
        starting_equity=10000,funding='zero assumed; not historical measurement',
        margin='equity minus notional/leverage proxy, not actual exchange capacity',
        grouping='exact marker price and candle end only; nearby prices not merged; groups not proven independent'),
        source_sha256={str(source.relative_to(ROOT)):hashlib.sha256(source.read_bytes()).hexdigest()},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/contact_groups.py',ROOT/'app/research/recovery/position_alternatives.py')})
    lines=['# 중복 관찰을 묶은 보유 상태 비교','',
        f"후보별 접촉 {summary['candidate_contacts']}개 → 동일 가격·동일 봉 묶음 {len(groups)}개. 실제 분봉 시각은 {summary['distinct_minutes']}개다.",
        '묶음 수도 독립 매매 근거 수가 아니다. 가까운 가격은 임의로 병합하지 않았고 같은 봉의 다른 기준점도 남겼다.',
        '각 묶음에서 롱 0.2 BTC·평단 63,050 또는 숏 0.2 BTC·평단 62,800을 독립적으로 가정한다. 실제 진입·방향 전환·연속 계좌 경로가 아니다.',
        '계좌 10,000 USDC, 초기 진입 수수료 포함. 편도 수수료 4bp, 반스프레드 0.5bp, 슬리피지 2bp, 펀딩 0 가정. 여력은 2배 단순 증거금 산식이다.',
        '0.1 추가와 0.1 축소는 비교용 수량이며 자동 주문 규칙이 아니다. 축소는 총수량 절반에 해당한다.','']
    labels={'wait':'유지','increase':'0.1 추가','retracement_reduce':'총수량 절반 축소'}
    for card in cards:
        g=card['contact']
        lines += [f"## {utc(g['available_ms'])} UTC · 구조 가격 {g['marker_price']:,.1f}",'',
            f"관찰 종가 {g['close']:,.1f}, 원본 후보 {g['source_count']}개, 역할 {', '.join(g['marker_roles'])}. 종가 위치 {g['close_position']}.",
            '출처: '+', '.join(r['candidate_id'] for r in g['sources']), '',
            '| 보유 가정 | 행동 | 잔량 BTC | 전체 순손익 | 여력 변화(가정) | 추가 $3,000 역행 시 전체 순손익 |',
            '| --- | --- | ---: | ---: | ---: | ---: |']
        for case in card['cases']:
            for r in case['alternatives']:
                lines.append(f"| {'롱' if case['side']==1 else '숏'} | {labels[r['action']]} | {r['after'].quantity:.3f} | {r['total_net']:.2f} | {r['free_margin_change']:+.2f} | {r['adverse_scenarios'][-1]['pnl']:.2f} |")
        lines += ['','행동 미확정: '+ ' / '.join(card['missing'])+'.','']
    lines+=['역행 시나리오는 롱 가격 하락·숏 가격 상승이다. 해당 시점 평가손익을 포함하며 미래 청산 비용은 표에서 제외했다. 예상 종료 비용 포함 값은 JSON에 별도로 있다.',
        '원본 후보가 여러 개여도 계산 횟수·수량을 배수로 늘리지 않는다. 이 연구용 비교가 실제 주문 엔진의 중복 주문 방지를 검증한 것은 아니다.']
    out=ROOT/'reports/validation/grouped_contact_positions_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'comparison.json').write_text(json.dumps(jsonable(output),ensure_ascii=False,indent=2)+'\n')
    (out/'comparison.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':run()
