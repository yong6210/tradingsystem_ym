"""Source boundaries and state provenance, not market labels."""
import importlib
from copy import deepcopy
from pathlib import Path
import pytest


@pytest.fixture
def m(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    return importlib.import_module('review_market_startup_provenance')


def pivot(t,price=100):
    return dict(id=f'high:{t}',kind='high',price=price,pivot_bar_end_ms=t,available_ms=t+120000)


def test_boundary_left_context_is_distinct_from_missing_old_history(m):
    start=60*m.MINUTE
    old=pivot(start)
    edge=pivot(start+2*15*m.MINUTE)
    later=pivot(start+3*15*m.MINUTE)
    args=dict(history_start=start,minutes=15,t=start+120*m.MINUTE)
    assert m.missing_landmark(old,[],**args)=='formed_before_or_at_history_start'
    assert m.missing_landmark(edge,[],**args)=='insufficient_left_context_at_boundary'
    assert m.missing_landmark(later,[],**args)=='not_observed_in_other_history'
    assert m.missing_landmark(edge,[edge],**args) is None


def test_partial_first_bar_does_not_count_as_left_context(m):
    start=61*m.MINUTE
    p=pivot(105*m.MINUTE)  # Complete bars end 90, 105; center 105 still lacks a second left bar.
    assert m.missing_landmark(p,[],history_start=start,minutes=15,t=180*m.MINUTE)=='insufficient_left_context_at_boundary'
    later=pivot(120*m.MINUTE)
    assert m.missing_landmark(later,[],history_start=start,minutes=15,t=180*m.MINUTE)=='not_observed_in_other_history'


def candidate(m,status='active'):
    return dict(side=1,status=status,formed_ms=200*m.MINUTE,
                prior_reaction=pivot(100*m.MINUTE,90),broken=pivot(120*m.MINUTE,110),protected=pivot(140*m.MINUTE,100))


def test_same_current_landmarks_do_not_imply_same_state(m):
    a=candidate(m);b=deepcopy(a);b['status']='invalidated'
    registry=[a[k] for k in ('prior_reaction','broken','protected')]
    nodes=[dict(minutes=15,candidate=a),dict(minutes=15,candidate=b)]
    r=m.compare_nodes(nodes,[registry,registry],[0,0],300*m.MINUTE)
    assert r['status']=='different_despite_current_landmarks_available' and not r['missing']
    nodes[1]['candidate']=deepcopy(a)
    assert m.compare_nodes(nodes,[registry,registry],[0,0],300*m.MINUTE)['status']=='same_basis_and_state'


def test_missing_candidate_is_not_neutral_or_automatic_opposite(m):
    a=candidate(m);nodes=[dict(minutes=15,candidate=None),dict(minutes=15,candidate=a)]
    registry=[a[k] for k in ('prior_reaction','broken','protected')]
    r=m.compare_nodes(nodes,[[],registry],[150*m.MINUTE,0],300*m.MINUTE)
    assert r['status']=='different_with_missing_landmarks'
    assert len(r['missing'])==3 and 'side' not in r


def test_even_matching_future_candidates_are_rejected(m):
    a=candidate(m);nodes=[dict(minutes=15,candidate=a),dict(minutes=15,candidate=deepcopy(a))]
    with pytest.raises(ValueError,match='future'):
        m.compare_nodes(nodes,[[],[]],[0,0],150*m.MINUTE)
    with pytest.raises(ValueError,match='two histories'):
        m.compare_nodes(nodes[:1],[[]],[0],300*m.MINUTE)


def test_prices_and_availability_must_match_not_only_pivot_id(m):
    p=pivot(100*m.MINUTE);wrong=dict(p,price=101)
    args=dict(history_start=0,minutes=15,t=200*m.MINUTE)
    assert m.missing_landmark(p,[wrong],**args)=='not_observed_in_other_history'
    with pytest.raises(ValueError,match='future'):
        m.missing_landmark(p,[],**dict(args,t=100*m.MINUTE))
