"""General trial boundaries; these are not market-ground-truth tests."""
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest


@pytest.fixture
def trial(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'scripts'))
    m = importlib.import_module('review_market_judgment_regimes')
    account = json.loads((root / 'configs/research/first_candidate_case_trial.json').read_text())
    costs = m.ExampleCosts('0', '0', '0', '.1', '.001', '2')
    return m, account, costs


def node(minutes, side=1, start=1, protected=2, prices=(80, 100, 90), bounds=(70, 120)):
    return dict(minutes=minutes, low=bounds[0], high=bounds[1], candidate=dict(
        status='active', side=side, formed_ms=protected + 1,
        prior_reaction=dict(price=prices[0], pivot_bar_end_ms=start),
        broken=dict(price=prices[1]), protected=dict(price=prices[2], pivot_bar_end_ms=protected)))


def arguments(m, account, costs, **overrides):
    values = dict(context=dict(side=None, root=None),
        position=m.PositionExample(-1, '.006', '63000', '0', '0', '0', '1000'),
        costs=costs, mark=63000, t=100, account=account, reaction=None,
        target=None, last_growth=10)
    values.update(overrides)
    return values


def test_role_uses_containment_not_timeframe_and_is_symmetric(trial):
    m, _, _ = trial
    nodes = [node(15), node(240, start=4, protected=5, prices=(95, 110, 105))]
    assert m.role_context(nodes)['root']['minutes'] == 15
    reflected = deepcopy(nodes)
    for n in reflected:
        n['low'], n['high'] = 400 - n['high'], 400 - n['low']
        n['candidate']['side'] = -1
        for key in ('prior_reaction', 'broken', 'protected'):
            n['candidate'][key]['price'] = 400 - n['candidate'][key]['price']
    assert m.role_context(reflected)['side'] == -1
    assert m.role_context(reflected)['root']['minutes'] == 15


def test_duplicates_and_opposite_child_do_not_manufacture_support(trial):
    m, _, _ = trial
    assert m.role_context([node(240)])['side'] is None
    assert m.role_context([node(15), node(240)])['active_groups'] == 1
    opposite = node(240, side=-1, start=4, protected=5, prices=(95, 110, 105))
    assert m.role_context([node(15), opposite])['blocker'] == 'no_later_same_side_structure'
    opposite['candidate']['broken']['price'] = 150
    assert m.role_context([node(15), opposite])['side'] is None


def test_history_disagreement_blocks_direction(trial):
    m, _, _ = trial
    a = m.role_context([node(15), node(60, start=4, protected=5, prices=(95, 110, 105))])
    b = m.role_context([node(240)])
    assert m.stable_context([dict(context=a), dict(context=b)])['reason'] == 'history_start_sensitive'


def test_reversal_requires_original_basis_failure_then_later_opposite(trial):
    m, a, c = trial
    root = node(60, side=1, protected=29)
    args = arguments(m, a, c, context=dict(side=1, root=root), original_root=node(60, side=-1))
    assert m.action_review(**args)['action'] == 'wait'
    args['prior_invalidated_ms'] = 20
    result = m.action_review(**args)
    assert result['action'] == 'exit_before_any_opposite_entry'
    assert result['quantity'] == m.dec('.006')
    args['prior_invalidated_ms'] = 30
    assert m.action_review(**args)['action'] == 'wait'


def test_half_is_current_total_rounded_up_even_if_direction_unknown(trial):
    m, a, c = trial
    args = arguments(m, a, c, position=m.PositionExample(-1, '.005', '63000', '0', '0', '0', '1000'), target_hit=True)
    result = m.action_review(**args)
    assert (result['action'], result['quantity']) == ('reduce_half', m.dec('.003'))
    assert m.action_review(**dict(args, reduction_used=True))['action'] == 'wait'


@pytest.mark.parametrize('reaction,expected', [
    (dict(pivot_bar_end_ms=5, available_ms=6), 'historical_marker_not_new_after_growth'),
    (dict(pivot_bar_end_ms=50, available_ms=101), 'reaction_not_available'),
    (dict(pivot_bar_end_ms=90, available_ms=80), 'reaction_not_available'),
])
def test_unavailable_or_old_reaction_cannot_add(trial, reaction, expected):
    m, a, c = trial
    args = arguments(m, a, c, context=dict(side=-1, root=node(60, side=-1)), mark=63100, reaction=reaction)
    assert m.action_review(**args)['reason'] == expected


def test_future_target_cannot_support_addition(trial):
    m, a, c = trial
    args = arguments(m, a, c, context=dict(side=-1, root=node(60, side=-1)), mark=63100,
        reaction=dict(pivot_bar_end_ms=50, available_ms=80), target=dict(price=62000, available_ms=101))
    assert m.action_review(**args)['reason'] == 'no_available_target'


def test_minimum_reduction_restores_stress_not_fixed_price_stop(trial):
    m, a, c = trial
    args = arguments(m, a, c, mark=67000)
    result = m.action_review(**args)
    assert (result['action'], result['quantity']) == ('capacity_reduction_review', m.dec('.001'))
    # Independent zero-cost arithmetic: loss 24 + remaining .005 * 3000 = 39.
    assert m.dec('24') + (m.dec('.006') - result['quantity']) * 3000 <= m.dec(a['total_stress_budget'])
    assert m.dec('24') + m.dec('.006') * 3000 > m.dec(a['total_stress_budget'])
    assert m.action_review(**dict(args, mark=65000))['action'] == 'wait'
    assert m.action_review(**dict(args, mark=71000))['action'] == 'account_halt_review'
