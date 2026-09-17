"""Boundary tests for pure v1 order semantics, never exchange transport."""
from dataclasses import replace
from decimal import Decimal as D
import unittest
from app.research.execution.order_rules import (
    Rules, Reentry, TargetAnchor, TakeProfit, StopBasis, Levels, SignalState,
    EntryBook, update_signal, reserve_entry, finish_cycle, prepare_cycle, assess_fill, Bar, evaluate_bar)


def rules(**changes):
    return replace(Rules(Reentry.FRESH_EPISODE,TargetAnchor.ENTRY_DECISION,
                         TakeProfit.CLOSE_CONFIRM_MARKET,StopBasis.ATR),**changes)


def levels(time=0, **changes):
    return replace(Levels(time,D('100'),D('2'),D('95'),D('105'),D('110')),**changes)


def signal(side=1):
    value=levels(target=D('110') if side==1 else D('90'))
    return update_signal(SignalState('paper/BTCUSDC/F0-vNext'),side,value)


def reserve(book,state,policy=None,**changes):
    args=dict(now_ms=state.latest.available_ms+60000,reconciled_flat_and_orders_clear=True,
              risk_approved=True,signal_valid=True)
    args.update(changes)
    return reserve_entry(book,state,policy or rules(),**args)


def cycle(side=1,**changes):
    return prepare_cycle(signal(side),rules(**changes),'test-cycle',D('100'))


def bar(**changes):
    return replace(Bar(60000,120000,D('100'),D('105'),D('95'),D('101')),**changes)


class SignalRulesTests(unittest.TestCase):
    def test_same_episode_updates_latest_but_preserves_anchor(self):
        first=signal();second=update_signal(first,1,levels(3600000,target=D('112')))
        self.assertEqual(first.episode_id,second.episode_id)
        self.assertEqual(second.anchor.target,D('110'))
        self.assertEqual(second.latest.target,D('112'))

    def test_neutral_then_same_side_is_new_episode(self):
        first=signal();neutral=update_signal(first,0,levels(3600000))
        again=update_signal(neutral,1,levels(7200000))
        self.assertNotEqual(first.episode_id,again.episode_id)

    def test_opposite_direction_new_episode(self):
        first=signal();second=update_signal(first,-1,levels(3600000,target=D('90')))
        self.assertNotEqual(first.episode_id,second.episode_id)

    def test_idempotent_and_conflicting_observations(self):
        first=signal()
        self.assertEqual(update_signal(first,1,levels()),first)
        with self.assertRaises(ValueError): update_signal(first,-1,levels())
        newer=update_signal(first,1,levels(3600000))
        with self.assertRaises(ValueError): update_signal(newer,1,levels())

    def test_namespace_ids_are_distinct(self):
        first=signal();second=update_signal(SignalState('other/BTCUSDC/F0-vNext'),1,levels())
        self.assertNotEqual(first.episode_id,second.episode_id)

    def test_fresh_episode_reservation_blocks_reentry(self):
        first=signal();book,result=reserve(EntryBook(),first)
        self.assertTrue(result.approved)
        book=finish_cycle(book,result.intent_id,confirmed_ms=120000,reconciled_flat_and_orders_clear=True)
        later=update_signal(first,1,levels(3600000))
        self.assertEqual(reserve(book,later)[1].reason,'EPISODE_ALREADY_RESERVED')
        renewed=update_signal(update_signal(later,0,levels(7200000)),1,levels(10800000))
        self.assertTrue(reserve(book,renewed)[1].approved)

    def test_continuing_requires_later_decision_and_clear_orders(self):
        policy=rules(reentry=Reentry.CONTINUING_NEXT_DECISION)
        book,result=reserve(EntryBook(),signal(),policy)
        self.assertFalse(reserve(book,signal(),policy)[1].approved)
        later=update_signal(signal(),1,levels(3600000))
        self.assertFalse(reserve(book,later,policy,reconciled_flat_and_orders_clear=False)[1].approved)
        book=finish_cycle(book,result.intent_id,confirmed_ms=120000,reconciled_flat_and_orders_clear=True)
        self.assertTrue(reserve(book,later,policy)[1].approved)

    def test_close_requires_new_completed_decision_and_order_reconciliation(self):
        policy=rules(reentry=Reentry.CONTINUING_NEXT_DECISION)
        book,result=reserve(EntryBook(),signal(),policy)
        for identity,clear in ((result.intent_id,False),('wrong',True)):
            with self.assertRaises(ValueError):
                finish_cycle(book,identity,confirmed_ms=4000000,reconciled_flat_and_orders_clear=clear)
        book=finish_cycle(book,result.intent_id,confirmed_ms=4000000,reconciled_flat_and_orders_clear=True)
        old=update_signal(signal(),1,levels(3600000))
        self.assertEqual(reserve(book,old,policy,now_ms=4100000)[1].reason,'NEW_COMPLETED_DECISION_AFTER_CLOSE_REQUIRED')
        new=update_signal(old,1,levels(7200000))
        self.assertTrue(reserve(book,new,policy)[1].approved)

    def test_no_risk_or_future_decision_does_not_consume(self):
        for changes in (dict(risk_approved=False),dict(signal_valid=False),dict(now_ms=59999)):
            book,result=reserve(EntryBook(),signal(),**changes)
            self.assertFalse(result.approved);self.assertEqual(book,EntryBook())


class LevelRulesTests(unittest.TestCase):
    def test_explicit_target_anchor(self):
        later=update_signal(signal(),1,levels(3600000,target=D('112')))
        a=prepare_cycle(later,rules(target_anchor=TargetAnchor.EPISODE_START),'a',D('100'))
        b=prepare_cycle(later,rules(),'b',D('100'))
        self.assertEqual((a.target,a.target_source_ms),(D('110'),0))
        self.assertEqual((b.target,b.target_source_ms),(D('112'),3600000))

    def test_stop_structure_and_atr_are_separate(self):
        self.assertEqual(cycle().stop,D('94'))
        self.assertEqual(cycle(stop_basis=StopBasis.STRUCTURE).stop,D('94.9'))
        self.assertEqual(cycle(-1).stop,D('106'))
        self.assertEqual(cycle(-1,stop_basis=StopBasis.STRUCTURE).stop,D('105.1'))

    def test_adverse_entry_does_not_move_target_or_stop(self):
        for entry in ('110','94','111'):
            with self.assertRaises(ValueError): prepare_cycle(signal(),rules(),'a',D(entry))

    def test_fill_cost_and_reserved_risk(self):
        args=dict(average=D('100'),quantity=D('.1'),reserved_loss=D('1'),roundtrip_cost_per_btc=D('1'))
        self.assertEqual(assess_fill(cycle(),**args),'PROTECT_FILLED_QUANTITY_RECHECK_REMAINDER')
        for update in (dict(quantity=D('1')),dict(average=D('110')),dict(average=D('93')),dict(roundtrip_cost_per_btc=D('11'))):
            self.assertEqual(assess_fill(cycle(),**dict(args,**update)),'URGENT_EXIT_CANCEL_ENTRY_REMAINDER')

    def test_invalid_numeric_rules_fail(self):
        with self.assertRaises(ValueError): levels(atr=D('NaN'))
        with self.assertRaises(ValueError): rules(structure_buffer_ticks=0)
        with self.assertRaises(ValueError): rules(take_profit='TOUCH_MARKET')


class ExitRulesTests(unittest.TestCase):
    def check(self,plan=None,candle=None,**changes):
        return evaluate_bar(plan or cycle(),candle or bar(),active_from_ms=changes.pop('active_from_ms',60000),**changes)

    def test_close_confirmation_does_not_use_high_or_same_close_fill(self):
        candle=bar(high=D('112'),close=D('109'))
        self.assertEqual(self.check(candle=candle,strategy_close_available=True).kind,'NONE')
        candle=replace(candle,close=D('111'))
        self.assertEqual(self.check(candle=candle).kind,'NONE')
        result=self.check(candle=candle,strategy_close_available=True)
        self.assertEqual(result.kind,'SCHEDULE_EXIT');self.assertEqual(result.earliest_ms,180000)
        self.assertIsNone(result.reference)

    def test_touch_market_and_limit_are_not_same_fill(self):
        candle=bar(high=D('112'))
        a=self.check(cycle(take_profit=TakeProfit.TOUCH_MARKET),candle)
        b=self.check(cycle(take_profit=TakeProfit.RESTING_LIMIT),candle)
        self.assertEqual(a.kind,'EXIT_REQUIRED');self.assertEqual(a.reference,D('110'))
        self.assertEqual(b.kind,'LIMIT_EXECUTION_EVIDENCE_REQUIRED')

    def test_both_touched_stop_first_and_flagged(self):
        for mode in (TakeProfit.TOUCH_MARKET,TakeProfit.RESTING_LIMIT):
            result=self.check(cycle(take_profit=mode),bar(high=D('112'),low=D('92')))
            self.assertEqual(result.reason,'STOP_FIRST_OHLC');self.assertTrue(result.ambiguous)

    def test_stop_gap_uses_open_and_short_symmetric(self):
        a=self.check(candle=bar(open=D('90'),low=D('89')))
        b=self.check(cycle(-1),bar(open=D('110'),high=D('112')))
        self.assertEqual(a.reference,D('90'));self.assertEqual(b.reference,D('110'))
        self.assertEqual(a.reason,'STOP_GAP');self.assertEqual(b.reason,'STOP_GAP')

    def test_opening_target_before_later_stop_market_only(self):
        result=self.check(cycle(take_profit=TakeProfit.TOUCH_MARKET),bar(open=D('112'),high=D('113'),low=D('90')))
        self.assertEqual(result.reason,'TARGET_GAP_MARKET_PROXY');self.assertEqual(result.reference,D('112'))

    def test_protection_bypasses_pending_normal_exit(self):
        result=self.check(candle=bar(low=D('92')),pending_exit=True)
        self.assertEqual(result.kind,'URGENT_RECONCILE_EXIT')
        self.assertEqual(self.check(pending_exit=True).kind,'RECONCILE_EXIT')

    def test_risk_halt_does_not_wait_limit_timeout(self):
        self.assertEqual(self.check(risk_halt=True).kind,'URGENT_EXIT_REQUIRED')
        self.assertEqual(self.check(risk_halt=True,pending_exit=True).kind,'URGENT_RECONCILE_EXIT')

    def test_midbar_entry_or_expiry_needs_finer_data(self):
        self.assertEqual(self.check(active_from_ms=90000).kind,'FINER_DATA_REQUIRED')
        self.assertEqual(self.check(cycle(maximum_hold_ms=30000)).reason,'EXPIRY_INSIDE_BAR')

    def test_time_exit_precedes_unknown_intrabar_extreme(self):
        candle=bar(start_ms=120000,end_ms=180000,low=D('92'))
        result=self.check(cycle(maximum_hold_ms=60000),candle)
        self.assertEqual(result.reason,'TIME_LIMIT');self.assertEqual(result.reference,D('100'))

    def test_future_position_not_active(self):
        self.assertEqual(self.check(active_from_ms=120000).kind,'NONE')

    def test_bad_ohlc_rejected(self):
        with self.assertRaises(ValueError): bar(high=D('90'))


class CycleFlowTests(unittest.TestCase):
    def test_reserve_fill_target_close_and_rearm(self):
        policy=rules()
        first=signal()
        book,reservation=reserve(EntryBook(),first,policy)
        plan=prepare_cycle(first,policy,reservation.intent_id,D('100'))
        self.assertEqual(assess_fill(plan,average=D('100'),quantity=D('.1'),reserved_loss=D('1'),
                                    roundtrip_cost_per_btc=D('1')),'PROTECT_FILLED_QUANTITY_RECHECK_REMAINDER')
        exit=evaluate_bar(plan,bar(high=D('112'),close=D('111')),active_from_ms=60000,strategy_close_available=True)
        self.assertEqual(exit.kind,'SCHEDULE_EXIT')
        # Exit intent is not proof of being flat.
        self.assertFalse(reserve(book,update_signal(first,1,levels(3600000)),policy)[1].approved)
        book=finish_cycle(book,reservation.intent_id,confirmed_ms=180000,reconciled_flat_and_orders_clear=True)
        continuing=update_signal(first,1,levels(3600000))
        self.assertFalse(reserve(book,continuing,policy)[1].approved)
        fresh=update_signal(update_signal(continuing,0,levels(7200000)),1,levels(10800000))
        self.assertTrue(reserve(book,fresh,policy)[1].approved)

    def test_partial_fill_target_passed_requests_exit_not_fake_rejection(self):
        plan=cycle(take_profit=TakeProfit.RESTING_LIMIT)
        result=assess_fill(plan,average=D('111'),quantity=D('.001'),reserved_loss=D('1'),
                           roundtrip_cost_per_btc=D('1'))
        self.assertEqual(result,'URGENT_EXIT_CANCEL_ENTRY_REMAINDER')
        self.assertEqual(plan.target,D('110'))
        # A live normal exit must be reconciled when protection is triggered.
        result=evaluate_bar(plan,bar(low=D('92')),active_from_ms=60000,pending_exit=True)
        self.assertEqual(result.kind,'URGENT_RECONCILE_EXIT')
