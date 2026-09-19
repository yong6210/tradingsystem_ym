"""As-of obstacles and cost space for the explicitly hypothetical re-add."""
from pathlib import Path
from zipfile import ZipFile
from decimal import Decimal,ROUND_CEILING
import csv,io,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.position_alternatives import ExampleCosts
from app.research.recovery.round_trip_review import round_trip
from app.research.recovery.models import dec,jsonable


def run():
    path=ROOT/'reports/validation/cycling_role_examples_20260919/paths.json'
    lineage=ROOT/'reports/validation/structure_lineage_20260919/lineage.json'
    zones=ROOT/'reports/validation/volume_zone_review_v02_20260919/frozen_zones.json'
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    plan=json.loads(path.read_text());history=plan['paths'][0]['history'][1]
    t=history['step']['decision_ms'];mark=dec(history['step']['mark']);costs=ExampleCosts(**plan['assumptions']['costs'])
    source=json.loads(lineage.read_text())
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==source['source_sha256'][str(archive.relative_to(ROOT))]
    known=[c for c in source['records'] if c['available_ms']<=t and c['kind']=='high' and dec(c['price'])>mark]
    byprice={}
    for c in known:byprice.setdefault(dec(c['price']),[]).append(c)
    # Nearest five known structural prices are a display selection, not active resistance confirmation.
    selected=sorted(byprice)[:5]
    rows=[]
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as fp:
        for r in csv.DictReader(io.TextIOWrapper(fp)):
            end=int(r['open_time'])+60000
            if end<=t:rows.append(dict(end_ms=end,close=dec(r['close'])))
    targets=[]
    for price in selected:
        refs=byprice[price];states=[]
        for c in refs:
            above=[r for r in rows if c['available_ms']<r['end_ms']<=t and r['close']>price]
            states.append(dict(candidate_id=c['id'],confirmed_ms=c['available_ms'],
                prior_close_above=bool(above),last_above_ms=above[-1]['end_ms'] if above else None))
        targets.append(dict(kind='structural_marker',target_mark=price,sources=states,
            round_trip=round_trip(costs,side=1,quantity='.1',entry_mark=mark,exit_mark=price)))
    frozen=json.loads(zones.read_text())
    above=sorted([z for z in frozen['zones'] if dec(z['low'])>mark],key=lambda z:z['low'])
    z=above[0]
    targets.append(dict(kind='frozen_volume_zone_lower_boundary',zone_id=z['id'],target_mark=dec(z['low']),
        round_trip=round_trip(costs,side=1,quantity='.1',entry_mark=mark,exit_mark=z['low'])))
    entry=costs.execution(mark,1)
    required_exit=entry*(1+costs.fee)/(1-costs.fee)
    quote=required_exit/((1-costs.half_spread)*(1-costs.slippage))
    quote=(quote/costs.tick).to_integral_value(rounding=ROUND_CEILING)*costs.tick
    while round_trip(costs,side=1,quantity='.1',entry_mark=mark,exit_mark=quote)['net']<0:quote+=costs.tick
    assert round_trip(costs,side=1,quantity='.1',entry_mark=mark,exit_mark=quote-costs.tick)['net']<0
    result=dict(decision_ms=t,mark=mark,targets=targets,marginal_round_trip_break_even_mark=quote,
        required_mark_move=quote-mark,position_before=history['before'],readd_result=history['result'],
        assumptions=plan['assumptions'],orders_generated=0,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (path,lineage,zones,archive)},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/round_trip_review.py',ROOT/'app/research/recovery/position_alternatives.py')})
    lines=['# 17:55 재추가의 가격 여유와 비용','',
        f'2026-08-15 17:55 UTC 관찰 종가 {mark:,.1f}. 그 시점까지 확인된 위쪽 구조 가격 중 가까운 다섯 개와 가장 가까운 기존 거래량 구간을 비교한다.',
        '위쪽 가격이라는 이유로 유효 저항으로 확정하지 않는다. 과거에 위 종가가 있었는지 원본별로 표시했다. 근접 가격을 임의로 병합하지 않았다.',
        '추가 0.1 BTC만의 가정 왕복 손익이다. 통합평단 장부의 부분 청산 실현손익·전체 운용 회복 가격과 다르다.',
        '기존 가정 비용: 편도 수수료 4bp·반스프레드 0.5bp·슬리피지 2bp, 펀딩 0. 목표 가격을 관찰 기준 가격으로 보고 양쪽 체결 비용을 적용했다.',
        '해당 목표에 도달하거나 원하는 수량이 체결된다는 가정은 검증하지 않았다.','',
        '| 기준 종류 | 목표 관찰 가격 | 현재에서 거리 | 가정 왕복 순손익 | 확인 후 위쪽 종가를 기록한 출처 수 |',
        '| --- | ---: | ---: | ---: | ---: |']
    for r in targets:
        crossed=str(sum(s['prior_close_above'] for s in r['sources'])) if 'sources' in r else '별도 구간 이력 검토 필요'
        lines.append(f"| {r['kind']} | {r['target_mark']:,.1f} | {r['target_mark']-mark:,.1f} | {r['round_trip']['net']:.4f} | {crossed} |")
    add=history['result']
    lines+=['',f'가정 비용에서 추가분 왕복 본절 관찰 가격은 {quote:,.1f}, 현재보다 {quote-mark:,.1f} USDC 위다. 이보다 한 가격 단위 낮은 경우는 순손실임을 검산했다.',
        f"재추가하면 총수량은 0.1→0.2 BTC, 평단은 63,050→{dec(add['after']['average']):,.2f}. 즉시 비용 영향은 {dec(add['change_at_same_mark']):.4f} USDC, 단순 증거금 여력 변화는 {dec(add['free_margin_change']):.2f} USDC다.",
        '여력 변화는 실제 거래소 사용 가능 증거금이 아니다. 계좌 한도·예비 자금·미체결 예약을 정하지 않았으므로 주문 가능 수량을 승인하지 않는다.',
        '가까운 구조까지의 움직임만 기대한다면 비용을 넘는지 먼저 확인해야 한다. 더 먼 거래량 구간을 목표로 바꾸려면 중간 구조를 통과할 별도 근거가 필요하다.']
    out=ROOT/'reports/validation/readd_room_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'review.json').write_text(json.dumps(jsonable(result),ensure_ascii=False,indent=2)+'\n')
    (out/'review.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines))


if __name__=='__main__':run()
