"""Resolve actual contact provenance; do not issue a market thesis or order."""
from pathlib import Path
import json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.research.recovery.thesis_evidence import ThesisEvidenceRegistry


def run():
    source=ROOT/'reports/validation/grouped_contact_positions_20260919/comparison.json'
    raw=source.read_bytes();data=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
    records=[]
    for card in data['cards']:
        g=card['contact']
        for s in g['sources']:
            records.append(dict(id='observation:'+s['candidate_id'],available_ms=g['available_ms'],
                event_key=g['id'],source_sha256=sha,source_path=str(source.relative_to(ROOT)),
                candidate_confirmed_ms=s['confirmed_ms'],marker_price=g['marker_price'],
                close=g['close'],kind=s['kind']))
    registry=ThesisEvidenceRegistry(records);audits=[]
    for r in records:
        audit=registry.resolve([r['id']],observed_ms=r['available_ms'])
        audits.append(audit)
        try:registry.resolve([r['id']],observed_ms=r['available_ms']-1)
        except ValueError:pass
        else:raise AssertionError('future evidence accepted')
    all_evidence=registry.resolve([r['id'] for r in records],observed_ms=max(r['available_ms'] for r in records))
    summary=dict(references=len(records),exact_provenance_groups=len(all_evidence['body']['provenance_groups']),
        at_availability_passed=len(audits),one_ms_early_rejected=len(audits),direction_assessments_generated=0,orders_generated=0)
    output=dict(summary=summary,records=records,availability_audits=audits,combined_audit=all_evidence,
        source_sha256=sha,code_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__),ROOT/'app/research/recovery/thesis_evidence.py')})
    out=ROOT/'reports/validation/thesis_evidence_references_20260919';out.mkdir(parents=True,exist_ok=False)
    (out/'audit.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':run()
