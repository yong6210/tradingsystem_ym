"""Historical adapter contracts, independent of the August outcome sample."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

import pandas as pd

from app.research.diagnostics.multiscale_profile import Zone
from app.research.recovery.historical import common_candidate, proxy_quote, costs_for, simulate_episode, select_plans
from app.research.recovery.models import dec

CONFIG = json.loads((Path(__file__).resolve().parents[1] / "configs/research/recovery_historical_v01.json").read_text())


def values():
    return dict(decision=1, daily=1, four_hour=-1, hour=1, quarter=1, atr=.2,
        b_l=100.8, b_h=102.5, b_c=102, b_o=100.9, b_previous_close=100.9,
        m_c=102, m_o=101.8, m_previous_close=101.6, m_previous_high=101.7,
        m_previous_low=101.5, h_close=103, h_previous_close=103, anchor_ms=float("nan"))


def fixture():
    start = pd.Timestamp("2026-08-01T01:01Z")
    ts = int(start.timestamp()*1000)
    zones = [Zone(100,101,100.5,.5,"week"), Zone(110,111,110.5,.3,"day")]
    config = {**CONFIG, "observation_hours": 1}
    plan, reason = common_candidate(ts, values(), zones, ts-60000, 102.2, 10000, config)
    assert reason == "eligible", reason
    index = pd.date_range(start-pd.Timedelta(minutes=48), periods=108, freq="min")
    trade = pd.DataFrame(dict(o=102.2, h=102.4, l=102.1, c=102.2, v=10000.), index=index)
    f = pd.DataFrame([values() for _ in index], index=index)
    return plan, trade, f, config


class HistoricalRecoveryTests(unittest.TestCase):
    def test_candidate_requires_causal_profile(self):
        plan, _, _, config = fixture()
        with self.assertRaisesRegex(ValueError, "not yet available"):
            common_candidate(plan.created_ms, values(), [Zone(100,101,100.5,.5,"week"),Zone(110,111,110.5,.3,"day")],
                             plan.created_ms, 102.2, 10000, config)

    def test_same_initial_price_and_qty_for_all_three_policies(self):
        plan, trade, f, config = fixture()
        rows = [simulate_episode(trade, trade, f, [], plan, config, mode, "base")[0]
                for mode in ("no_add", "confirmed", "planned")]
        self.assertEqual(len({r["initial_qty"] for r in rows}), 1)
        self.assertEqual(len({r["initial_price"] for r in rows}), 1)
        self.assertTrue(all(r["right_censored"] for r in rows))

    def test_right_censor_does_not_force_time_exit(self):
        plan, trade, f, config = fixture()
        r, ledger, _, _ = simulate_episode(trade, trade, f, [], plan, config, "no_add", "base")
        self.assertTrue(r["right_censored"])
        self.assertEqual(len([x for x in ledger if x["type"] == "fill"]), 1)
        self.assertNotEqual(dec(r["cash_pnl"]), dec(r["net_liquidation_pnl"]))

    def test_future_minutes_do_not_change_first_fill(self):
        plan, trade, f, config = fixture()
        a = simulate_episode(trade, trade, f, [], plan, config, "confirmed", "base")
        changed = trade.copy()
        changed.iloc[-10:, changed.columns.get_indexer(["o","h","l","c"])] = [98,99,97,98]
        b = simulate_episode(changed, changed, f, [], plan, config, "confirmed", "base")
        self.assertEqual(a[1][0], b[1][0])

    def test_funding_at_initial_timestamp_excluded(self):
        plan, trade, f, config = fixture()
        funding = [dict(fundingTime=plan.created_ms, markPrice="102.2", fundingRate="0.001")]
        a = simulate_episode(trade, trade, f, funding, plan, config, "no_add", "base")
        self.assertFalse(any(x["type"]=="funding" for x in a[1]))

    def test_funding_inside_minute_and_final_minute_included(self):
        plan, trade, f, config = fixture()
        funding = [dict(fundingTime=plan.created_ms+offset, markPrice="102.2", fundingRate="0.001")
                   for offset in (30000, 3590000)]
        r, ledger, _, _ = simulate_episode(trade, trade, f, funding, plan, config, "no_add", "base")
        entries = [x for x in ledger if x["type"]=="funding"]
        self.assertEqual(len(entries), 2)
        self.assertTrue(all(dec(x["amount"])==plan.initial_qty*dec("102.2")*dec("0.001") for x in entries))
        without = simulate_episode(trade, trade, f, [], plan, config, "no_add", "base")[0]
        self.assertEqual(dec(without["net_liquidation_pnl"])-dec(r["net_liquidation_pnl"]), sum(dec(x["amount"]) for x in entries))

    def test_volume_capacity_does_not_use_current_bar_volume(self):
        c = costs_for(CONFIG, "base")
        q = proxy_quote(1, 100, 5, dec(10000), dec(0), c, CONFIG)
        self.assertEqual(q.liquidity_qty, dec("0.05"))

    def test_ohlc_touch_is_not_limit_fill(self):
        plan, trade, f, config = fixture()
        # Touch pending split prices, while every later open remains above limits.
        trade.loc[trade.index >= pd.to_datetime(plan.created_ms,unit="ms",utc=True), "l"] = 100.7
        r, ledger, _, _ = simulate_episode(trade, trade, f, [], plan, config, "planned", "base")
        self.assertEqual(r["planned_fills"], 0)
        self.assertFalse(any(x.get("kind")=="planned" for x in ledger))

    def test_stop_observation_fills_on_next_open_not_past_stop_price(self):
        plan, trade, f, config = fixture()
        start = pd.to_datetime(plan.created_ms,unit="ms",utc=True)
        trade.loc[start+pd.Timedelta(minutes=1), ["o","h","l","c"]] = [102.2,102.4,99,99.5]
        trade.loc[start+pd.Timedelta(minutes=2), ["o","h","l","c"]] = [98,99,97,98]
        r, ledger, _, _ = simulate_episode(trade, trade, f, [], plan, config, "no_add", "base")
        exit_fill = next(x for x in ledger if x.get("kind")=="reduce")
        self.assertEqual(exit_fill["time_ms"], plan.created_ms + 120001)
        self.assertLess(dec(exit_fill["price"]), dec(98))
        self.assertEqual(dec(r["remaining_qty"]), 0)

    def test_missing_window_rejected(self):
        plan, trade, f, config = fixture()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            simulate_episode(trade.iloc[:-1], trade, f, [], plan, config, "no_add", "base")

    def test_shared_plan_is_not_mutated_by_policy(self):
        plan, trade, f, config = fixture()
        splits = plan.splits
        simulate_episode(trade, trade, f, [], plan, config, "no_add", "base")
        self.assertEqual(plan.splits, splits)
        self.assertEqual(len(splits), 2)

    def test_stress_proxy_has_worse_execution_price(self):
        a = proxy_quote(1,100000,1000,dec(10000),dec(0),costs_for(CONFIG,"base"),CONFIG)
        b = proxy_quote(1,100000,1000,dec(10000),dec(0),costs_for(CONFIG,"stress"),CONFIG)
        self.assertGreater(b.ask,a.ask)
        self.assertLess(b.bid,a.bid)

    def test_funding_at_same_timestamp_as_split_uses_pre_fill_quantity(self):
        plan, trade, f, config = fixture()
        when = pd.to_datetime(plan.created_ms+60000,unit="ms",utc=True)
        trade.loc[when,["o","h","l","c"]] = [100.5,100.8,100.4,100.6]
        event = dict(fundingTime=plan.created_ms+60001,markPrice="100.5",fundingRate="0.001")
        _, ledger, _, _ = simulate_episode(trade,trade,f,[event],plan,config,"planned","base")
        entry = next(x for x in ledger if x["type"]=="funding")
        self.assertEqual(dec(entry["amount"]),plan.initial_qty*dec("100.5")*dec("0.001"))
        same = [x for x in ledger if x["time_ms"]==event["fundingTime"]]
        self.assertEqual(same[0]["type"],"funding")
        self.assertTrue(any(x.get("kind")=="planned" for x in same))

    def test_funding_at_exact_first_fill_timestamp_excluded(self):
        plan,trade,f,config=fixture()
        event=dict(fundingTime=plan.created_ms+1,markPrice="102.2",fundingRate="0.001")
        _,ledger,_,_=simulate_episode(trade,trade,f,[event],plan,config,"no_add","base")
        self.assertFalse(any(x["type"]=="funding" for x in ledger))


if __name__ == "__main__":
    unittest.main()
