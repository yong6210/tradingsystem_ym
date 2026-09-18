import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_flow_absorption import FlowBoundaries
from app.research.diagnostics.flow_absorption import grid_from_raw as original
from app.research.diagnostics.flow_absorption_v2 import grid_from_raw
from scripts.audit_microstructure_raw_sample import timestamp_ns


class RepairedFlowBoundaries(FlowBoundaries):
    def fixture(self,*args,**kwargs):
        with patch('tests.test_flow_absorption.grid_from_raw',grid_from_raw):
            return super().fixture(*args,**kwargs)

    def test_second_delayed_snapshot_reuses_received_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.fixture(folder);p=folder/'raw'
            rows=p.read_text().splitlines();message=json.loads(rows[0].split(' ',1)[1]);message['data']['lastUpdateId']=39
            rows.append('2024-09-01T00:00:40.5000000Z '+json.dumps(message));rows.sort()
            p.write_text('\n'.join(rows)+'\n');start=timestamp_ns('2024-09-01T00:00:00Z')
            with self.assertRaisesRegex(ValueError,'SNAPSHOT_BRIDGE_MISSING'):
                original(p,start,start+90*10**9,timestamp_ns)
            grid,quality=grid_from_raw(p,start,start+90*10**9,timestamp_ns)
            self.assertEqual(quality['snapshots'],2)
            self.assertEqual(grid[41]['bids'][0],['60000','0.1'])
            self.assertGreaterEqual(grid[41]['quality_reset_ns'],start+40_500_000_000)
            self.assertFalse(grid[89]['valid'])

    def test_uncovered_snapshot_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);self.fixture(folder);p=folder/'raw';rows=p.read_text().splitlines()
            message=json.loads(rows[0].split(' ',1)[1]);message['data']['lastUpdateId']=0
            rows.append('2024-09-01T00:00:40.5000000Z '+json.dumps(message));rows.sort();p.write_text('\n'.join(rows)+'\n')
            start=timestamp_ns('2024-09-01T00:00:00Z')
            with self.assertRaisesRegex(ValueError,'SNAPSHOT_BRIDGE_MISSING'):
                grid_from_raw(p,start,start+90*10**9,timestamp_ns)
