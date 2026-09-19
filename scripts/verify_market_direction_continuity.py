"""Independent raw-minute audit of the saved continuity review."""
import hashlib,json,csv,io
from pathlib import Path
from zipfile import ZipFile
root=Path(__file__).resolve().parents[1];folder=root/'reports/validation/market_direction_continuity_20260919'
r=json.loads((folder/'review.json').read_text())
closes={}
for month in ('07','08'):
 p=root/f'data/historical/btcusdc_public_20260917/klines/BTCUSDC-1m-2026-{month}.zip'
 with ZipFile(p) as z,z.open(z.namelist()[0]) as f:
  for row in csv.DictReader(io.TextIOWrapper(f)):
   closes[int(row['open_time'])+60000]=float(row['close'])
assert all(hashlib.sha256((root/p).read_bytes()).hexdigest()==v for p,v in r['source_sha256'].items())
verified=0
for case in r['cases']:
 events=case['events']
 for i,e in enumerate(events):
  if e['kind']!='basis_adopted':continue
  c=e['root']['candidate'];t=e['time_ms'];step=e['root']['minutes']*60000
  assert c['formed_ms']<=t and c['evidence_available_ms']<=t
  for k in ('protected','broken','prior_reaction'):assert c[k]['available_ms']<=t
  invalid=next((x for x in events[i+1:] if x['kind']=='basis_invalidated'),None)
  end=invalid['time_ms'] if invalid else case['end_ms']
  raw_break=next((x for x in range((t//step+1)*step,end+1,step) if c['side']*(closes[x]-c['protected']['price'])<0),None)
  assert raw_break==(invalid['time_ms'] if invalid else None)
  if invalid:
   assert invalid['root']==e['root']
   later=[x for x in events[i+1:] if x['kind']=='basis_adopted']
   if later:
    assert later[0]['time_ms']>raw_break
    assert later[0]['root']['candidate']['formed_ms']>raw_break
  verified+=1
 for p in case['points']:
  for key in ('remembered','day_start_reset'):assert p[key]['new_exposure_allowed'] is False
six=r['cases'][:6]
result=dict(source_hashes='PASS',raw_minute_anchor_breaks='PASS',verified_adoptions=verified,
            opposite_sequence='PASS',new_exposure_approval=False,
            checkpoints=sum(c['counts']['points'] for c in six),
            before_unknown=sum(c['counts']['old_unknown'] for c in six),
            after_unknown=sum(c['counts']['memory_unknown'] for c in six),
            start_state_sensitive=sum(c['counts']['start_state_sensitive'] for c in six),
            start_basis_sensitive=sum(c['counts']['start_basis_sensitive'] for c in six))
(folder/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
