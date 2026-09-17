"""E012 counterfactual sizing contracts; relaxed units are never executable."""
from dataclasses import replace

from ..baseline.risk import Risk, size_order

PROFILES = ('contract_half', 'contract_full', 'fine_half', 'fine_full')


def diagnostic_risk(profile):
    if profile not in PROFILES:
        raise ValueError('unsupported diagnostic profile')
    risk = Risk()
    if profile.endswith('_full'):
        risk = replace(risk, warning_multiplier=1.)
    if profile.startswith('fine_'):
        risk = replace(risk, minimum_qty=1e-8, step=1e-8, minimum_notional=1e-8)
    return risk


def snapshot_choices(attempt, costs):
    """Same flat equity/price/ATR/warning state; no future fills or PnL."""
    return {profile: size_order(attempt['reference'], attempt['close'], attempt['atr'],
                                attempt['side'], attempt['equity'], attempt['warned'],
                                costs, diagnostic_risk(profile)) for profile in PROFILES}


def terminal_contrasts(runs):
    """Finite simulated path contrasts, not additive real-market attribution."""
    a, b, c, d = (runs[p]['return_pct'] for p in PROFILES)
    return dict(full_minus_half_contract_pp=b-a, fine_minus_contract_half_pp=c-a,
                interaction_pp=d-b-c+a, both_minus_baseline_pp=d-a,
                reconstruction_error_pp=(b-a)+(c-a)+(d-b-c+a)-(d-a))
