"""Reuse the independent raw-data account audit and check return classification."""
import hashlib
import json
from pathlib import Path

import verify_market_transition_inventory as account_audit
from review_market_return_followup import ROOT, OUT, CONFIG, first_return


def main():
    r = json.loads((OUT / 'review.json').read_text())
    cfg = json.loads(CONFIG.read_text())
    assert r['config'] == cfg
    assert r['selection']['config_sha256'] == hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    market = r['market']
    # Independently enumerate all qualifying snapshots rather than trust selection.json.
    candidates = []
    for p in market['points']:
        t = p['time_ms']
        if t <= market['failure_ms']:
            continue
        root = p['state']['root']
        if root:
            c = root['candidate']
            assert c['formed_ms'] <= t and c['evidence_available_ms'] <= t
        if p['support']['side'] == cfg['original_side']:
            assert root is not None and p['support']['support']
            if root['candidate']['formed_ms'] > market['failure_ms']:
                candidates.append(t)
    assert r['selection']['return_ms'] == (min(candidates) if candidates else None)
    assert (first_return(market, cfg['original_side']) is None) == (not candidates)
    assert market['points'][-1]['time_ms'] - market['failure_ms'] == 7 * 86400000
    # Same independently implemented Decimal arithmetic, unchanged prior verifier.
    previous_out = account_audit.OUT
    try:
        account_audit.OUT = OUT
        account_audit.main()
    finally:
        account_audit.OUT = previous_out
    path = OUT / 'verification.json'
    verification = json.loads(path.read_text())
    # No zero-liquidity scenario was repeated in this follow-up.
    verification.pop('unfilled_exit_retains_position', None)
    verification.update(fixed_window='PASS', return_classification='PASS',
                        returned=bool(candidates), prior_prefix=r['checks'],
                        verifier_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in (ROOT / 'scripts/verify_market_transition_inventory.py', Path(__file__))})
    path.write_text(json.dumps(verification, indent=2) + '\n')
    print(json.dumps(verification))


if __name__ == '__main__':
    main()
