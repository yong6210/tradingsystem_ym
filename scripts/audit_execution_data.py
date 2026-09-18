#!/usr/bin/env python3
"""Read-only execution-data audit and bounded public connectivity capture.

This is not a fill simulator or an account client. Public messages are retained
verbatim; local receive timestamps do not measure exchange-to-client latency.
"""
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import statistics
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = 'wss://fstream.binance.com/public/stream?streams=btcusdc@depth@100ms/btcusdc@bookTicker'
MARKET = 'wss://fstream.binance.com/market/stream?streams=btcusdc@aggTrade/btcusdc@markPrice@1s'
DEPTH = 'https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDC&limit=1000'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quote_profile(path):
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    # A pair of directional calculations is one observed book, not two trials.
    groups = defaultdict(list)
    invalid, missing = 0, Counter()
    required = ('timestamp', 'symbol', 'side', 'best_bid', 'best_ask', 'latency_ms', 'market_slippage_bps')
    for row in rows:
        for key in required:
            if row.get(key) is None:
                missing[key] += 1
        groups[(row.get('symbol'), row.get('timestamp'))].append(row)
        try:
            bid, ask = Decimal(str(row['best_bid'])), Decimal(str(row['best_ask']))
            valid = bid.is_finite() and ask.is_finite() and 0 < bid <= ask
        except (KeyError, ArithmeticError, ValueError):
            valid = False
        invalid += not valid
    times = sorted({datetime.fromisoformat(ts) for _, ts in groups if ts is not None})
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    per_day = Counter(t.date().isoformat() for t in times)
    conflicts = sum(len({(r.get('best_bid'), r.get('best_ask')) for r in group}) > 1 for group in groups.values())
    return dict(path=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), sha256=sha(path),
                rows=len(rows), distinct_decision_ids=len({r.get('decision_id') for r in rows}),
                exact_duplicate_rows=len(rows)-len({json.dumps(r, sort_keys=True) for r in rows}),
                unique_book_observations=len(groups), directional_pairs=sum({r.get('side') for r in g} == {'long', 'short'} for g in groups.values()),
                rows_per_observation=dict(Counter(len(g) for g in groups.values())),
                symbols=dict(Counter(r.get('symbol') for r in rows)), invalid_bid_ask_rows=invalid,
                missing_required_fields=dict(missing), conflicting_same_time_books=conflicts,
                first_utc=times[0].isoformat() if times else None, last_utc=times[-1].isoformat() if times else None,
                observation_days=dict(per_day), median_gap_seconds=statistics.median(gaps) if gaps else None,
                maximum_gap_seconds=max(gaps) if gaps else None,
                missing_for_fill_calibration=['raw_depth_levels', 'depth_update_sequence', 'public_trade_events',
                                             'own_order_acceptance_and_fills', 'queue_priority', 'monotonic_receive_time'],
                eligible_for_maker_fill_calibration=False)


def sequence_profile(snapshot, events):
    """Check snapshot bridge and pu chain; does not claim a reconstructed book."""
    if not snapshot or type(snapshot.get('lastUpdateId')) is not int:
        return dict(status='NO_SNAPSHOT', bridged=False, continuous=False)
    last = snapshot['lastUpdateId']
    depth = [r['message']['data'] for r in events if r.get('message', {}).get('data', {}).get('e') == 'depthUpdate']
    previous, bridged, gaps, used, discarded, malformed = None, False, [], 0, 0, 0
    for event in depth:
        if (event.get('s') != 'BTCUSDC' or any(type(event.get(k)) is not int for k in ('U', 'u', 'pu'))
                or event['U'] > event['u']):
            malformed += 1
            continue
        if not bridged:
            if event['u'] < last:
                discarded += 1
                continue
            if not event['U'] <= last <= event['u']:
                return dict(status='SNAPSHOT_BRIDGE_MISSING', bridged=False, continuous=False,
                            snapshot_last=last, first_U=event['U'], first_u=event['u'], depth_events=len(depth))
            bridged, previous, used = True, event['u'], 1
        else:
            if event['pu'] != previous or event['u'] <= previous:
                gaps.append(dict(previous_u=previous, U=event['U'], u=event['u'], pu=event['pu']))
            previous = event['u']
            used += 1
    continuous = bridged and not gaps and not malformed
    return dict(status='CHAIN_OBSERVED' if continuous else 'INSUFFICIENT_OR_DISCONTINUOUS',
                bridged=bridged, continuous=continuous, depth_events=len(depth), used_events=used,
                discarded_before_snapshot=discarded, malformed_events=malformed, gaps=gaps,
                snapshot_last=last, last_u=previous, full_book_reconstruction_verified=False)


async def capture(output, seconds):
    from websockets.asyncio.client import connect
    events, errors, opened = [], [], {}
    stop = asyncio.Event()
    ready = {key: asyncio.Event() for key in ('public', 'market')}
    raw_path = output / 'public_events.jsonl'
    with raw_path.open('x') as raw:
        async def listen(key, url):
            try:
                async with connect(url, open_timeout=8, close_timeout=2, max_queue=4096) as ws:
                    opened[key] = datetime.now(timezone.utc).isoformat()
                    ready[key].set()
                    while not stop.is_set():
                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=.5)
                        except asyncio.TimeoutError:
                            continue
                        record = dict(channel=key, received_utc=datetime.now(timezone.utc).isoformat(),
                                      received_monotonic_ns=time.monotonic_ns(), message=json.loads(message))
                        raw.write(json.dumps(record, separators=(',', ':')) + '\n')
                        raw.flush()
                        events.append(record)
            except Exception as exc:
                errors.append(dict(channel=key, error=type(exc).__name__, detail=str(exc)))
                ready[key].set()

        jobs = [asyncio.create_task(listen('public', PUBLIC)), asyncio.create_task(listen('market', MARKET))]
        await asyncio.gather(*(event.wait() for event in ready.values()))
        snapshot = None
        started = datetime.now(timezone.utc).isoformat()
        rest_start = time.monotonic_ns()
        try:
            def fetch():
                with urlopen(DEPTH, timeout=8) as response:
                    return json.loads(response.read())
            snapshot = await asyncio.to_thread(fetch)
            rest_record = dict(url=DEPTH, request_started_utc=started,
                               received_utc=datetime.now(timezone.utc).isoformat(),
                               duration_ms=(time.monotonic_ns()-rest_start)/1e6, response=snapshot)
            (output / 'depth_snapshot.json').write_text(json.dumps(rest_record, indent=2)+'\n')
        except Exception as exc:
            errors.append(dict(channel='REST_depth', error=type(exc).__name__, detail=str(exc)))
        await asyncio.sleep(seconds)
        stop.set()
        await asyncio.gather(*jobs)
    return dict(urls=dict(public=PUBLIC, market=MARKET, snapshot=DEPTH), opened_utc=opened,
                post_snapshot_observation_seconds=seconds, errors=errors,
                event_counts=dict(Counter(r['message'].get('data', {}).get('e', 'unknown') for r in events)),
                depth_sequence=sequence_profile(snapshot, events),
                actual_orders=0, private_requests=0, eligible_for_maker_fill_calibration=False,
                limitation='Bounded connection/sequence probe only; no queue, own fills, regime coverage or latency calibration.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--capture-seconds', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.capture_seconds <= 30:
        parser.error('capture-seconds must be 0..30')
    args.output.mkdir(parents=True, exist_ok=False)
    manifest_path = ROOT / 'data/historical/btcusdc_public_20260917/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    profiles = [quote_profile(ROOT / 'data/shadow' / name) for name in
                ('market_state_rotation_v6_quote_shadow_BTCUSDC.jsonl', 'market_state_rotation_v6_quote_shadow.jsonl')]
    result = dict(audited_utc=datetime.now(timezone.utc).isoformat(), legacy_quotes=profiles,
                  historical_bundle=dict(path=str(manifest_path.relative_to(ROOT)), sha256=sha(manifest_path),
                                         archives=len(manifest['archives']), funding_sources=len(manifest['funding_sources']),
                                         kinds=dict(Counter(a['kind'] for a in manifest['archives']))),
                  producer=dict(path='scripts/run_market_state_rotation_v6_quote_shadow_audit.py',
                                sha256=sha(ROOT / 'scripts/run_market_state_rotation_v6_quote_shadow_audit.py')))
    if args.capture_seconds:
        result['public_probe'] = asyncio.run(capture(args.output, args.capture_seconds))
    result['artifact_hashes'] = {p.name: sha(p) for p in args.output.iterdir() if p.is_file()}
    (args.output / 'data_fitness.json').write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
