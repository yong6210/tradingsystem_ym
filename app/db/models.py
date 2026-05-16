from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_candles_symbol_tf_ts"),
        Index("ix_candles_symbol_tf_ts", "symbol", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    o: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)
    l: Mapped[float] = mapped_column(Float, nullable=False)
    c: Mapped[float] = mapped_column(Float, nullable=False)
    v: Mapped[float] = mapped_column(Float, nullable=False)

    source: Mapped[str] = mapped_column(String(30), default="binance")
    is_final: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FundingRateSnapshot(Base):
    __tablename__ = "funding_rates"
    __table_args__ = (
        UniqueConstraint("symbol", "ts", name="uq_funding_rates_symbol_ts"),
        Index("ix_funding_rates_symbol_ts", "symbol", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    funding_rate: Mapped[float] = mapped_column(Float, nullable=False)
    mark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="binance", nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OpenInterestSnapshot(Base):
    __tablename__ = "open_interest"
    __table_args__ = (
        UniqueConstraint("symbol", "period", "ts", name="uq_open_interest_symbol_period_ts"),
        Index("ix_open_interest_symbol_period_ts", "symbol", "period", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_interest: Mapped[float] = mapped_column(Float, nullable=False)
    open_interest_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="binance", nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BasisSnapshot(Base):
    __tablename__ = "basis_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "ts", name="uq_basis_snapshots_symbol_tf_ts"),
        Index("ix_basis_snapshots_symbol_tf_ts", "symbol", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    basis_open: Mapped[float] = mapped_column(Float, nullable=False)
    basis_high: Mapped[float] = mapped_column(Float, nullable=False)
    basis_low: Mapped[float] = mapped_column(Float, nullable=False)
    basis_close: Mapped[float] = mapped_column(Float, nullable=False)
    basis_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(30), default="binance", nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LiquidationEvent(Base):
    __tablename__ = "liquidation_events"
    __table_args__ = (
        UniqueConstraint("symbol", "ts", "side", "price", "qty", name="uq_liquidation_events_identity"),
        Index("ix_liquidation_events_symbol_ts", "symbol", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(30), default="binance", nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MacroEvent(Base):
    __tablename__ = "macro_events"
    __table_args__ = (
        UniqueConstraint("event_code", "event_ts", name="uq_macro_events_code_ts"),
        Index("ix_macro_events_ts", "event_ts"),
        Index("ix_macro_events_code_ts", "event_code", "event_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_code: Mapped[str] = mapped_column(String(40), nullable=False)
    importance: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    country: Mapped[str | None] = mapped_column(String(10), nullable=True)
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CrossAssetBreadthSnapshot(Base):
    __tablename__ = "cross_asset_breadth"
    __table_args__ = (
        UniqueConstraint("leader_symbol", "confirm_symbol", "timeframe", "ts", name="uq_cross_asset_breadth_pair_tf_ts"),
        Index("ix_cross_asset_breadth_pair_tf_ts", "leader_symbol", "confirm_symbol", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    leader_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    confirm_symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, default="15m")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    leader_close: Mapped[float] = mapped_column(Float, nullable=False)
    confirm_close: Mapped[float] = mapped_column(Float, nullable=False)
    leader_ret_1h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confirm_ret_1h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    leader_ret_4h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confirm_ret_4h: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    divergence_bps: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    breadth_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[str] = mapped_column(String(30), default="derived", nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Zone(Base):
    __tablename__ = "zones"
    __table_args__ = (
        Index("ix_zones_symbol_state", "symbol", "state"),
        Index("ix_zones_symbol_created", "symbol", "created_ts"),
    )

    zone_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, default="15m")
    type: Mapped[str] = mapped_column(String(10), nullable=False)

    low: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    mid: Mapped[float] = mapped_column(Float, nullable=False)
    width_atr: Mapped[float] = mapped_column(Float, nullable=False)

    dir_bias: Mapped[str] = mapped_column(String(20), nullable=False)
    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_touched_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    touch_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    base_strength: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    quality: Mapped[float] = mapped_column(Float, default=50.0, nullable=False)
    state: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    merge_group_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), default="v1", nullable=False)


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        Index("ix_plans_symbol_state_valid", "symbol", "state", "valid_until"),
        Index("ix_plans_time_state_valid_from", "timeframe", "state", "valid_until", "valid_from"),
        Index("ix_plans_symbol_time_state_ev", "symbol", "timeframe", "state", "ev", "confidence", "rr_base"),
        Index("ix_plans_zone_id", "zone_id"),
    )

    plan_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    zone_id: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, default="5m")
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    entry_model: Mapped[str] = mapped_column(String(20), nullable=False)

    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    entry_condition: Mapped[str | None] = mapped_column(String(250), nullable=True)
    sl: Mapped[float] = mapped_column(Float, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, nullable=False)
    tp3: Mapped[float] = mapped_column(Float, nullable=False)

    split: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    rr_min: Mapped[float] = mapped_column(Float, nullable=False)
    rr_base: Mapped[float] = mapped_column(Float, nullable=False)
    rr_opt: Mapped[float] = mapped_column(Float, nullable=False)
    ev: Mapped[float] = mapped_column(Float, nullable=False)
    cost_est: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    validity: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="PLANNED")

    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), default="v1", nullable=False)


class ZoneOutcome(Base):
    __tablename__ = "zone_outcomes"
    __table_args__ = (
        Index("ix_outcomes_zone_touch", "zone_id", "touch_ts"),
        Index("ix_outcomes_symbol_entry", "symbol", "entry_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    zone_id: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)

    touch_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_model_used: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)

    sl_price: Mapped[float] = mapped_column(Float, nullable=False)
    tp1: Mapped[float] = mapped_column(Float, nullable=False)
    tp2: Mapped[float] = mapped_column(Float, nullable=False)
    tp3: Mapped[float] = mapped_column(Float, nullable=False)

    mfe_atr: Mapped[float] = mapped_column(Float, nullable=False)
    mae_atr: Mapped[float] = mapped_column(Float, nullable=False)
    mfe_pct: Mapped[float] = mapped_column(Float, nullable=False)
    mae_pct: Mapped[float] = mapped_column(Float, nullable=False)

    hit_1r: Mapped[bool] = mapped_column(Boolean, default=False)
    hit_2r: Mapped[bool] = mapped_column(Boolean, default=False)
    hit_3r: Mapped[bool] = mapped_column(Boolean, default=False)

    sweep_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    sweep_success: Mapped[bool] = mapped_column(Boolean, default=False)

    friction_at_touch: Mapped[float] = mapped_column(Float, nullable=False)
    regime_at_touch: Mapped[float] = mapped_column(Float, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), default="v1", nullable=False)


class AlertSubscription(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_symbol_type", "symbol", "type"),)

    alert_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    plan_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    triggered_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertRetryTask(Base):
    __tablename__ = "alert_retry_queue"
    __table_args__ = (
        Index("ix_alert_retry_queue_status_next_retry", "status", "next_retry_ts"),
        Index("ix_alert_retry_queue_source_channel", "source_alert_id", "channel"),
        Index("ix_alert_retry_queue_dedupe_key", "dedupe_key"),
    )

    task_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_alert_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(140), nullable=False)

    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    target: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    last_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    delivered_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_letter_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExecutionFill(Base):
    __tablename__ = "execution_fills"
    __table_args__ = (
        Index("ix_execution_fills_plan_ts", "plan_id", "fill_ts"),
        Index("ix_execution_fills_symbol_stage", "symbol", "stage"),
    )

    fill_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    stage: Mapped[str] = mapped_column(String(20), nullable=False)

    fill_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    fee: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    from_state: Mapped[str] = mapped_column(String(30), nullable=False)
    to_state: Mapped[str] = mapped_column(String(30), nullable=False)
    state_changed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), default="v1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BinanceOrderLedger(Base):
    __tablename__ = "binance_order_ledger"
    __table_args__ = (
        Index("ix_binance_order_ledger_symbol_status", "symbol", "status"),
        Index("ix_binance_order_ledger_exchange_order_id", "exchange_order_id"),
        Index("ix_binance_order_ledger_plan_id", "plan_id"),
    )

    client_order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    exchange_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    live_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    test_order: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    orig_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    executed_qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_in_force: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    last_event_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_event_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BinancePositionSnapshot(Base):
    __tablename__ = "binance_positions"
    __table_args__ = (
        Index("ix_binance_positions_symbol", "symbol"),
        Index("ix_binance_positions_symbol_side", "symbol", "position_side"),
    )

    position_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    position_side: Mapped[str] = mapped_column(String(10), nullable=False, default="BOTH")
    position_amt: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    break_even_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mark_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    liquidation_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    notional: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    leverage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    margin_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    isolated_wallet: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    update_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OrderIntent(Base):
    __tablename__ = "order_intents"
    __table_args__ = (
        Index("ix_order_intents_plan_created", "plan_id", "created_at"),
        Index("ix_order_intents_symbol_created", "symbol", "created_at"),
        Index(
            "ix_order_intents_family_created_funnel",
            "strategy_family",
            "created_at",
            "symbol",
            "execution_mode",
            "approval_state",
            "submit_decision",
            "decision_reason_code",
        ),
        Index("ix_order_intents_decision", "submit_decision"),
    )

    intent_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy_family: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    approval_state: Mapped[str] = mapped_column(String(30), nullable=False)
    submit_decision: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_reason_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    decision_reason_message: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    thesis_fingerprint: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    session_guidance: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    quality_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    approval_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OrderSubmission(Base):
    __tablename__ = "order_submissions"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_order_submissions_intent"),
        Index("ix_order_submissions_symbol_state", "symbol", "state"),
        Index(
            "ix_order_submissions_live_submitted_funnel",
            "requested_live",
            "submitted_at",
            "intent_id",
            "symbol",
            "state",
        ),
        Index("ix_order_submissions_client_order_id", "client_order_id"),
    )

    submission_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(80), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    submit_status: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    message: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    adapter: Mapped[str] = mapped_column(String(30), nullable=False, default="paper")
    execution_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="PAPER")
    attachments: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    order_type: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    reduce_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requested_live: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SafetyLock(Base):
    __tablename__ = "safety_locks"
    __table_args__ = (
        Index("ix_safety_locks_scope_active", "scope_type", "scope_key", "active"),
        Index("ix_safety_locks_reason_active", "reason_code", "active"),
    )

    lock_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_message: Mapped[str] = mapped_column(String(250), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allow_closes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    lock_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    unlock_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FamilyRolloutPolicy(Base):
    __tablename__ = "family_rollout_policy"
    __table_args__ = (
        Index("ix_family_rollout_policy_live_enabled", "live_enabled"),
    )

    family: Mapped[str] = mapped_column(String(50), primary_key=True)
    live_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_execution_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    max_risk_r: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    allowed_sessions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    min_quality_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(250), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PromotionLifecycleHistory(Base):
    __tablename__ = "promotion_lifecycle_history"
    __table_args__ = (
        Index("ix_promotion_lifecycle_history_family_event_ts", "family", "event_ts"),
        Index("ix_promotion_lifecycle_history_event_type", "event_type"),
        UniqueConstraint("snapshot_hash", name="uq_promotion_lifecycle_history_snapshot_hash"),
    )

    history_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    family: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_from: Mapped[str | None] = mapped_column(String(80), nullable=True)
    state_to: Mapped[str | None] = mapped_column(String(80), nullable=True)
    bias: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    source_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExecutionReconciliationEvent(Base):
    __tablename__ = "execution_reconciliation_events"
    __table_args__ = (
        Index("ix_execution_reconciliation_events_symbol_created", "symbol", "created_at"),
        Index("ix_execution_reconciliation_events_severity", "severity"),
        Index("ix_execution_reconciliation_events_mismatch", "mismatch_type"),
    )

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    mismatch_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    local_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    exchange_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    lock_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    lock_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ValidationTrialRun(Base):
    __tablename__ = "validation_trial_runs"
    __table_args__ = (
        Index("ix_validation_trial_runs_symbol_version", "symbol", "strategy_version"),
        Index("ix_validation_trial_runs_family_created", "parameter_family", "created_at"),
    )

    trial_run_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), nullable=False)
    parameter_family: Mapped[str] = mapped_column(String(50), nullable=False)
    parameter_values: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    selection_rule: Mapped[str | None] = mapped_column(String(80), nullable=True)
    selected_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selection_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_sample_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_of_sample_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_like_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    trial_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_universe_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ValidationTrialFoldScore(Base):
    __tablename__ = "validation_trial_fold_scores"
    __table_args__ = (
        Index("ix_validation_trial_fold_scores_trial_run", "trial_run_id", "fold_id"),
        Index("ix_validation_trial_fold_scores_symbol_version", "symbol", "strategy_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trial_run_id: Mapped[str] = mapped_column(String(80), nullable=False)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), nullable=False)
    fold_id: Mapped[str] = mapped_column(String(40), nullable=False)
    selected_flag: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    selection_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_sample_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    out_of_sample_metric: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ValidationPboDsrSnapshot(Base):
    __tablename__ = "validation_pbo_dsr_snapshots"
    __table_args__ = (
        Index("ix_validation_pbo_dsr_snapshots_symbol_version", "symbol", "strategy_version"),
        Index("ix_validation_pbo_dsr_snapshots_created", "created_at"),
    )

    snapshot_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(30), nullable=False)
    selected_trial_run_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    trial_run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fold_score_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selection_universe_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pbo_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    dsr_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    pbo_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dsr_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    computation_state: Mapped[str] = mapped_column(String(40), default="not_computed", nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyMetric(Base):
    __tablename__ = "strategy_metrics"
    __table_args__ = (
        Index("ix_strategy_metrics_symbol_version", "symbol", "version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[str] = mapped_column(String(30), nullable=False)

    win_rate: Mapped[float] = mapped_column(Float, default=0.0)
    avg_win: Mapped[float] = mapped_column(Float, default=0.0)
    avg_loss: Mapped[float] = mapped_column(Float, default=0.0)
    ev: Mapped[float] = mapped_column(Float, default=0.0)
    p1r: Mapped[float] = mapped_column(Float, default=0.0)
    p2r: Mapped[float] = mapped_column(Float, default=0.0)
    p3r: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SessionImpulseRetestRuntimeAudit(Base):
    __tablename__ = "session_impulse_retest_runtime_audits"
    __table_args__ = (
        Index("ix_sir_runtime_audits_symbol_observed", "symbol", "observed_ts"),
        Index("ix_sir_runtime_audits_observed_symbol_phase_status", "observed_ts", "symbol", "phase", "status"),
        Index("ix_sir_runtime_audits_phase_status", "phase", "status"),
        Index("ix_sir_runtime_audits_plan_observed", "plan_id", "observed_ts"),
    )

    audit_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), nullable=False)
    phase: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(60), nullable=False)
    plan_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    decision_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    observed_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class EventOutbox(Base):
    __tablename__ = "event_outbox"
    __table_args__ = (
        Index("ix_event_outbox_status_next_retry", "status", "next_retry_ts"),
        Index("ix_event_outbox_dedupe_key", "dedupe_key"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    backend: Mapped[str] = mapped_column(String(20), nullable=False, default="memory")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_retry_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
