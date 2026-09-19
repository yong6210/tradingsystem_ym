import copy
import unittest
from app.research.recovery.integration_audit import audit_snapshot
from app.research.recovery.models import jsonable
from tests import test_recovery_split_admission as fixtures


class IndependentAuditTests(unittest.TestCase):
    def setUp(self):
        f = fixtures.SplitTests(); f.setUp(); f.submit(auto=True)
        self.config = f.f.config
        self.snapshot = f.e.snapshot()
        self.trace = copy.deepcopy(f.e.trace)
        self.rows = jsonable(f.e.ledger.rows)

    def audit(self):
        return audit_snapshot(self.config,self.snapshot,self.trace,self.rows)

    def test_correct_pending_and_unsubmitted_accounting(self):
        self.assertEqual(self.audit()["fills"],2)

    def test_cash_tampering_detected(self):
        self.snapshot["cash"] = "10000"
        with self.assertRaises(AssertionError): self.audit()

    def test_lot_quantity_tampering_detected(self):
        next(iter(self.snapshot["lots"].values()))["quantity"] = "999"
        with self.assertRaises(AssertionError): self.audit()

    def test_reservation_tampering_detected(self):
        self.snapshot["guarded_splits"]["unsubmitted_risk"] = "0"
        with self.assertRaises(AssertionError): self.audit()

    def test_declared_schedule_tampering_detected(self):
        self.snapshot["guarded_splits"]["slots"][1]["qty"] = "2"
        with self.assertRaises(AssertionError): self.audit()

    def test_fill_pnl_tampering_detected(self):
        self.rows[-1]["gross"] = "100"
        with self.assertRaises(AssertionError): self.audit()

    def test_fill_before_order_detected(self):
        self.rows[0]["time_ms"] = 0
        with self.assertRaises(AssertionError): self.audit()

    def test_cancel_state_tampering_detected(self):
        next(iter(self.snapshot["orders"].values()))["status"] = "open"
        with self.assertRaises(AssertionError): self.audit()


if __name__ == "__main__": unittest.main()
