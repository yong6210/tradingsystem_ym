from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.enums import ExecutionFillStage, OrderLifecycleState, PlanState
from app.db.models import OrderSubmission, Plan
from app.db.session import SessionLocal, init_db
from app.services.strategy_engine import StrategyEngine


def _seed_plan(db, *, symbol: str, plan_id: str, direction: str = "long", state: str = "PLANNED") -> Plan:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    plan = Plan(
        plan_id=plan_id,
        zone_id=f"{symbol}_z1",
        symbol=symbol,
        timeframe="5m",
        direction=direction,
        entry_model="CONFIRM",
        entry_price=100.0,
        entry_condition="touch_then_confirm",
        sl=98.5 if direction == "long" else 101.5,
        tp1=101.5 if direction == "long" else 98.5,
        tp2=102.5 if direction == "long" else 97.5,
        tp3=103.5 if direction == "long" else 96.5,
        split={"tp1": 0.6, "tp2": 0.25, "runner": 0.15},
        rr_min=1.2,
        rr_base=1.8,
        rr_opt=2.5,
        ev=0.21,
        cost_est=0.08,
        confidence=0.71,
        validity={
            "meta_reason": "meta_pass",
            "strategy_family": "trend_continuation",
            "reaction_classification": "acceptance_confirmed",
        },
        state=state,
        valid_from=now - timedelta(minutes=30),
        valid_until=now + timedelta(hours=6),
        strategy_version="v1",
    )
    db.add(plan)
    db.commit()
    return plan


def test_ingest_binance_user_stream_order_trade_update_maps_to_entry() -> None:
    init_db()
    symbol = f"BUS{int(datetime.now(timezone.utc).timestamp() * 1_000_000)}USDC"
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_entry_plan", direction="long", state="PLANNED")
        trade_id = int(datetime.now(timezone.utc).timestamp() * 1_000_000)

        engine.binance_order_repo.upsert(
            client_order_id="usr-entry-1",
            exchange_order_id=12345,
            plan_id=plan.plan_id,
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            status="NEW",
            reduce_only=False,
            requested_live=True,
            live_enabled=False,
            test_order=True,
            price=100.0,
            orig_qty=0.01,
            executed_qty=0.0,
            time_in_force="GTC",
            last_event_type="submit",
            last_trade_id=None,
            last_event_ts=datetime.now(timezone.utc),
            raw={"seed": True},
        )
        db.commit()

        engine.market_data.binance.fetch_position_risk = lambda symbol=None: [  # type: ignore[assignment]
            {
                "symbol": symbol or "BTCUSDC",
                "positionSide": "LONG",
                "positionAmt": "0.01",
                "entryPrice": "100.0",
                "breakEvenPrice": "100.1",
                "markPrice": "100.5",
                "liquidationPrice": "50.0",
                "unRealizedProfit": "0.5",
                "notional": "1.005",
                "leverage": "5",
                "marginType": "isolated",
                "isolatedWallet": "10.0",
                "updateTime": 1700000000000,
            }
        ]

        result = engine.ingest_binance_user_stream_event(
            payload={
                "e": "ORDER_TRADE_UPDATE",
                "E": 1700000000000,
                "o": {
                    "s": symbol,
                    "i": 12345,
                    "c": "usr-entry-1",
                    "S": "BUY",
                    "o": "LIMIT",
                    "f": "GTC",
                    "X": "FILLED",
                    "x": "TRADE",
                    "R": False,
                    "ps": "LONG",
                    "l": "0.01",
                    "L": "100.0",
                    "z": "0.01",
                    "q": "0.01",
                    "ap": "100.0",
                    "rp": "0",
                        "t": trade_id,
                },
            }
        )

        assert result["accepted"] is True
        assert result["kind"] == "order_trade_update"
        assert result["plan_id"] == plan.plan_id
        assert result["fill_ingest"] is not None
        assert result["fill_ingest"]["stage"] == "ENTRY"
        assert result["fill_ingest"]["accepted"] is True
        assert result["fill_ingest"]["duplicate"] is False
        assert result["fill_ingest"]["state_changed"] is True
        assert result["position_sync"]["open_positions"] == 1

        db.expire_all()
        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == PlanState.ENTERED.value


def test_ingest_binance_user_stream_malformed_fill_numbers_do_not_crash() -> None:
    init_db()
    symbol = f"BUS{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 9}USDC"
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_bad_fill_plan", direction="long", state="ARMED")

        engine.binance_order_repo.upsert(
            client_order_id="usr-bad-fill-1",
            exchange_order_id=92345,
            plan_id=plan.plan_id,
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            status="NEW",
            reduce_only=False,
            requested_live=True,
            live_enabled=True,
            test_order=False,
            price=100.0,
            orig_qty=0.01,
            executed_qty=0.0,
            time_in_force="GTC",
            last_event_type="submit",
            last_trade_id=None,
            last_event_ts=datetime.now(timezone.utc),
            raw={"seed": True},
        )
        db.commit()
        engine.market_data.binance.fetch_position_risk = lambda symbol=None: []  # type: ignore[assignment]

        result = engine.ingest_binance_user_stream_event(
            payload={
                "e": "ORDER_TRADE_UPDATE",
                "E": "bad-event-ts",
                "o": {
                    "s": symbol,
                    "i": 92345,
                    "c": "usr-bad-fill-1",
                    "S": "BUY",
                    "o": "LIMIT",
                    "f": "GTC",
                    "X": "FILLED",
                    "x": "TRADE",
                    "R": False,
                    "ps": "LONG",
                    "l": "bad-qty",
                    "L": "bad-price",
                    "z": "bad-cumulative",
                    "q": "bad-original",
                    "ap": "bad-average",
                    "rp": "bad-pnl",
                    "t": "bad-trade-id",
                },
            }
        )

        assert result["accepted"] is True
        assert result["fill_ingest"] is None
        assert result["order_snapshot"]["client_order_id"] == "usr-bad-fill-1"

        db.expire_all()
        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == PlanState.ARMED.value


def test_ingest_binance_user_stream_tolerates_malformed_payload_shapes() -> None:
    init_db()
    symbol = f"BUS{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 7}USDC"
    with SessionLocal() as db:
        engine = StrategyEngine(db)

        unknown = engine.ingest_binance_user_stream_event(payload="not-a-dict")
        assert unknown["accepted"] is False
        assert unknown["kind"] == "unknown"

        account = engine.ingest_binance_user_stream_event(
            payload={
                "kind": "account_update",
                "event_type": "ACCOUNT_UPDATE",
                "positions": [
                    ["bad-position"],
                    {
                        "position_key": f"{symbol}:LONG",
                        "symbol": symbol,
                        "position_side": "LONG",
                        "position_amt": 0.01,
                        "entry_price": 100.0,
                        "break_even_price": 100.0,
                        "mark_price": 101.0,
                        "liquidation_price": 50.0,
                        "unrealized_pnl": 0.1,
                        "notional": 1.01,
                        "leverage": 5,
                        "margin_type": "isolated",
                        "isolated_wallet": 10.0,
                        "update_ts": datetime.now(timezone.utc),
                        "raw": {"source": "test"},
                    },
                ],
            }
        )

        assert account["accepted"] is True
        assert account["position_sync"]["synced"] == 1
        assert account["position_sync"]["positions"][0]["position_key"] == f"{symbol}:LONG"


def test_ingest_binance_user_stream_reduce_only_trade_can_close_plan() -> None:
    init_db()
    symbol = f"BUS{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1}USDC"
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_close_plan", direction="long", state="ENTERED")
        trade_id = int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 1

        engine.binance_order_repo.upsert(
            client_order_id="usr-close-1",
            exchange_order_id=22334,
            plan_id=plan.plan_id,
            symbol=symbol,
            side="SELL",
            order_type="TAKE_PROFIT_MARKET",
            status="NEW",
            reduce_only=True,
            requested_live=True,
            live_enabled=True,
            test_order=False,
            price=101.5,
            orig_qty=0.01,
            executed_qty=0.0,
            time_in_force="GTC",
            last_event_type="submit",
            last_trade_id=None,
            last_event_ts=datetime.now(timezone.utc),
            raw={"seed": True},
        )
        db.commit()

        engine.market_data.binance.fetch_position_risk = lambda symbol=None: [  # type: ignore[assignment]
            {
                "symbol": symbol or "BTCUSDC",
                "positionSide": "LONG",
                "positionAmt": "0.0",
                "entryPrice": "0.0",
                "breakEvenPrice": "0.0",
                "markPrice": "101.5",
                "liquidationPrice": "0.0",
                "unRealizedProfit": "0.0",
                "notional": "0.0",
                "leverage": "5",
                "marginType": "isolated",
                "isolatedWallet": "0.0",
                "updateTime": 1700000000000,
            }
        ]

        result = engine.ingest_binance_user_stream_event(
            payload={
                "e": "ORDER_TRADE_UPDATE",
                "E": 1700000005000,
                "o": {
                    "s": symbol,
                    "i": 22334,
                    "c": "usr-close-1",
                    "S": "SELL",
                    "o": "TAKE_PROFIT_MARKET",
                    "f": "GTC",
                    "X": "FILLED",
                    "x": "TRADE",
                    "R": True,
                    "ps": "LONG",
                    "l": "0.01",
                    "L": "101.5",
                    "z": "0.01",
                    "q": "0.01",
                    "ap": "101.5",
                    "rp": "1.5",
                        "t": trade_id,
                },
            }
        )

        assert result["accepted"] is True
        assert result["fill_ingest"] is not None
        assert result["fill_ingest"]["stage"] == "CLOSED"
        assert result["fill_ingest"]["exit_reason"] == "target_tp1"
        assert result["fill_ingest"]["duplicate"] is False
        assert result["fill_ingest"]["state_changed"] is True

        db.expire_all()
        refreshed = db.get(Plan, plan.plan_id)
        assert refreshed is not None
        assert refreshed.state == PlanState.CLOSED.value


def test_ingest_binance_user_stream_skips_duplicate_submit_response_entry_fill() -> None:
    init_db()
    symbol = f"BUS{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_dup_plan", direction="long", state="ARMED")
        trade_id = int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2

        engine.binance_order_repo.upsert(
            client_order_id="usr-dup-1",
            exchange_order_id=32345,
            plan_id=plan.plan_id,
            symbol=symbol,
            side="BUY",
            order_type="MARKET",
            status="FILLED",
            reduce_only=False,
            requested_live=True,
            live_enabled=True,
            test_order=False,
            price=100.0,
            orig_qty=0.01,
            executed_qty=0.01,
            time_in_force="GTC",
            last_event_type="submit",
            last_trade_id=None,
            last_event_ts=datetime.now(timezone.utc),
            raw={"seed": True},
        )
        entry_response = engine.ingest_execution_fill(
            fill_id="binance_submit_32345_filled",
            plan_id=plan.plan_id,
            symbol=plan.symbol,
            stage=ExecutionFillStage.ENTRY,
            fill_ts=datetime.now(timezone.utc),
            price=100.0,
            qty=0.01,
            fee=0.0,
            payload={
                "source": "binance_submit_response",
                "client_order_id": "usr-dup-1",
                "exchange_order_id": "32345",
                "submit_status": "FILLED",
            },
        )
        assert entry_response["accepted"] is True
        db.commit()

        engine.market_data.binance.fetch_position_risk = lambda symbol=None: [  # type: ignore[assignment]
            {
                "symbol": symbol or "BTCUSDC",
                "positionSide": "LONG",
                "positionAmt": "0.01",
                "entryPrice": "100.0",
                "breakEvenPrice": "100.0",
                "markPrice": "100.5",
                "liquidationPrice": "50.0",
                "unRealizedProfit": "0.5",
                "notional": "1.005",
                "leverage": "5",
                "marginType": "isolated",
                "isolatedWallet": "10.0",
                "updateTime": 1700000000000,
            }
        ]

        result = engine.ingest_binance_user_stream_event(
            payload={
                "e": "ORDER_TRADE_UPDATE",
                "E": 1700000007000,
                "o": {
                    "s": symbol,
                    "i": 32345,
                    "c": "usr-dup-1",
                    "S": "BUY",
                    "o": "MARKET",
                    "f": "GTC",
                    "X": "FILLED",
                    "x": "TRADE",
                    "R": False,
                    "ps": "LONG",
                    "l": "0.01",
                    "L": "100.0",
                    "z": "0.01",
                    "q": "0.01",
                    "ap": "100.0",
                    "rp": "0",
                    "t": trade_id,
                },
            }
        )

        assert result["accepted"] is True
        assert result["fill_ingest"] is not None
        assert result["fill_ingest"]["duplicate"] is True
        assert result["fill_ingest"]["reason"] == "submit_response_fill_already_recorded"

        fills = engine.fill_repo.list_for_plans(plan_ids=[plan.plan_id], symbol=plan.symbol)
        assert len(fills) == 1


def test_ingest_binance_user_stream_cancel_updates_submission_state() -> None:
    init_db()
    symbol = f"BUS{int(datetime.now(timezone.utc).timestamp() * 1_000_000) + 2}USDC"
    with SessionLocal() as db:
        engine = StrategyEngine(db)
        plan = _seed_plan(db, symbol=symbol, plan_id=f"{symbol}_cancel_plan", direction="long", state="PLANNED")

        engine.binance_order_repo.upsert(
            client_order_id="usr-cancel-1",
            exchange_order_id=33445,
            plan_id=plan.plan_id,
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            status="NEW",
            reduce_only=False,
            requested_live=True,
            live_enabled=True,
            test_order=False,
            price=100.0,
            orig_qty=0.01,
            executed_qty=0.0,
            time_in_force="GTC",
            last_event_type="submit",
            last_trade_id=None,
            last_event_ts=datetime.now(timezone.utc),
            raw={"seed": True},
        )
        submission = OrderSubmission(
            submission_id=f"sub_{symbol}_cancel",
            intent_id=f"intent_{symbol}_cancel",
            plan_id=plan.plan_id,
            symbol=symbol,
            client_order_id="usr-cancel-1",
            exchange_order_id="33445",
            state=OrderLifecycleState.ACKNOWLEDGED.value,
            submit_status="ACKNOWLEDGED",
            message="seeded live order",
            adapter="binance",
            execution_mode="MICRO_LIVE",
            attachments={},
            side="BUY",
            order_type="LIMIT",
            reduce_only=False,
            requested_live=True,
            raw={"seed": True},
        )
        db.add(submission)
        db.commit()

        engine.market_data.binance.fetch_position_risk = lambda symbol=None: []  # type: ignore[assignment]

        result = engine.ingest_binance_user_stream_event(
            payload={
                "e": "ORDER_TRADE_UPDATE",
                "E": 1700000010000,
                "o": {
                    "s": symbol,
                    "i": 33445,
                    "c": "usr-cancel-1",
                    "S": "BUY",
                    "o": "LIMIT",
                    "f": "GTC",
                    "X": "CANCELED",
                    "x": "CANCELED",
                    "R": False,
                    "ps": "LONG",
                    "l": "0.0",
                    "L": "0.0",
                    "z": "0.0",
                    "q": "0.01",
                    "ap": "0.0",
                    "rp": "0",
                    "t": 0,
                },
            }
        )

        assert result["accepted"] is True
        assert result["fill_ingest"] is None
        assert result["submission_sync"] is not None
        assert result["submission_sync"]["state"] == OrderLifecycleState.CANCELLED.value

        db.expire_all()
        refreshed_submission = db.get(OrderSubmission, submission.submission_id)
        assert refreshed_submission is not None
        assert refreshed_submission.state == OrderLifecycleState.CANCELLED.value
        assert refreshed_submission.submit_status == "CANCELED"
        assert refreshed_submission.cancelled_at is not None
