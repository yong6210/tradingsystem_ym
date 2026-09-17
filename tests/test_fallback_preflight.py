"""Hand-budgeted sizing and offline journal/transport integration."""
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from app.research.execution.binance_contract import Contract
from app.research.execution.durable_fallback import Journal, dispatch_once
from app.research.execution.fallback_preflight import (
    RiskContext, approve_remaining, advance_from_query, authorize_journaled_market, latch_risk,
)
from app.research.execution.market_fallback import State, Snapshot
from tests.test_durable_fallback import FakeExchange


def contract_fixture():
    return Contract(dict(symbol='BTCUSDC', contractType='PERPETUAL', marginAsset='USDC', status='TRADING', filters=[
        dict(filterType='LOT_SIZE', minQty='.001', maxQty='800', stepSize='.001'),
        dict(filterType='MARKET_LOT_SIZE', minQty='.001', maxQty='50', stepSize='.001'),
        dict(filterType='PRICE_FILTER', minPrice='.1', maxPrice='500000', tickSize='.1'),
        dict(filterType='MIN_NOTIONAL', notional='50'),
        dict(filterType='PERCENT_PRICE', multiplierDown='.95', multiplierUp='1.05')]))


def context_fixture():
    return RiskContext(observed_ms=3000, quote_observed_ms=3000, filters_observed_ms=3000,
                       equity=D(1000), peak_equity=D(1000), day_start_equity=D(1000),
                       position_qty=D('.001'), position_risk=D('1.6'), other_reserved_risk=D(0),
                       other_reserved_notional=D(0), pending_exit_qty=D(0), cycle_initial_budget=D(5),
                       cycle_spent=D('.04'), margin_quantity_cap=D('.010'), mark_price=D(60000),
                       worst_entry_price=D(60000), stop_price=D(58500), taker_fee_fraction=D('.0007'),
                       stop_slippage_fraction=D('.0005'), funding_reserve_per_btc=D(0),
                       signal_valid=True, reconciled=True, protection_ready=True, warning_latched=False,
                       drawdown_halted=False, daily_halted=False)


class PreflightFixture:
    def setUp(self):
        self.contract = contract_fixture()
        self.context = context_fixture()
        self.state = State('original-risk-1', D('.003'), 1, 'entry', 3000)
        self.snapshot = Snapshot(self.state.original_id, 'CANCELED', D('.001'), 3000)

    def approve(self, **changes):
        return approve_remaining(self.state, self.snapshot, replace(self.context, **changes), self.contract, now_ms=3000)


class PreflightTests(PreflightFixture, unittest.TestCase):
    def test_remaining_budget_includes_partial_fill_and_paid_costs(self):
        result = self.approve()
        # 5 - 1.6 - .04 = 3.36 available; stop fill 58470.7,
        # unit loss 1529.3 + .0007 * 118470.7 = 1612.22949.
        self.assertEqual(result.remaining_risk, D('3.36'))
        self.assertEqual(result.loss_per_btc, D('1612.22949'))
        self.assertEqual(result.quantity, D('.002'))

    def test_adverse_quote_lowers_quantity_without_moving_stop(self):
        result = self.approve(worst_entry_price=D(61500))
        self.assertEqual(result.quantity, D('.001'))
        self.assertEqual(self.context.stop_price, D(58500))

    def test_warning_never_rounds_up_to_minimum_lot(self):
        result = self.approve(warning_latched=True)
        self.assertEqual(result.quantity, 0)
        self.assertEqual(result.remaining_risk, D('.86'))

    def test_current_drawdown_warns_even_if_latch_input_false(self):
        result = self.approve(equity=D(950), day_start_equity=D(950))
        self.assertEqual(result.quantity, 0)

    def test_margin_aggregate_and_notional_reservations_each_constrain(self):
        for change in (dict(margin_quantity_cap=D('.001')), dict(other_reserved_risk=D('6.7')),
                       dict(other_reserved_notional=D(840))):
            with self.subTest(change=change):
                self.assertEqual(self.approve(**change).quantity, D('.001'))

    def test_daily_and_drawdown_halts_block_entry(self):
        for change in (dict(daily_halted=True), dict(drawdown_halted=True),
                       dict(equity=D(920), day_start_equity=D(920)), dict(equity=D(980))):
            self.assertEqual(self.approve(**change).reason, 'ENTRY_RISK_HALTED')

    def test_halts_and_invalid_signal_do_not_block_reducing_exit(self):
        state = replace(self.state, purpose='exit', side=-1)
        context = replace(self.context, daily_halted=True, drawdown_halted=True,
                          signal_valid=False, protection_ready=False, mark_price=D(49000))
        result = approve_remaining(state, self.snapshot, context, self.contract, now_ms=3000)
        self.assertEqual(result.quantity, D('.001'))  # Reduce-only min-notional exception.
        context = replace(context, pending_exit_qty=D('.001'))
        self.assertEqual(approve_remaining(state, self.snapshot, context, self.contract, now_ms=3000).quantity, 0)

    def test_stale_future_and_unreconciled_context_fail_closed(self):
        for key in ('observed_ms', 'quote_observed_ms', 'filters_observed_ms'):
            for value in (0, 3001):
                self.assertEqual(self.approve(**{key: value}).reason, 'STALE_CONTEXT')
        self.assertEqual(self.approve(reconciled=False).quantity, 0)

    def test_invalid_decimals_and_types_are_rejected(self):
        for change in (dict(equity=D('NaN')), dict(cycle_spent=D(-1)), dict(reconciled=1),
                       dict(margin_quantity_cap=.1), dict(peak_equity=D(999))):
            with self.assertRaises(ValueError):
                replace(self.context, **change)

    def test_short_sizing_and_crossed_stop(self):
        state = replace(self.state, side=-1)
        context = replace(self.context, position_qty=D('-.001'), stop_price=D(61500))
        result = approve_remaining(state, self.snapshot, context, self.contract, now_ms=3000)
        self.assertEqual(result.quantity, D('.002'))
        self.assertEqual(result.loss_per_btc, D('1615.87156'))
        self.assertEqual(self.approve(stop_price=D(61000)).reason, 'STOP_ALREADY_CROSSED')


class IntegratedPreflightTests(PreflightFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'journal.sqlite'
        self.journal = Journal(self.path)
        self.journal.register(self.state)
        self.exchange = FakeExchange(Path(self.tmp.name) / 'exchange.json')

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def payload(self, status='CANCELED', fill='.001'):
        return dict(symbol='BTCUSDC', clientOrderId=self.state.original_id, side='BUY', origQty='.003',
                    type='LIMIT', reduceOnly=False, positionSide='BOTH', orderId=12, updateTime=3000,
                    status=status, executedQty=fill, avgPrice='60000')

    def advance(self, context=None, **changes):
        return advance_from_query(self.journal, self.payload(**changes), context or self.context, self.contract,
                                  original_id=self.state.original_id, observed_ms=3000, now_ms=3000)

    def authorize(self, command, context=None):
        return authorize_journaled_market(self.journal, command, self.snapshot,
                                          context or self.context, self.contract, now_ms=3000)

    def test_query_to_outbox_timeout_restart_no_duplicate(self):
        action, _ = self.advance()
        self.assertEqual(action.quantity, D('.002'))
        self.exchange.lose_response = True
        self.assertEqual(dispatch_once(self.journal, action.client_id, self.exchange, self.authorize), 'UNCERTAIN')
        self.journal.close()
        self.journal = Journal(self.path)
        self.assertEqual(dispatch_once(self.journal, action.client_id, self.exchange, self.authorize), 'TERMINAL')
        self.assertEqual(self.exchange.read()['submits'], 1)
        self.assertEqual(self.journal.filled_quantity(action.client_id), D('.002'))

    def test_dispatch_rechecks_price_and_blocks_original_quantity(self):
        action, _ = self.advance()
        changed = replace(self.context, worst_entry_price=D(61500))
        status = dispatch_once(self.journal, action.client_id, self.exchange,
                               lambda command: self.authorize(command, changed))
        self.assertEqual(status, 'BLOCKED')
        self.assertEqual(self.exchange.read()['submits'], 0)
        self.assertEqual(self.journal.command(action.client_id).action.quantity, D('.002'))

    def test_stale_risk_can_cancel_but_cannot_create_market(self):
        stale = replace(self.context, quote_observed_ms=0)
        action, _ = self.advance(stale, status='PARTIALLY_FILLED')
        self.assertEqual(action.kind, 'CANCEL_ORIGINAL')
        action, _ = self.advance(stale)
        self.assertEqual(action.kind, 'REFRESH_CONTEXT')
        self.assertEqual(self.journal.state(self.state.original_id).phase, 'CANCEL_REQUESTED')
        action, _ = self.advance()
        self.assertEqual(action.kind, 'MARKET_INTENT')

    def test_fill_during_cancel_uses_final_remainder(self):
        self.advance(status='PARTIALLY_FILLED')
        context = replace(self.context, position_qty=D('.002'), position_risk=D('3.2'))
        action, _ = self.advance(context, fill='.002')
        self.assertEqual(action.quantity, D('.001'))

    def test_wrong_query_identity_and_altered_command_are_rejected(self):
        payload = self.payload() | {'symbol': 'BTCUSDT'}
        with self.assertRaises(ValueError):
            advance_from_query(self.journal, payload, self.context, self.contract,
                               original_id=self.state.original_id, observed_ms=3000, now_ms=3000)
        action, _ = self.advance()
        command = self.journal.command(action.client_id)
        self.assertFalse(self.authorize(replace(command, action=replace(command.action, reduce_only=True))))

    def test_warning_and_halts_survive_recovery_and_restart(self):
        context = replace(self.context, equity=D(920), day_start_equity=D(1000))
        latched = latch_risk(self.journal, context, now_ms=3000)
        self.assertTrue(latched.warning_latched)
        self.assertTrue(latched.drawdown_halted)
        self.assertTrue(latched.daily_halted)
        self.journal.close()
        self.journal = Journal(self.path)
        recovered = latch_risk(self.journal, self.context, now_ms=3000)
        self.assertTrue(recovered.warning_latched)
        self.assertTrue(recovered.drawdown_halted)
        self.assertTrue(recovered.daily_halted)
        self.assertEqual(self.advance()[0].kind, 'NONE')
        self.assertEqual(self.journal.state(self.state.original_id).phase, 'SKIPPED')

    def test_original_terminal_fill_change_blocks_dispatch(self):
        action, _ = self.advance()
        command = self.journal.command(action.client_id)
        changed = replace(self.snapshot, cumulative_fill=D(0))
        self.assertFalse(authorize_journaled_market(self.journal, command, changed,
                                                    self.context, self.contract, now_ms=3000))
