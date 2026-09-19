import importlib
from copy import deepcopy
from pathlib import Path
import pytest


@pytest.fixture
def join(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    m=importlib.import_module('review_local_failure_continuation')
    state=dict(pending=None,active_obligation=None,obligations=dict(waiting=[]),
               summary=dict(halted=False,final=dict(position=m.PositionExample(-1,'.003',100,0,0,0,1000))))
    return m,state


@pytest.mark.parametrize('change',[
    dict(pending=dict(remaining='.003')),dict(active_obligation=dict(kind='target')),
    dict(obligations=dict(waiting=['target'])),
])
def test_unresolved_obligation_rejected_without_mutating_inventory(join,change):
    m,state=join;state.update(change);before=deepcopy(state)
    with pytest.raises(ValueError,match='unresolved'):m.require_clean_join(state)
    assert state==before


def test_halt_cannot_be_erased_by_new_replay(join):
    m,state=join;state['summary']['halted']=True
    with pytest.raises(ValueError,match='halted'):m.require_clean_join(state)


def test_clean_join_preserves_live_remaining_position(join):
    m,state=join;before=deepcopy(state);m.require_clean_join(state)
    assert state==before
