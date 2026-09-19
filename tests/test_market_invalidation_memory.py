"""Validate the audit controls, including a case where erasing memory changes behavior."""
import importlib
from pathlib import Path
import pytest


@pytest.fixture
def m(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    return importlib.import_module('review_market_invalidation_memory')


@pytest.mark.parametrize('mode',['current_cross','confirmed_path','confirmed_path_reanchor','confirmed_path_causal_target','confirmed_path_opposition_retest'])
def test_observation_only_instrumentation_preserves_original_output(m,mode):
    case=m.synthetic_counterexample();bars,pivots=case['bars'],case['pivots']
    result=m.audit_reduce(bars,pivots,after_ms=0,mode=mode)
    assert result['result']==m.reduce_structure(bars,pivots,confirmation_mode=mode)
    assert result['applied']==[]


def test_memory_erasure_can_bypass_the_required_later_retest(m):
    case=m.synthetic_counterexample();baseline,erased=case['baseline'],case['erased']
    assert baseline['result']['candidate']['formed_ms']==19
    assert erased['result']['candidate']['formed_ms']==18
    assert erased['applied']==[dict(time_ms=18,old=17,new=None)]
    assert case['bars'][-2]['close']==104  # Above the old long basis 100: not a valid short retest.
    assert baseline['branches'][0]['inherited'] is True
    assert erased['branches'][0]['inherited'] is False


def test_override_is_once_and_does_not_erase_a_later_real_invalidation(m):
    c=m.synthetic_counterexample()
    bars=c['bars']+[dict(end_ms=20,close=116,low=115,high=117),dict(end_ms=21,close=114,low=113,high=115)]
    r=m.audit_reduce(bars,c['pivots'],after_ms=17,override=None)
    assert len(r['applied'])==1
    assert r['states'][-1]['invalidated_before']==20
    assert r['states'][-1]['invalidated_used']==20


def test_cutoff_and_future_evidence_do_not_leak_into_prefix(m):
    c=m.synthetic_counterexample();bars=c['bars'];ps=c['pivots']
    prefix=m.audit_reduce(bars[:-2],ps,after_ms=17,override=None)
    assert prefix['applied']==[] and prefix['states']==[] and prefix['branches']==[]
    future=ps+[dict(id='future',kind='high',price=999,pivot_bar_end_ms=30,available_ms=32)]
    assert m.audit_reduce(bars,future,after_ms=17)['result']==c['baseline']['result']


def test_input_records_are_not_mutated(m):
    from copy import deepcopy
    c=m.synthetic_counterexample();before=deepcopy((c['bars'],c['pivots']))
    m.audit_reduce(c['bars'],c['pivots'],after_ms=17,override=None)
    assert (c['bars'],c['pivots'])==before
