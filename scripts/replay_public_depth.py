#!/usr/bin/env python3
"""Reconstruct the saved public capture; independent Fraction replay and fault drills.

No network, orders, fill simulation, parameter search or new historical sample.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.data.local_order_book import LocalOrderBook, BookUnavailable


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(book):
    checkpoint = book.checkpoint()
    return hashlib.sha256(json.dumps(dict(bids=checkpoint['bids'], asks=checkpoint['asks']), sort_keys=True).encode()).hexdigest()


def replay(snapshot, rows, boundary_ns, *, independent=False, tickers=None):
    book = LocalOrderBook()
    book.begin_session('saved-public-connection-1', started_ns=rows[0]['received_monotonic_ns'])
    installed, counts, quotes, failures = False, Counter(), [], []
    # Independent numeric representation and source-level update loop. No
    # production parser/update helpers used to calculate expected book contents.
    reference_bids = {Fraction(p):Fraction(q) for p,q in snapshot['bids']}
    reference_asks = {Fraction(p):Fraction(q) for p,q in snapshot['asks']}
    reference_last = None
    compared, matched_updates, matched_observations, ticker_mismatches = 0, 0, 0, []
    for index, wrapper in enumerate(rows):
        received = wrapper['received_monotonic_ns']
        event = wrapper['message']['data']
        if independent and event['u'] >= snapshot['lastUpdateId']:
            if reference_last is None:
                assert event['U'] <= snapshot['lastUpdateId'] <= event['u'], 'reference bridge missing'
            else:
                assert event['pu'] == reference_last and event['u'] > reference_last, 'reference chain gap'
            for key, side in (('b', reference_bids), ('a', reference_asks)):
                for price, quantity in event[key]:
                    price, quantity = Fraction(price), Fraction(quantity)
                    if quantity == 0:
                        if price in side:
                            del side[price]
                    else:
                        side[price] = quantity
            reference_last = event['u']
        if not installed and received >= boundary_ns:
            book.install_snapshot(snapshot, session=book.session, available_ns=boundary_ns)
            installed = True
        outcome = book.ingest(event, session=book.session, received_ns=received)
        counts[outcome] += 1
        if book.state == 'INVALID' and not failures:
            failures.append(dict(index=index, u=event.get('u'), reason=book.reason))
        if outcome != 'APPLIED':
            if book.state == 'INVALID':
                try:
                    book.quote(now_ns=received)
                except BookUnavailable:
                    pass
                else:
                    raise AssertionError('invalid book remained publishable')
            continue
        quote = book.quote(now_ns=received)
        quotes.append(quote | dict(received_utc=wrapper['received_utc'], book_sha256=digest(book)))
        if independent:
            assert {Fraction(p):Fraction(q) for p,q in book.bids.items()} == reference_bids, ('bids', event['u'])
            assert {Fraction(p):Fraction(q) for p,q in book.asks.items()} == reference_asks, ('asks', event['u'])
            compared += 1
        matching = (tickers or {}).get(event['u'], [])
        if matching:
            matched_updates += 1
        for ticker in matching:
            matched_observations += 1
            expected = [Fraction(ticker[k]) for k in ('b','B','a','A')]
            actual = [Fraction(quote[k]) for k in ('bid','bid_quantity','ask','ask_quantity')]
            if actual != expected:
                ticker_mismatches.append(dict(u=event['u'], actual=list(map(str, actual)), ticker=list(map(str, expected))))
    if not installed:
        raise ValueError('no event after snapshot availability boundary')
    return dict(final_state=book.state, final_reason=book.reason, outcomes=dict(counts), failures=failures,
                published_quotes=len(quotes), independent_full_book_comparisons=compared,
                ticker_matched_updates=matched_updates, ticker_matched_observations=matched_observations,
                ticker_mismatches=ticker_mismatches, final_book_sha256=digest(book),
                final_quote=quotes[-1] if quotes and book.state=='LIVE' else None), quotes, book.checkpoint()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'reports/validation/execution_data_fitness_20260917')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = json.loads((args.input/'data_fitness.json').read_text())
    for name, expected in source['artifact_hashes'].items():
        if sha(args.input/name) != expected:
            raise ValueError('saved source hash mismatch: '+name)
    raw = json.loads((args.input/'depth_snapshot.json').read_text())
    snapshot = raw['response']
    events = [json.loads(line) for line in (args.input/'public_events.jsonl').read_text().splitlines()]
    times = [r['received_monotonic_ns'] for r in events]
    if any(type(t) is not int or t < 0 for t in times) or times != sorted(times):
        raise ValueError('capture receive clock regressed')
    rows = [r for r in events if r['channel']=='public' and r['message']['data']['e']=='depthUpdate']
    if len(rows) < 80:
        raise ValueError('bounded source needs at least 80 depth events for fixed fault scenarios')
    # The old capture has no REST monotonic timestamp. Use the first recorded
    # depth receive after REST UTC receipt as a conservative publication boundary.
    # Do not turn this compatibility rule into a latency estimate.
    rest_time = datetime.fromisoformat(raw['received_utc'])
    boundary = next(r['received_monotonic_ns'] for r in rows if datetime.fromisoformat(r['received_utc']) >= rest_time)
    tickers = defaultdict(list)
    for record in events:
        message = record['message']['data']
        if message['e']=='bookTicker' and message['s']=='BTCUSDC':
            tickers[message['u']].append(message)
    base, quotes, final = replay(snapshot, rows, boundary, independent=True, tickers=tickers)
    (args.output/'quotes.jsonl').write_text(''.join(json.dumps(q,sort_keys=True)+'\n' for q in quotes))
    (args.output/'final_book.json').write_text(json.dumps(final,indent=2)+'\n')
    cases = {}
    missing = deepcopy(rows)
    del missing[50]
    cases['missing_depth_event_50'] = (missing, 'UPDATE_CHAIN_GAP')
    duplicate = deepcopy(rows)
    duplicate.insert(51, deepcopy(duplicate[50]))
    cases['duplicate_depth_event_50'] = (duplicate, None)
    swapped = deepcopy(rows)
    swapped[50]['message'], swapped[51]['message'] = swapped[51]['message'], swapped[50]['message']
    cases['reordered_payloads_50_51'] = (swapped, 'UPDATE_CHAIN_GAP')
    malformed = deepcopy(rows)
    malformed[50]['message']['data']['b'].append(['100','NaN'])
    cases['malformed_quantity_event_50'] = (malformed, 'MALFORMED_DEPTH')
    fault_results = {}
    for name, (altered, expected) in cases.items():
        result, _, _ = replay(snapshot, altered, boundary)
        if expected:
            assert result['final_state']=='INVALID' and result['final_reason']==expected, name
        else:
            assert result['final_state']=='LIVE' and result['outcomes']['DUPLICATE']==1
            assert result['final_book_sha256']==base['final_book_sha256']
        fault_results[name] = result
    assert base['final_state']=='LIVE' and not base['ticker_mismatches']
    report = dict(status='PASS_SCOPED_L2_REPLAY', source_directory=str(args.input),
                  source_hashes={name:sha(args.input/name) for name in ('data_fitness.json','depth_snapshot.json','public_events.jsonl')},
                  depth_input_events=len(rows), snapshot_bid_levels=len(snapshot['bids']), snapshot_ask_levels=len(snapshot['asks']),
                  publication_boundary=dict(monotonic_ns=boundary, method='first_depth_receive_after_REST_UTC_receipt',
                                            native_REST_monotonic_timestamp_present=False, latency_calibration_eligible=False),
                  base=base, fault_drills=fault_results, actual_orders=0, private_requests=0, network_requests=0,
                  limitations=['Same short archived capture; no new independent period or strategy test.',
                               'Reference implementation reuses source events; exact-u bookTicker checks cover only their overlap.',
                               'Snapshot-limited L2 completeness, not all market liquidity or maker queue/fill calibration.',
                               'Session/reconnect state machine tested offline; no live reconnect/resnapshot collection integration.'])
    (args.output/'replay_report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'], depth_input_events=len(rows), base=base,
                         fault_drills={name:dict(state=r['final_state'],reason=r['final_reason']) for name,r in fault_results.items()}),indent=2))


if __name__ == '__main__':
    main()
