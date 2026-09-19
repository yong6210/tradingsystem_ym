"""Check the admission audit against raw minute prices and recorded evidence times."""
import csv,hashlib,io,json
from decimal import Decimal as D
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/validation/oneway_admission_20260919'


def main():
    r=json.loads((OUT/'review.json').read_text())
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in r['source_sha256'].items())
    for name in ('market_basis_revision_20260919','market_judgment_regimes_20260919'):
        prior=json.loads((ROOT/f'reports/validation/{name}/review.json').read_text())
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in prior['source_sha256'].items())
    archive=ROOT/'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-08.zip'
    with ZipFile(archive) as z,z.open(z.namelist()[0]) as f:
        raw={int(b['open_time'])+60000:{k:D(b[k]) for k in ('high','low','close')} for b in csv.DictReader(io.TextIOWrapper(f))}
    points=r['points'];start,end=r['case']['start_ms'],r['case']['end_ms']
    assert [p['time_ms'] for p in points]==sorted({p['time_ms'] for p in points})
    assert set(range(start,end+1,900000))<={p['time_ms'] for p in points}
    assert raw[end]['close']-raw[start]['close']==D(r['shape']['net'])
    first_long=min(p['time_ms'] for p in points if p['support']['side']==1)
    assert first_long==r['summary']['first_long_support_ms']
    for p in points:
        t=p['time_ms'];assert D(str(p['mark']))==raw[t]['close']
        assert p['support']['side']!=-1
        root=p['state']['root']
        if root:
            c=root['candidate'];assert c['formed_ms']<=t and c['evidence_available_ms']<=t
            assert all(c[k]['available_ms']<=t for k in ('protected','broken','prior_reaction'))
        for side,group in p['reactions'].items():
            for reaction in group:
                assert reaction['pivot_bar_end_ms']<=reaction['available_ms']<reaction['departed_ms']<t
                if side=='1':assert t<first_long  # No long reaction coincides with supported long direction.
        assert p['reviews']['flat']['result']['action']!='entry_candidate'
        assert p['reviews']['fixed_short_diagnostic']['result']['action']!='add_candidate'
        assert D(p['reviews']['fixed_short_diagnostic']['result']['position']['quantity'])==D('.006')
        assert D(p['reviews']['flat']['result']['position']['quantity'])==0
    assert not r['summary']['entry_candidate_times'] and not r['summary']['short_add_candidate_times']
    assert r['account_simulated'] is False and r['orders_generated']==0 and r['new_exposure_allowed'] is False
    verification=dict(source_hashes='PASS',prior_source_integrity='PASS',raw_prices='PASS',quarter_hour_coverage='PASS',
                      evidence_available_before_decision='PASS',no_direction_reaction_overlap_for_entry='PASS',
                      hypothetical_inventory_not_mistaken_for_fills='PASS',prior_and_prefix_checks=r['checks'],
                      verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2)+'\n');print(json.dumps(verification))


if __name__=='__main__':main()
