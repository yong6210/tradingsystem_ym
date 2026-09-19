"""Checksummed historical signal inspection; no trades or PnL claims."""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.recovery.cycling_signals import SignalPolicy, CyclingSignals
from app.research.recovery.models import Bar, jsonable


def run(config_path, archive_dir, output):
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    if config['status'] != 'unapproved_research_candidate':
        raise ValueError('this inspector accepts only explicitly labelled trial rules')
    adapter = CyclingSignals(SignalPolicy(**config['policy']))
    archive_hashes, count, first, last = {}, 0, None, None
    trends, reactions = [], []
    counts = Counter()
    paths = sorted(archive_dir.glob('BTCUSDC-1m-*.zip'))
    if not paths:
        raise ValueError('no BTCUSDC minute archives found')
    for path in paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != path.with_name(path.name + '.CHECKSUM').read_text().split()[0]:
            raise ValueError('archive checksum mismatch: ' + str(path))
        archive_hashes[path.name] = digest
        with ZipFile(io.BytesIO(raw)) as archive:
            members = archive.namelist()
            if len(members) != 1:
                raise ValueError('one CSV per archive required')
            with archive.open(members[0]) as member:
                for row in csv.DictReader(io.TextIOWrapper(member)):
                    end = int(row['open_time']) + 60000
                    if last is not None and end != last + 60000:
                        raise ValueError('archive gap or duplicate minute')
                    bar = Bar(end, row['open'], row['high'], row['low'], row['close'], end)
                    event = adapter.observe(bar)
                    first = end if first is None else first
                    last, count = end, count + 1
                    trend = event['trend']
                    if trend is not None:
                        trends.append(trend)
                        counts['four_hour_' + str(trend['side'])] += 1
                        if trend['changed']:
                            counts['initial_direction' if trend['previous'] is None else 'direction_reversals'] += 1
                    for location in event['reactions']:
                        latest = location.history.events[-1]
                        if latest.evidence.recorded_ms > end or location.history.zone.available_ms > end:
                            raise AssertionError('future reaction evidence')
                        reactions.append(dict(at_ms=end, side=location.side, direction=adapter.trend.direction,
                                              zone_key=location.history.zone.key,
                                              formed_ms=location.history.zone.available_ms,
                                              event_id=location.reaction_event_id,
                                              price=bar.close, entry_low=location.entry_low,
                                              entry_high=location.entry_high))
                        counts['reaction_unknown_direction' if adapter.trend.direction is None else
                               'same_direction_reaction' if location.side == adapter.trend.direction else
                               'opposing_zone_reaction'] += 1
    # Inspect source availability independently of the direction classification.
    for row in trends:
        for pivot in (*row['highs'], *row['lows']):
            if pivot.available_ms > row['available_ms'] or pivot.center.end_ms >= pivot.available_ms:
                raise AssertionError('pivot used before right-hand confirmation')
    source_paths = ['app/research/recovery/cycling_signals.py',
                    'app/research/recovery/zone_observer.py',
                    'scripts/inspect_cycling_signals.py']
    summary = dict(status=config['status'], sample_status='previously_used_development_data',
                   symbol='BTCUSDC', minute_count=count, first_end_ms=first, last_end_ms=last,
                   four_hour_count=len(trends), zone_count=len(adapter.zones),
                   reaction_count=len(reactions), counts=counts, archive_sha256=archive_hashes,
                   config_sha256=hashlib.sha256(config_raw).hexdigest(),
                   source_sha256={p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in source_paths},
                   live_orders=0, simulated_trades=0,
                   limitations=['Historical receipt time assumed equal to candle close.',
                                'No profitability or order-fill assessment.',
                                'Mixed structure preserves bias; this can delay reversal.',
                                'Reactions are candidates, not approved entries or reductions.'])
    output.mkdir(parents=True, exist_ok=False)
    (output/'summary.json').write_text(json.dumps(jsonable(summary), ensure_ascii=False, indent=2)+'\n')
    (output/'config.json').write_bytes(config_raw)
    for name, records in (('four_hour_assessments', trends), ('zone_reactions', reactions)):
        with (output/(name+'.jsonl')).open('w') as stream:
            for record in records:
                stream.write(json.dumps(jsonable(record), ensure_ascii=False)+'\n')
    print(json.dumps(jsonable({k: v for k, v in summary.items() if not k.endswith('sha256')}), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--archives', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.config, args.archives, args.output)
