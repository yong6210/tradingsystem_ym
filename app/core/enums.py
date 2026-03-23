from enum import Enum


class Timeframe(str, Enum):
    M5 = "5m"
    M15 = "15m"


class ZoneType(str, Enum):
    LP = "LP"
    OB = "OB"
    FVG = "FVG"
    FLIP = "FLIP"


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class DirBias(str, Enum):
    SUPPORT = "support"
    RESISTANCE = "resistance"
    NEUTRAL = "neutral"


class ZoneState(str, Enum):
    ACTIVE = "active"
    WEAK = "weak"
    EXPIRED = "expired"


class PlanState(str, Enum):
    PLANNED = "PLANNED"
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    ENTERED = "ENTERED"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class ExecutionFillStage(str, Enum):
    TRIGGERED = "TRIGGERED"
    ENTRY = "ENTRY"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    CLOSED = "CLOSED"


class ExecutionMode(str, Enum):
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    MICRO_LIVE = "MICRO_LIVE"
    LIVE = "LIVE"


class ApprovalState(str, Enum):
    APPROVED_AUTO = "APPROVED_AUTO"
    APPROVED_MANUAL = "APPROVED_MANUAL"
    APPROVED_SHADOW = "APPROVED_SHADOW"
    BLOCKED = "BLOCKED"


class SubmitDecision(str, Enum):
    SUBMIT = "SUBMIT"
    SKIP_MANUAL_ONLY = "SKIP_MANUAL_ONLY"
    SKIP_SHADOW_ONLY = "SKIP_SHADOW_ONLY"
    SKIP_BLOCKED = "SKIP_BLOCKED"
    SKIP_STALE_PLAN = "SKIP_STALE_PLAN"
    SKIP_DUPLICATE = "SKIP_DUPLICATE"
    SKIP_CLOSE_ONLY = "SKIP_CLOSE_ONLY"
    SKIP_RECONCILIATION_LOCK = "SKIP_RECONCILIATION_LOCK"
    SKIP_KILL_SWITCH = "SKIP_KILL_SWITCH"
    SKIP_LIVE_DISABLED = "SKIP_LIVE_DISABLED"
    SKIP_ALREADY_SUBMITTED = "SKIP_ALREADY_SUBMITTED"


class OrderLifecycleState(str, Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class LockScopeType(str, Enum):
    GLOBAL = "GLOBAL"
    SYMBOL = "SYMBOL"
    FAMILY = "FAMILY"
    SESSION = "SESSION"


class LockSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ReconciliationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class ExitReason(str, Enum):
    TARGET_TP1 = "target_tp1"
    TARGET_TP2 = "target_tp2"
    TARGET_TP3 = "target_tp3"
    STOP_LOSS = "stop_loss"
    STRUCTURE_FAILURE = "structure_failure"
    TIME_FAILURE = "time_failure"
    INFORMATION_FAILURE = "information_failure"
    MANUAL_FLATTEN = "manual_flatten"
    RISK_LOCK_FLATTEN = "risk_lock_flatten"
    SESSION_END_FLATTEN = "session_end_flatten"


class EntryModel(str, Enum):
    LIMIT = "LIMIT"
    CONFIRM = "CONFIRM"
    SWEEP_CONFIRM = "SWEEP_CONFIRM"


class RiskGateState(str, Enum):
    OPEN = "OPEN"
    THROTTLED = "THROTTLED"
    CLOSED = "CLOSED"


class StrategyMode(str, Enum):
    A_ONLY = "A_ONLY"
    A_PLUS_B = "A_PLUS_B"
    RESEARCH = "RESEARCH"


class EventStatus(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
    SKIPPED_LATE = "skipped_late"
    DUPLICATE = "duplicate"
