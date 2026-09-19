"""Independently enumerate pair predicates and check raw future-close failures."""
import csv,hashlib,io,json
from pathlib import Path
from zipfile import ZipFile
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/structure_role_diagnostic_20260920'
MINUTE=60000


def key(n):
    c=n['candidate']
    return (n['minutes'],c['side'],c['formed_ms'],tuple((c[k]['price'],c[k]['pivot_bar_end_ms'],c[k]['available_ms']) for k in ('prior_reaction','broken','protected')))


def main():
    path=OUT/'review.json';report=json.loads(path.read_text())
    for p,h in report['source_sha256'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h,p
    scan=json.loads((ROOT/'reports/validation/six_case_entry_scan_20260920/review.json').read_text())
    old=json.loads((ROOT/'reports/validation/market_basis_revision_20260919/review.json').read_text())
    originals={c['label']:c for c in scan['cases']};originals['original_nine']=next(c for c in old['cases'] if c['label']=='original_nine')
    raw={}
    for month in ('07','08'):
        with ZipFile(ROOT/f'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-{month}.zip') as z,z.open(z.namelist()[0]) as fp:
            for r in csv.DictReader(io.TextIOWrapper(fp)):
                t=int(r['open_time'])+MINUTE;assert t not in raw;raw[t]=Decimal(r['close'])
    for case in report['cases']:
        prior=originals[case['label']];assert [p['time_ms'] for p in case['points']]==[p['time_ms'] for p in prior['points']]
        first={}
        for p,base in zip(case['points'],prior['points']):
            assert p['baseline_state']==base.get('state',base.get('updated_only'))
            assert p['baseline_support']==base.get('support',base.get('guarded'))
            groups=[]
            for v in p['views']:
                active=[n for n in v['nodes'] if n['candidate'] and n['candidate']['status']=='active']
                unique={}
                for n in active:
                    c=n['candidate'];sig=(c['side'],*(c[k]['price'] for k in ('prior_reaction','broken','protected')))
                    if sig not in unique or c['formed_ms']>unique[sig]['candidate']['formed_ms']:unique[sig]=n
                candidates={}
                for a in unique.values():
                    for b in unique.values():
                        x,y=a['candidate'],b['candidate']
                        eligible=(a['minutes']!=b['minutes'] and x['side']==y['side'] and
                            x['prior_reaction']['pivot_bar_end_ms']<y['prior_reaction']['pivot_bar_end_ms'] and
                            x['protected']['pivot_bar_end_ms']<y['protected']['pivot_bar_end_ms'] and
                            all(a['low']<=y[k]['price']<=a['high'] for k in ('prior_reaction','broken','protected')))
                        if eligible:candidates[(key(a),key(b))]=(a,b)
                groups.append((candidates,unique))
            expected=set(groups[0][0])&set(groups[1][0]);observed={(key(q['root']),key(q['support'])) for q in p['diagnostic']['common_pairs']}
            assert observed==expected
            assert p['diagnostic']['history_pair_counts']==[len(g[0]) for g in groups]
            for q in p['diagnostic']['common_pairs']:
                first.setdefault(q['pair_id'],(p['time_ms'],q))
                for i,(pairs,unique) in enumerate(groups):
                    a=pairs[(key(q['root']),key(q['support']))][0]
                    expected_opp=[]
                    for n in unique.values():
                        c=n['candidate']
                        if c['side']==q['side']:continue
                        outer=c['prior_reaction']['pivot_bar_end_ms']<a['candidate']['prior_reaction']['pivot_bar_end_ms'] and all(n['low']<=a['candidate'][k]['price']<=n['high'] for k in ('prior_reaction','broken','protected'))
                        expected_opp.append((key(n),outer))
                    assert sorted(expected_opp)==sorted((key(o['node']),o['outer']) for o in q['opposition_by_history'][i])
        assert len(first)==len(case['episodes'])
        for e in case['episodes']:
            t,q=first[e['pair_id']];assert t==e['first_observed_ms'] and q==e['pair']
            for role in ('root','support'):
                n=q[role];c=n['candidate'];step=n['minutes']*MINUTE
                times=range((t//step+1)*step,case['end_ms']+1,step)
                expected=None
                for x in times:
                    assert all(m in raw for m in range(x-step+MINUTE,x+1,MINUTE))
                    if c['side']*(raw[x]-Decimal(str(c['protected']['price'])))<0:expected=x;break
                found=e['retrospective_followup'][role]
                assert expected==(None if found is None else found['time_ms'])
                if found:assert Decimal(str(found['close']))==raw[expected]
    result=dict(source_hashes='PASS',baseline_all_points_unchanged='PASS',independent_pair_enumeration='PASS',
        independent_opposition_roles='PASS',raw_first_adverse_closes='PASS',
        prefix_checks=report['checks'],actual_orders=False,
        report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
