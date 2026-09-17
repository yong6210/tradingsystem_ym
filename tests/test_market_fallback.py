import unittest
from decimal import Decimal as D
from dataclasses import replace,asdict
from app.research.execution.market_fallback import State, Snapshot,plan


class MarketFallbackTests(unittest.TestCase):
    def setUp(self):
        self.state=State('limit-1',D('.003'),1,'entry',3000)
        self.args=dict(now_ms=3000,signal_valid=True,approved_market_qty=D('.003'),position_qty=D('0'),context_observed_ms=3000)

    def call(self,status,fill='0',state=None,**kwargs):
        args=self.args|kwargs
        return plan(state or self.state,Snapshot('limit-1',status,D(fill),args['now_ms']),**args)

    def test_wait_then_cancel_never_immediate_market(self):
        self.assertEqual(self.call('NEW',now_ms=2999)[1].kind,'WAIT')
        state,action=self.call('PARTIALLY_FILLED','.001')
        self.assertEqual(action.kind,'CANCEL_ORIGINAL')
        self.assertEqual(self.call('PARTIALLY_FILLED','.002',state)[1].kind,'QUERY_ORIGINAL')

    def test_fill_during_cancel_reduces_replacement(self):
        state,_=self.call('PARTIALLY_FILLED','.001')
        state,action=self.call('CANCELED','.002',state)
        self.assertEqual(action.quantity,D('.001'))
        self.assertEqual(action.kind,'MARKET_INTENT')
        self.assertEqual(self.call('CANCELED','.002',state)[1].kind,'RECONCILE_MARKET')

    def test_full_fill_wins_cancel_race(self):
        state,_=self.call('NEW')
        state,action=self.call('FILLED','.003',state)
        self.assertEqual(state.phase,'DONE');self.assertEqual(action.kind,'NONE')

    def test_stale_unknown_snapshot_cannot_trigger_market(self):
        self.assertEqual(self.call('UNKNOWN')[1].kind,'QUERY_ORIGINAL')
        s=Snapshot('limit-1','CANCELED',D('0'),0)
        self.assertEqual(plan(self.state,s,**self.args)[1].kind,'QUERY_ORIGINAL')

    def test_new_market_risk_is_checked(self):
        self.assertEqual(self.call('CANCELED',approved_market_qty=D('.001'))[1].quantity,D('.001'))
        self.assertEqual(self.call('CANCELED',approved_market_qty=D('0'))[0].phase,'SKIPPED')
        self.assertEqual(self.call('CANCELED',signal_valid=False)[0].phase,'SKIPPED')
        self.assertEqual(self.call('CANCELED',context_observed_ms=0)[1].kind,'REFRESH_CONTEXT')

    def test_exit_is_reduce_only_and_capped_at_live_position(self):
        state=replace(self.state,side=-1,purpose='exit')
        _,action=self.call('CANCELED',state=state,position_qty=D('.001'),signal_valid=False)
        self.assertEqual(action.quantity,D('.001'));self.assertTrue(action.reduce_only)
        self.assertEqual(self.call('CANCELED',state=state,position_qty=D('-.001'))[1].kind,'HALT_RECONCILE')
        self.assertEqual(self.call('CANCELED',state=state,position_qty=D('0'))[0].phase,'DONE')

    def test_blocked_exit_escalates_instead_of_silent_skip(self):
        state=replace(self.state,side=-1,purpose='exit')
        self.assertEqual(self.call('CANCELED',state=state,position_qty=D('.001'),approved_market_qty=D('0'))[1].kind,'ESCALATE_EXIT')

    def test_restored_planned_state_does_not_create_second_order(self):
        state,action=self.call('CANCELED')
        restored=State(**asdict(state))
        next_action=self.call('CANCELED',state=restored)[1]
        self.assertEqual(next_action.kind,'RECONCILE_MARKET')
        self.assertEqual(next_action.client_id,action.client_id)

    def test_bad_cumulative_fill_rejected(self):
        with self.assertRaises(ValueError):self.call('CANCELED','.004')
        with self.assertRaises(ValueError):self.call('FILLED','.001')
        with self.assertRaises(ValueError):self.call('CANCELED',approved_market_qty=D('NaN'))


if __name__=='__main__':unittest.main()
