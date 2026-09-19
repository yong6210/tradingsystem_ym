"""Read-only episode/cost attribution of the frozen cycling replay.

The initial-size holding baseline is a same-end-price accounting comparison,
not an executable alternative strategy or an equal-risk performance comparison.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from decimal import Decimal as D
import csv
import io
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.models import jsonable


def analyze(rows, final_mark, end_ms):
    episodes, readds = [], []
    current = None
    last_time = -1
    direction = None
    for row in rows:
        if row['time_ms'] < last_time:
            raise ValueError('event stream out of order')
        last_time = row['time_ms']
        if row['kind'] == 'direction':
            direction = row['assessment']
        if row['kind'] == 'funding':
            if current is None:
                raise ValueError('funding without position')
            cost = D(row['signed_cost'])
            if D(row['quantity']) != current['quantity']:
                raise ValueError('funding quantity mismatch')
            current['funding_cost'] += cost
            current['baseline_funding_cost'] += cost / current['quantity'] * current['initial_quantity']
        if row['kind'] != 'fill':
            continue
        qty, price, fee = (D(row[k]) for k in ('quantity', 'price', 'fee'))
        if current is None:
            if row['order_kind'] != 'increase' or D(row['previous_quantity']) != 0:
                raise ValueError('episode must begin flat')
            current = dict(index=len(episodes)+1, side=row['side'], start_ms=row['time_ms'],
                           initial_quantity=qty, initial_price=price, initial_fee=fee,
                           quantity=D(0), average=D(0), peak_quantity=D(0), gross=D(0),
                           fees=D(0), funding_cost=D(0), baseline_funding_cost=D(0),
                           initial_direction=direction, adds=0, readds=0, reductions=0,
                           exit_qty=D(0), exit_notional=D(0), exit_fee=D(0),
                           last_reduce_qty=D(0), last_reduce_notional=D(0))
        ep = current
        if D(row['previous_quantity']) != ep['quantity'] or row['side'] != ep['side']:
            raise ValueError('fill position mismatch')
        ep['fees'] += fee
        if row['order_kind'] == 'increase':
            if ep['quantity']:
                ep['adds'] += 1
            if ep['last_reduce_qty']:
                reference = ep['last_reduce_notional']/ep['last_reduce_qty']
                readds.append(dict(episode=ep['index'], time_ms=row['time_ms'],
                                   side=ep['side'], quantity=qty, price=price,
                                   previous_reduction_vwap=reference,
                                   adverse_reentry_distance=ep['side']*(price-reference),
                                   order_id=row['order_id']))
                ep['readds'] += 1
            ep['last_reduce_qty'] = ep['last_reduce_notional'] = D(0)
            ep['average'] = (ep['quantity']*ep['average']+qty*price)/(ep['quantity']+qty)
            ep['quantity'] += qty
            ep['peak_quantity'] = max(ep['peak_quantity'], ep['quantity'])
        else:
            if qty > ep['quantity']:
                raise ValueError('reduction exceeds position')
            ep['gross'] += ep['side']*qty*(price-ep['average'])
            ep['quantity'] -= qty
            if row['order_kind'] == 'reduce':
                ep['reductions'] += 1
                ep['last_reduce_qty'] += qty
                ep['last_reduce_notional'] += qty*price
            elif row['order_kind'] == 'exit':
                ep['exit_qty'] += qty
                ep['exit_notional'] += qty*price
                ep['exit_fee'] += fee
            else:
                raise ValueError('unknown fill kind')
        if ep['quantity'] != D(row['remaining_quantity']):
            raise ValueError('remaining quantity mismatch')
        if not ep['quantity']:
            ep['end_ms'] = row['time_ms']
            ep['closed'] = True
            ep['end_direction'] = direction
            if not ep['exit_qty']:
                raise ValueError('expected trend exit for this frozen experiment')
            finish(ep, ep['exit_notional']/ep['exit_qty'])
            episodes.append(ep)
            current = None
    if current is not None:
        current['end_ms'] = end_ms
        current['closed'] = False
        current['end_direction'] = direction
        finish(current, D(final_mark))
        episodes.append(current)
    return dict(episodes=episodes, reentries=readds,
                total_net=sum((e['net'] for e in episodes), D(0)),
                total_gross_including_open=sum((e['price_pnl'] for e in episodes), D(0)),
                total_fees=sum((e['fees'] for e in episodes), D(0)),
                total_funding_cost=sum((e['funding_cost'] for e in episodes), D(0)),
                holding_baseline_net=sum((e['baseline_net'] for e in episodes), D(0)),
                same_endpoint_difference=sum((e['net']-e['baseline_net'] for e in episodes), D(0)),
                worse_price_reentries=sum(r['adverse_reentry_distance'] > 0 for r in readds),
                better_price_reentries=sum(r['adverse_reentry_distance'] < 0 for r in readds),
                equal_price_reentries=sum(r['adverse_reentry_distance'] == 0 for r in readds))


def finish(ep, mark):
    ep['terminal_price'] = mark
    ep['unrealized'] = ep['side']*ep['quantity']*(mark-ep['average'])
    ep['price_pnl'] = ep['gross']+ep['unrealized']
    ep['net'] = ep['price_pnl']-ep['fees']-ep['funding_cost']
    ep['baseline_gross'] = ep['side']*ep['initial_quantity']*(mark-ep['initial_price'])
    exit_fee = ep['exit_fee']/ep['exit_qty']*ep['initial_quantity'] if ep['closed'] else D(0)
    ep['baseline_fees'] = ep['initial_fee']+exit_fee
    ep['baseline_net'] = ep['baseline_gross']-ep['baseline_fees']-ep['baseline_funding_cost']
    ep['same_endpoint_difference'] = ep['net']-ep['baseline_net']
    ep['hours'] = D(ep['end_ms']-ep['start_ms'])/3600000
    for key in ('last_reduce_qty', 'last_reduce_notional'):
        del ep[key]


def utc(ms):
    return datetime.fromtimestamp(ms/1000, timezone.utc).strftime('%m-%d %H:%M')


def run(source, archives, output):
    summary_raw = (source/'summary.json').read_bytes()
    events_raw = (source/'events.jsonl').read_bytes()
    summary = json.loads(summary_raw)
    # Final historical close, not inferred from model PnL.
    name = sorted(summary['archive_sha256'])[-1]
    raw = (archives/name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != summary['archive_sha256'][name]:
        raise ValueError('final archive checksum mismatch')
    with ZipFile(io.BytesIO(raw)) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            last = list(csv.DictReader(io.TextIOWrapper(stream)))[-1]
    if int(last['open_time'])+60000 != summary['last_close_ms']:
        raise ValueError('final endpoint mismatch')
    rows = [json.loads(line) for line in events_raw.splitlines()]
    report = analyze(rows, last['close'], summary['last_close_ms'])
    if abs(report['total_net']-D(summary['total_pnl'])) > D('1e-18'):
        raise ValueError('episode sum disagrees with original replay')
    report['source_summary_sha256'] = hashlib.sha256(summary_raw).hexdigest()
    report['source_events_sha256'] = hashlib.sha256(events_raw).hexdigest()
    report['review_script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report['baseline_limitations'] = 'Initial quantity held to actual exit VWAP or final mark; different exposure, no policy resimulation.'
    output.mkdir(parents=True, exist_ok=False)
    (output/'review.json').write_text(json.dumps(jsonable(report), ensure_ascii=False, indent=2)+'\n')
    lines = ['# 순환매 구간별 손익 점검', '', '시간은 UTC. 금액은 USDC. 마지막 구간은 미종료다.', '',
             '| 구간 | 방향 | 시작 → 끝 | 총 가격손익 | 수수료 | 펀딩 비용 | 순손익 | 최초수량 보유 비교 | 차이 |',
             '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for ep in report['episodes']:
        lines.append(f"| {ep['index']} | {'롱' if ep['side']==1 else '숏'} | {utc(ep['start_ms'])} → {utc(ep['end_ms'])} | {ep['price_pnl']:.2f} | {ep['fees']:.2f} | {ep['funding_cost']:.2f} | {ep['net']:.2f} | {ep['baseline_net']:.2f} | {ep['same_endpoint_difference']:.2f} |")
    lines += ['', '최초수량 보유 비교는 같은 종료 가격의 회계 비교다. 노출·위험이 다르며 대안 전략 백테스트가 아니다.', '',
              f"전체 순손익 {report['total_net']:.2f}; 최초수량 보유 비교 {report['holding_baseline_net']:.2f}; 차이 {report['same_endpoint_difference']:.2f}.",
              f"축소 후 재추가 {len(report['reentries'])}회 중 이전 축소 VWAP보다 불리한 가격 {report['worse_price_reentries']}회, 유리한 가격 {report['better_price_reentries']}회.",
              '불리한 재진입 가격만으로 잘못된 거래라고 판정하지 않는다. 돌파 지속 근거와 비용을 따로 검토해야 한다.']
    (output/'cases.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(jsonable({k:v for k,v in report.items() if k not in ('episodes', 'reentries')}), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.archives, args.output)
