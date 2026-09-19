"""Development archive replay and independent pooled-ledger reconciliation."""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.cycling_market_replay import CyclingMarketReplay
from app.research.recovery.models import Bar, dec, jsonable


def audit(replay, mark):
    qty, average, side, gross, costs = dec(0), None, None, dec(0), dec(0)
    latest_direction = None
    adds = readds = initial = reductions = exits = 0
    reduced_since_add = False
    intents = {r['order_id']: r for r in replay.rows if r['kind'] in ('increase_intent', 'reduction_intent', 'exit_intent')}
    for row in replay.rows:
        if row['kind'] == 'direction':
            latest_direction = row['assessment']['side']
        if row['kind'] == 'funding':
            expected = side * qty * dec(row['mark']) * dec(row['rate'])
            assert expected == dec(row['signed_cost'])
            costs += expected
        if row['kind'] != 'fill':
            continue
        amount, price, fee = (dec(row[k]) for k in ('quantity', 'price', 'fee'))
        intent = intents[row['order_id']]
        assert row['time_ms'] >= intent['time_ms'] == row['created_ms']
        assert fee == amount * price * replay.costs.fee
        if row['order_kind'] == 'increase':
            assert row['side'] == latest_direction
            assert side is None or row['side'] == side
            if qty:
                adds += 1
                readds += int(reduced_since_add)
            else:
                initial += 1
            reduced_since_add = False
            average = ((average or dec(0))*qty + amount*price)/(qty+amount)
            qty += amount
            side = row['side']
        else:
            assert 0 < amount <= qty and row['side'] == side
            if row['order_kind'] == 'reduce':
                assert dec(intent['quantity']) >= dec(intent['basis'])/2
                reduced_since_add = True
                reductions += 1
            else:
                assert intent['reason'] == 'four_hour_candidate_direction_change'
                exits += 1
            gross += side * amount * (price-average)
            qty -= amount
            if not qty:
                average, side, reduced_since_add = None, None, False
        costs += fee
        assert qty == dec(row['remaining_quantity'])
        assert average == (None if row['average'] is None else dec(row['average']))
        assert abs(gross-dec(row['realized_gross'])) < dec('1e-18')
        assert costs == dec(row['net_costs'])
    total = gross-costs+(side*qty*(dec(mark)-average) if qty else 0)
    assert abs(total-replay.model.total_pnl(mark)) < dec('1e-18')
    return dict(status='PASS', initial_fill_events=initial, add_fill_events=adds,
                readd_after_reduction_fill_events=readds, reduction_fill_events=reductions,
                trend_exit_fill_events=exits, independently_reconciled_total_pnl=str(total))


def run(config_path, archive_dir, output):
    raw_config = config_path.read_bytes()
    replay = CyclingMarketReplay(json.loads(raw_config))
    funding_raw = (archive_dir/'funding.json').read_bytes()
    funding = sorted(json.loads(funding_raw), key=lambda r: int(r['fundingTime']))
    if len({int(f['fundingTime']) for f in funding}) != len(funding):
        raise ValueError('duplicate funding records')
    fi, count, previous, first, mark = 0, 0, None, None, None
    hashes = {}
    paths = sorted(archive_dir.glob('BTCUSDC-1m-*.zip'))
    if not paths:
        raise ValueError('no input archives')
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if path.with_name(path.name+'.CHECKSUM').read_text().split()[0] != digest:
            raise ValueError('archive checksum mismatch')
        hashes[path.name] = digest
        with ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.namelist()) != 1:
                raise ValueError('expected one CSV member')
            with archive.open(archive.namelist()[0]) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream)):
                    start = int(row['open_time'])
                    if previous is not None and start != previous + 60000:
                        raise ValueError('nonconsecutive archive minutes')
                    if first is None:
                        first = start
                    while fi < len(funding) and int(funding[fi]['fundingTime']) <= start:
                        if int(funding[fi]['fundingTime']) >= first:
                            replay.funding(funding[fi])
                        fi += 1
                    replay.fill_open(row['open'], start)
                    end = start + 60000
                    while fi < len(funding) and int(funding[fi]['fundingTime']) <= end:
                        replay.funding(funding[fi])
                        fi += 1
                    replay.close(Bar(end, row['open'], row['high'], row['low'], row['close'], end), row['volume'])
                    previous, mark, count = start, row['close'], count + 1
    result = replay.summary(mark)
    result.update(status='development_replay_not_strategy_validation', sample='previously_used_data',
                  minute_count=count, first_open_ms=first, last_close_ms=previous+60000,
                  audit=audit(replay, mark), archive_sha256=hashes,
                  funding_sha256=hashlib.sha256(funding_raw).hexdigest(),
                  config_sha256=hashlib.sha256(raw_config).hexdigest(),
                  limitations=['Next-open spread/slippage proxy, not historical orderbook fills.',
                               'Entry remainder cancelled after one open opportunity; no position time stop.',
                               'No liquidation model; reserve and stress limits are unapproved trial inputs.',
                               'End position is marked, not forcibly closed; exit fees on remaining position excluded.',
                               'Funding uses supplied event timestamps and marks; no future funding forecast.'])
    source = list((ROOT/'app/research/recovery').glob('cycling_*.py')) + [ROOT/'app/research/recovery/directional_cycling.py', Path(__file__)]
    result['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source}
    output.mkdir(parents=True, exist_ok=False)
    (output/'summary.json').write_text(json.dumps(jsonable(result), ensure_ascii=False, indent=2)+'\n')
    (output/'config.json').write_bytes(raw_config)
    (output/'checkpoint.json').write_text(json.dumps(replay.orders.checkpoint(), ensure_ascii=False, indent=2)+'\n')
    with (output/'events.jsonl').open('w') as stream:
        for event in replay.rows:
            stream.write(json.dumps(event, ensure_ascii=False)+'\n')
    print(json.dumps({k: v for k, v in result.items() if not k.endswith('sha256')}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.archives, args.output)
