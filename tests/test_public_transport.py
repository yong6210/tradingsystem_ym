import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.research.observation.public_transport import PublicRest,ingest,receive_cycle,LIMITS
from app.research.observation.public_paper_store import PublicPaperStore
from tests.test_public_paper import ready,query
from tests.test_causal_intents import WHEN,clock


class PublicTransportTests(unittest.TestCase):
    def test_only_fixed_public_paths_and_symbol_queries_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rest = PublicRest(Path(tmp))
            for path,params in [('/fapi/v1/order',{}),('/fapi/v1/premiumIndex',dict(symbol='ETHUSDT')),
                                ('/fapi/v1/time',dict(signature='forbidden'))]:
                with self.assertRaises(ValueError):rest.get(path,params)
            self.assertEqual(rest.count,0)

    def test_request_budget_checked_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            rest = PublicRest(Path(tmp));rest.count = LIMITS['requests']
            with self.assertRaises(ValueError):rest.get('/fapi/v1/time')

    def test_network_error_is_persisted_and_blocks_entries(self):
        state = ready();binding = {k:state['account'][k] for k in ('costs','risk')}
        class FailedRest:
            def get(self,path,params):
                return dict(request_id='fail',status=503,error='HTTP_503',clock=clock(WHEN+5000)),b'failure'
        with tempfile.TemporaryDirectory() as tmp:
            store = PublicPaperStore(Path(tmp)/'account.sqlite',binding,state)
            ingest(FailedRest(),store,'/fapi/v1/fundingRate',query(state,WHEN+5000))
            self.assertIn('FUNDING_HISTORY',store.state()['faults'])
            self.assertEqual(store.state()['guard']['status'],'BLOCK_NEW_ENTRY')
            store.close()

    def test_cycle_still_requests_exit_quote_after_history_failure(self):
        calls = []
        class Store:
            def state(self):return ready()
        def record(rest,store,path,params):
            calls.append(path)
            return [dict(kind='PUBLIC_REQUEST_FAILED')] if path.endswith('fundingRate') else []
        with patch('app.research.observation.public_transport.ingest',side_effect=record):
            receive_cycle(object(),Store())
        self.assertEqual(calls[-1],'/fapi/v1/ticker/bookTicker')
        self.assertEqual(len(calls),4)


if __name__=='__main__':unittest.main()
