"""Audit the top-five cap without changing the frozen zone selection."""
from pathlib import Path
from datetime import datetime,timezone
import csv,json,hashlib,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.diagnostics.multiscale_profile import zones_from_hist


def peaks_without_cap(values, offset):
    values=np.asarray(values,dtype=float)
    if values.ndim!=1 or not len(values) or not np.isfinite(values).all() or (values<0).any():
        raise ValueError('finite nonnegative one-dimensional volume required')
    if values.sum()==0:return []
    if len(values)<3:raise ValueError('at least three bins required')
    smooth=np.convolve(values,[.25,.5,.25],mode='same');chosen=[];result=[]
    for k in np.argsort(-smooth,kind='stable'):
        k=int(k)
        if smooth[k]<=0 or (k and smooth[k]<smooth[k-1]) or (k+1<len(smooth) and smooth[k]<smooth[k+1]):continue
        if any(abs(k-j)<=3 for j in chosen):continue
        chosen.append(k);lo=max(0,k-1);hi=min(len(values),k+2)
        result.append(dict(rank=len(chosen),low=(lo+offset)*50,high=(hi+offset)*50,
            poc=(k+offset+.5)*50,share=float(values[lo:hi].sum()/values.sum()),
            low_bin=lo,high_bin_exclusive=hi,excluded_by_top_five_cap=len(chosen)>5))
    return result


def stamp(t):return int(datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()*1000)
def utc(t):return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()


def run():
    source=ROOT/'reports/validation/volume_zone_review_v02_20260919/frozen_zones.json'
    archive=ROOT/'data/historical/btcusdc_aggprofiles_20260919/histogram_50usdc_15min.npz'
    prior=ROOT/'reports/validation/volume_zone_review_v02_20260919/prior_24h_ohlc.csv'
    frozen=json.loads(source.read_text())
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==frozen['source_sha256'][str(archive.relative_to(ROOT))]
    start=stamp('2026-06-01T00:00:00Z');cutoff=stamp(frozen['data_cutoff_exclusive_utc']);end=(cutoff-start)//900000
    with np.load(archive) as cache:hist=cache['hist'][:end].copy();offset=int(cache['offset'])
    with prior.open() as fp:bars=list(csv.DictReader(fp))
    assert len(bars)==1440
    profiles={label:hist[-length:].sum(axis=0) for label,length in [('24h',96),('7d',672),('60d',5760)]}
    all_candidates=[]
    for label,v in profiles.items():
        candidates=peaks_without_cap(v,offset)
        old=zones_from_hist(v,offset,label)
        assert [(p['low'],p['high'],p['poc'],p['share']) for p in candidates[:5]]==[(p.low,p.high,p.poc,p.share) for p in old]
        for c in candidates:
            lo,hi=c['low_bin'],c['high_bin_exclusive']
            volume_by_slot=hist[:,lo:hi].sum(axis=1);active=np.flatnonzero(volume_by_slot>0)
            c.update(horizon=label,shares={h:float(p[lo:hi].sum()/p.sum()) for h,p in profiles.items()},
                last_trade_slot_end_ms=int(start+(int(active[-1])+1)*900000) if len(active) else None,
                last_trade_time_precision='15-minute slot end, not exact last execution',
                prior24h_ohlc_overlap_minutes=sum(float(b['low'])<=c['high'] and float(b['high'])>=c['low'] for b in bars),
                overlaps_frozen_zone_ids=[z['id'] for z in frozen['zones'] if c['low']<=z['high'] and c['high']>=z['low']])
        all_candidates.extend(candidates)
    # Diagnose the area below the nearest existing lower zone; no hindsight selection.
    below=[c for c in all_candidates if c['high']<=62750 and c['excluded_by_top_five_cap']]
    nearest=sorted(below,key=lambda c:(-c['high'],c['horizon']))[:3]
    output=dict(decision_utc=frozen['decision_utc'],cutoff_exclusive_utc=frozen['data_cutoff_exclusive_utc'],
        method='same 50-USDC bins, smoothing and peak suppression; only top-five stopping cap removed for coverage audit',
        candidates=all_candidates,nearest_omitted_below_Z01=nearest,
        frozen_selection_unchanged=True,orders_generated=0,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,archive,prior)},
        code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/diagnostics/multiscale_profile.py')})
    lines=['# 거래량 상위 다섯 구간 선정의 누락 점검','',
        f"기준 {frozen['decision_utc']}, 가격 {frozen['reference_price']:,.1f}. 집계 종료 {frozen['data_cutoff_exclusive_utc']} 이전 체결량만 사용했다.",
        '50-USDC 분할·평활·인접 고점 억제는 그대로 두고 상위 다섯 개 제한만 제거했다. 원본 선정 구간과 과거 주문 판단은 변경하지 않았다.',
        '제한 없는 후보도 완전한 매물대 지도가 아니다. 분할 폭·평활·중첩 억제에 따른 누락은 이번 비교에서 해결하지 않았다.','',
        '| 집계 창 | 기존 추출 후보 | 제한 제거 후보 | 추가 후보 |','| --- | ---: | ---: | ---: |']
    for label in profiles:
        group=[c for c in all_candidates if c['horizon']==label]
        lines.append(f'| {label} | {min(5,len(group))} | {len(group)} | {max(0,len(group)-5)} |')
    lines+=['','## Z01 아래에서 가까운 누락 후보 세 개','',
        '| 범위 | 출처·순위 | 24h 비중 | 7d 비중 | 60d 비중 | 마지막 거래 포함 슬롯 종료 UTC | 직전 24h 봉 겹침 |',
        '| --- | --- | ---: | ---: | ---: | --- | ---: |']
    for c in nearest:
        lines.append(f"| {c['low']:,.0f}–{c['high']:,.0f} | {c['horizon']} #{c['rank']} | {c['shares']['24h']:.2%} | {c['shares']['7d']:.2%} | {c['shares']['60d']:.2%} | {utc(c['last_trade_slot_end_ms'])} | {c['prior24h_ohlc_overlap_minutes']} |")
    lines+=['','## 판단에 주는 차이','',
        '- 전체 거래량 순위에서 밀려난 구간도 가격 아래쪽의 검토 지도에는 필요할 수 있다. 가까운 구간을 찾기 전에 전체 상위 다섯 개로 자르면 후보 자체가 사라진다.',
        '- 오래된 거래량 집중이 발견됐다고 지금 지지가 확인된 것은 아니다. 최근 거래·재접근이 없다면 역사적 참고로 남긴다.',
        '- 직전 24시간 저점 62,450은 구조 가격이다. 거래량 봉우리로 뽑히지 않아도 구조 이력에서 삭제하지 않는다.',
        '- 거래량 비중은 중첩 창끼리 합산하지 않는다. 마지막 거래 시각은 15분 단위 근사이며 구조 확인·지지 성공 시각이 아니다.',
        '- 과거 선정표의 빈칸을 뒤늦게 채워 당시 진입·물타기를 정당화하지 않는다. 이번 결과는 당시 자료로 후보 추출의 누락을 점검한 사후 방법 감사다.']
    out=ROOT/'reports/validation/volume_zone_coverage_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'coverage.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    (out/'coverage.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(counts={k:sum(c['horizon']==k for c in all_candidates) for k in profiles},nearest=nearest),ensure_ascii=False))


if __name__=='__main__':run()
