from decimal import Decimal as D
import unittest
from app.research.execution.binance_contract import Contract, parse_query

class ContractTests(unittest.TestCase):
    def setUp(self):
        # Tests use an explicit small fixture, not a network response or account.
        self.raw = dict(symbol='BTCUSDC', contractType='PERPETUAL', marginAsset='USDC', status='TRADING', filters=[
            dict(filterType='LOT_SIZE', minQty='.001', maxQty='800', stepSize='.001'),
            dict(filterType='MARKET_LOT_SIZE', minQty='.001', maxQty='50', stepSize='.001'),
            dict(filterType='PRICE_FILTER', minPrice='.1', maxPrice='500000', tickSize='.1'),
            dict(filterType='MIN_NOTIONAL', notional='50'),
            dict(filterType='PERCENT_PRICE', multiplierDown='.95', multiplierUp='1.05')])
        self.contract = Contract(self.raw)
        self.args = dict(order_type='MARKET', side='BUY', quantity='.001', mark_price='60000')

    def test_valid_market(self):
        self.assertEqual(self.contract.check(**self.args), D('.001'))

    def test_market_limit_distinction(self):
        with self.assertRaises(ValueError): self.contract.check(**dict(self.args, quantity='50.001'))
        self.contract.check(**dict(self.args, quantity='50.001', order_type='LIMIT', price='60000'))

    def test_qty_notional_and_nonfinite(self):
        for updates in (dict(quantity='.0011'), dict(quantity='.0001'), dict(mark_price='49000'), dict(quantity='NaN'), dict(quantity=.001)):
            with self.assertRaises(ValueError): self.contract.check(**dict(self.args, **updates))

    def test_reduce_only_dust_requires_position(self):
        args = dict(self.args, side='SELL', mark_price='49000', reduce_only=True, position_quantity='.001')
        self.contract.check(**args)
        for updates in (dict(position_quantity='0'), dict(position_quantity='-.001'), dict(quantity='.002'), dict(position_mode='UNKNOWN')):
            with self.assertRaises(ValueError): self.contract.check(**dict(args, **updates))

    def test_price_tick_and_percent(self):
        for price in ('60000.01', '63000.1'):
            with self.assertRaises(ValueError): self.contract.check(**dict(self.args, order_type='LIMIT', price=price))

    def test_required_filter_missing_duplicate(self):
        for filters in (self.raw['filters'][:-1], self.raw['filters'] + [self.raw['filters'][0]]):
            with self.assertRaises(ValueError): Contract(dict(self.raw, filters=filters))


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.args = dict(client_id='abc', side='BUY', quantity='.002', order_type='MARKET', reduce_only=False, observed_ms=2000)
        self.payload = dict(symbol='BTCUSDC', clientOrderId='abc', side='BUY', origQty='.002', type='MARKET', reduceOnly=False,
                            positionSide='BOTH', orderId=123, updateTime=1000, status='PARTIALLY_FILLED', executedQty='.001', avgPrice='60000')

    def test_partial_and_same_time_are_not_sequence(self):
        a = parse_query(self.payload, **self.args)
        b = parse_query(dict(self.payload, executedQty='.002', status='FILLED'), **self.args)
        self.assertEqual(a.exchange_updated_ms, b.exchange_updated_ms)
        self.assertFalse(hasattr(a, 'sequence'))
        self.assertNotEqual(a.executed, b.executed)

    def test_identity_mismatch(self):
        for key, value in [('symbol','BTCUSDT'), ('clientOrderId','other'), ('origQty','.003'), ('positionSide','LONG'), ('reduceOnly','false')]:
            with self.assertRaises(ValueError): parse_query(dict(self.payload, **{key:value}), **self.args)

    def test_ack_or_test_not_fill_evidence(self):
        for payload in ({}, {'code':200, 'msg':'success'}, {'orderId':123}):
            with self.assertRaises((ValueError, KeyError)): parse_query(payload, **self.args)

    def test_status_consistency(self):
        for updates in (dict(status='FILLED'), dict(status='NEW'), dict(executedQty='.003'), dict(avgPrice='NaN'), dict(status='TEST_ACCEPTED')):
            with self.assertRaises(ValueError): parse_query(dict(self.payload, **updates), **self.args)

    def test_stp_expiry_is_terminal(self):
        self.assertEqual(parse_query(dict(self.payload,status='EXPIRED_IN_MATCH'), **self.args).status, 'EXPIRED')
