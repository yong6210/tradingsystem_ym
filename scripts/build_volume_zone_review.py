"""Point-in-time volume-zone review, not an automated trading strategy.

Uses executed aggTrade volume, independently checks the last day's histogram,
freezes the selected zones, then observes the following six hours separately.
"""
from pathlib import Path
import sys
import json
import hashlib
import zipfile
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.research.diagnostics.multiscale_profile import zones_from_hist


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as fp:
        for block in iter(lambda: fp.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def build(output):
    data = ROOT/'data/historical/btcusdc_aggprofiles_20260919'
    npz = data/'histogram_50usdc_15min.npz'
    registration = json.loads((ROOT/'reports/validation/e055_multiscale_profile_20260919/registration.json').read_text())
    assert sha(npz) == registration['source_hashes'][str(npz.relative_to(ROOT))]
    packed = np.load(npz)
    hist, offset = packed['hist'], int(packed['offset'])
    start = int(pd.Timestamp('2026-06-01T00:00Z').timestamp()*1000)
    cutoff = int(pd.Timestamp('2026-08-15T00:00Z').timestamp()*1000)
    decision = cutoff + 60000
    end = (cutoff-start)//900000
    profiles = {label: hist[end-slots:end].sum(axis=0) for label, slots in [('24h',96),('7d',672),('60d',5760)]}
    assert end >= 5760 and all(np.isfinite(v).all() for v in profiles.values())
    # Independent recent-volume check from actual price/quantity trades.
    archive = data/'BTCUSDC-aggTrades-2026-08.zip'
    manifest = json.loads((data/'manifest.json').read_text())
    expected = next(r['sha256'] for r in manifest['archives'] if r['file']==archive.name)
    assert sha(archive) == expected
    recent, replay_parts = [], []
    raw_hist = np.zeros(hist.shape[1])
    previous_id, previous_time = None, None
    with zipfile.ZipFile(archive) as z, z.open(z.namelist()[0]) as fp:
        for chunk in pd.read_csv(fp, usecols=['agg_trade_id','price','quantity','transact_time'], chunksize=400000):
            ids = chunk.agg_trade_id.to_numpy('int64')
            times = chunk.transact_time.to_numpy('int64')
            assert (np.diff(ids)==1).all() and (np.diff(times)>=0).all()
            if previous_id is not None:
                assert ids[0]==previous_id+1 and times[0]>=previous_time
            previous_id, previous_time = int(ids[-1]), int(times[-1])
            window = chunk[(chunk.transact_time>=cutoff-86400000)&(chunk.transact_time<cutoff)]
            if len(window):
                np.add.at(raw_hist, np.floor(window.price.to_numpy()/50).astype(int)-offset, window.quantity.to_numpy())
                recent.append(window)
            future = chunk[(chunk.transact_time>=cutoff)&(chunk.transact_time<cutoff+6*3600000)]
            if len(future):
                replay_parts.append(future)
            if times[-1]>=cutoff+6*3600000:
                break
    assert np.allclose(raw_hist, profiles['24h'], rtol=1e-10, atol=1e-7)
    def candles(parts):
        frame = pd.concat(parts).set_index(pd.to_datetime(pd.concat(parts).transact_time, unit='ms', utc=True))
        return frame.price.resample('1min').ohlc()
    candles_before = candles(recent)
    assert len(candles_before)==1440 and not candles_before.isna().any().any()
    reference = float(candles_before.close.iloc[-1])
    structural = dict(prior_24h_high=float(candles_before.high.max()),
                      prior_24h_low=float(candles_before.low.min()),
                      meaning='Price extremes only, not volume nodes or confirmed support/resistance')
    # Candidate extraction is explicitly a trial display method.
    candidates = [vars(zone) for label, values in profiles.items() for zone in zones_from_hist(values, offset, label)]
    groups = []
    for zone in sorted(candidates, key=lambda z: z['low']):
        if groups and zone['low']<=groups[-1]['high']:
            groups[-1]['high'] = max(groups[-1]['high'], zone['high'])
            groups[-1]['members'].append(zone)
        else:
            groups.append(dict(low=zone['low'], high=zone['high'], members=[zone]))
    for i, group in enumerate(groups,1):
        group['id'] = f'Z{i:02}'
        group['distance'] = max(group['low']-reference, reference-group['high'], 0)
        group['position'] = 'below' if group['high']<reference else 'above' if group['low']>reference else 'inside'
        lo, hi = int(group['low']/50)-offset, int(group['high']/50)-offset
        group['shares'] = {label: float(v[lo:hi].sum()/v.sum()) for label,v in profiles.items()}
        group['selected'] = False
    # Nearby three zones on each side are review priorities, never orders.
    for side in ('below','above','inside'):
        for group in sorted((g for g in groups if g['position']==side), key=lambda g:g['distance'])[:3]:
            group['selected'] = True
    selected = [g for g in groups if g['selected']]
    snapshot = dict(decision_utc='2026-08-15T00:01:00Z', data_cutoff_exclusive_utc='2026-08-15T00:00:00Z',
                    reference_price=reference, structural_references=structural, symbol='BTCUSDC', source='executed aggTrade quantity, BTC',
                    method='50-USDC bins; prior research top-five peaks per horizon; overlapping ranges merged',
                    method_status='review_candidate_not_approved_trading_rule', zones=groups,
                    overlap_warning='Nested windows are correlated; shares are NOT added or counted as independent votes.',
                    source_sha256={str(npz.relative_to(ROOT)):sha(npz),str(archive.relative_to(ROOT)):expected},
                    script_sha256=sha(Path(__file__)),
                    validation=dict(raw_24h_histogram_matches_cache=True, complete_1440_minutes=True,
                                    no_post_cutoff_volume_in_selection=True, orders_generated=0))
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.dumps(snapshot, ensure_ascii=False, indent=2)
    (output/'frozen_zones.json').write_text(frozen+'\n')
    candles_before.to_csv(output/'prior_24h_ohlc.csv', index_label='minute_open_utc')
    pd.DataFrame({'price_bin_low':(np.arange(hist.shape[1])+offset)*50, **profiles}).to_csv(output/'profile_bins.csv', index=False)
    # Scientific review figure: price history and separately scaled volume profiles.
    fig, axes = plt.subplots(1,4, figsize=(16,7), gridspec_kw={'width_ratios':[4,1.2,1.2,1.2]}, sharey=True)
    price_15 = candles_before.resample('15min').agg({'open':'first','high':'max','low':'min','close':'last'})
    axes[0].plot(price_15.index, price_15.close, color='#253858', linewidth=1.4, label='15m close')
    axes[0].fill_between(price_15.index, price_15.low, price_15.high, color='#253858', alpha=.12, label='15m high/low')
    axes[0].set_title('Prior 24h price | future hidden', loc='left')
    axes[0].set_ylabel('BTC price (USDC)')
    import matplotlib.dates as mdates
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter('%m-%d\n%H:%M', tz=timezone.utc))
    axes[0].legend(loc='upper left', fontsize=9)
    for key, label in [('prior_24h_high','24h high (structure)'),('prior_24h_low','24h low (structure)')]:
        axes[0].axhline(structural[key], color='#6b7280', linestyle=':', linewidth=1)
        axes[0].text(price_15.index[0], structural[key], label, fontsize=8, va='bottom', color='#475569')
    centers = (np.arange(hist.shape[1])+offset+.5)*50
    for ax,(label,values) in zip(axes[1:],profiles.items()):
        ax.barh(centers, values, height=45, color='#829ab1')
        ax.set_title(label+' executed volume')
        ax.set_xlabel('BTC (own scale)')
        ax.tick_params(axis='x', labelrotation=35)
    for ax in axes:
        for group in selected:
            ax.axhspan(group['low'], group['high'], color='#d69e2e', alpha=.17)
        ax.axhline(reference, color='#222222', linestyle='--', linewidth=1)
        ax.grid(axis='y', alpha=.15)
    for group in selected:
        axes[0].text(price_15.index[-1], (group['low']+group['high'])/2, group['id'], fontsize=9,
                     ha='right', va='center', bbox=dict(facecolor='white', alpha=.9, edgecolor='none'))
    bounds = [reference-1000, reference+1000]+[g[k] for g in selected for k in ('low','high')]
    axes[0].set_ylim(min(bounds)-100, max(bounds)+100)
    fig.suptitle('Volume-zone review | 2026-08-15 00:01 UTC', fontsize=17, x=.06, ha='left')
    fig.text(.06,.025,'Only trades before 00:00 UTC. Highlighted ranges are candidates, not support/resistance confirmations.\n24h / 7d / 60d windows overlap; profile volumes must not be added. One exchange and one contract only.',fontsize=10)
    fig.subplots_adjust(left=.07,right=.98,top=.88,bottom=.17,wspace=.10)
    fig.savefig(output/'volume_zones.png',dpi=150)
    plt.close(fig)
    # Step 3: observe frozen levels with no retrospective zone replacement.
    future = candles(replay_parts)
    assert len(future)==360 and not future.isna().any().any()
    observations = []
    for time, bar in future.resample('15min').agg({'open':'first','high':'max','low':'min','close':'last'}).iterrows():
        close_time = time+pd.Timedelta(minutes=15)
        if close_time.timestamp()*1000 < decision:
            continue
        observations.append(dict(available_utc=close_time.isoformat(),close=float(bar.close),
            zones=[dict(id=g['id'], touched=bool(bar.low<=g['high'] and bar.high>=g['low']),
                        close_position='below' if bar.close<g['low'] else 'above' if bar.close>g['high'] else 'inside') for g in selected],
            decision='unassessed; market direction and reaction interpretation not yet calibrated'))
    (output/'forward_observations.json').write_text(json.dumps(dict(frozen_snapshot_sha256=hashlib.sha256((frozen+'\n').encode()).hexdigest(), observations=observations), indent=2)+'\n')
    lines = ['# 매물대 검토 — 1단계 근거표','',f'기준 시점: 2026-08-15 00:01 UTC. 직전 가격 {reference:,.1f} USDC. 미래 차트 제외.','',
             '| 구간 | 가격 범위 | 현재 위치와 관계 | 24시간 비중 | 7일 비중 | 60일 비중 | 검토 우선순위 |',
             '| --- | --- | --- | ---: | ---: | ---: | --- |']
    for g in groups:
        lines.append(f"| {g['id']} | {g['low']:,.0f}–{g['high']:,.0f} | {g['position']} | {g['shares']['24h']:.1%} | {g['shares']['7d']:.1%} | {g['shares']['60d']:.1%} | {'근거리 검토' if g['selected'] else '먼 구간: 즉시 대응 검토에서 제외'} |")
    lines += ['', f"별도 구조 참고: 직전 24시간 고점 {structural['prior_24h_high']:,.1f}, 저점 {structural['prior_24h_low']:,.1f}. 거래량 상위 구간에서 제외됐어도 구조 관찰에서 버리지 않는다.",
              '가격 아래에 있다고 지지가 확정된 것은 아니다. 실제 반응·이탈·재진입을 추가로 판정해야 한다.',
              '구간별 비중의 분모는 각 기간의 전체 체결 BTC 수량이다. 중첩 기간 비중을 합산하지 않는다.',
              '선정 방법은 기존 후보 추출기를 사용한 검토 초안이다. 중요도를 사용자 방식대로 확정했다는 뜻이 아니다.',
              '직전 24시간은 원본 체결로 독립 재집계했다. 7일·60일은 기존 해시 검증 캐시를 사용했으며 이번에 전량 재집계하지 않았다.']
    (output/'zones.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(reference=reference, groups=len(groups), selected=[g['id'] for g in selected], observations=len(observations), output=str(output))))


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
