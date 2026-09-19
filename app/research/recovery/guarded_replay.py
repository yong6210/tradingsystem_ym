"""JSONL replay and checkpoint restoration retaining guarded admission.

The journal is authoritative. Use process(), not direct engine mutations, for
any state that must survive a checkpoint. This is an offline synthetic broker.
"""
import hashlib
import json

from .replay import Replay, make_plan
from .guarded_engine import GuardedRecoveryEngine, EntrySubmission
from .entry_assessment import AdmissionPolicy, Reachability
from .evidence import Evidence, TargetEvidence, ZoneEvent, ZoneHistory, timestamp
from .zone_observer import ZoneObserver
from .models import Bar, Costs, Policy, Quote, Zone, dec, jsonable, require_flags
from .exit_execution import ExitExecution
from .add_admission import AddSubmission, ReentrySubmission, ProfitAddSubmission
from .split_admission import SplitSubmission


def make_observer(data):
    data = dict(data)
    h = data.pop("history")
    events = tuple(ZoneEvent(e["id"], e["kind"], Evidence(**e["evidence"])) for e in h["events"])
    history = ZoneHistory(Zone(**h["zone"]), events)
    last = data.pop("last_bar")
    bar = Bar(**last) if last is not None else None
    buffer = dec(data.pop("buffer"))
    side, source, pending = data.pop("side"), data.pop("source"), data.pop("pending_touch_ms")
    if data or type(side) is not int or side not in (-1, 1) or buffer < 0 or not source.strip():
        raise ValueError("invalid serialized observer")
    if pending is not None:
        timestamp(pending)
        if bar is None or pending != bar.end_ms:
            raise ValueError("pending touch must belong to last observed minute")
    if bar is None:
        if len(events) != 1:
            raise ValueError("observed events require a last bar")
    elif (events[0].evidence.recorded_ms > bar.end_ms-60000
          or events[-1].evidence.recorded_ms > bar.received_ms
          or events[-1].evidence.observed_ms > bar.end_ms):
        raise ValueError("observer event/bar time mismatch")
    return ZoneObserver(history, side, buffer, source, bar, pending)


def make_submission(data):
    if data is None:
        return None
    data = dict(data)
    for role in ("support", "target"):
        data[role] = make_observer(data[role])
    contract = data["contract"]
    if contract is not None:
        contract = dict(contract)
        contract["evidence"] = Evidence(**contract["evidence"])
        contract = TargetEvidence(**contract)
    data["contract"] = contract
    reach = data["reach"]
    if reach is not None:
        reach = dict(reach)
        # Retain the embedded binding, rather than silently replacing it with
        # the submitted contract (which would hide mismatched source evidence).
        bound = dict(reach.pop("target"))
        bound["evidence"] = Evidence(**bound["evidence"])
        reach = Reachability(target=TargetEvidence(**bound), **reach)
    data["reach"] = reach
    data["policy"] = AdmissionPolicy(**data["policy"])
    data["context_evidence"] = Evidence(**data["context_evidence"])
    execution = data.get("execution")
    data["execution"] = ExitExecution(**execution) if execution is not None else None
    return EntrySubmission(**data)


def make_add_submission(data, *, reentry=False, profit=False):
    data = dict(data)
    for role in ("support", "target"):
        data[role] = make_observer(data[role])
    data["context"] = Evidence(**data["context"])
    return (ProfitAddSubmission if profit else ReentrySubmission if reentry else AddSubmission)(**data)


def make_split_submission(data):
    data = dict(data)
    for role in ("support", "target"):
        data[role] = make_observer(data[role])
    data["context"] = Evidence(**data["context"])
    return SplitSubmission(**data)


class GuardedReplay(Replay):
    def __init__(self, config):
        # Detach caller-owned structures so later mutation cannot rewrite the
        # checkpoint's policy binding or alter future restoration.
        self.config = json.loads(json.dumps(jsonable(config), allow_nan=False))
        if self.config.get("mode", "no_add") != "no_add":
            raise ValueError("guarded replay supports no_add only")
        self.engine = GuardedRecoveryEngine(self.config["initial_equity"], Costs(**self.config["costs"]),
                                            Policy(**self.config.get("policy", {})))
        self.events = []
        self.fill_sequence = 0
        self.binding = dict(controller="recovery-guarded-v0.7", config_sha256=hashlib.sha256(
            json.dumps(self.config, sort_keys=True, allow_nan=False).encode()).hexdigest())

    def process(self, event):
        event = json.loads(json.dumps(jsonable(event), allow_nan=False))
        if event.get("type") == "split":
            if set(event) - {"type", "quote", "submission", "simulate_fills"}:
                raise ValueError("unknown split fields")
            automatic = event.get("simulate_fills",False)
            require_flags(automatic)
            quote = Quote(**event["quote"])
            result = self.engine.submit_split(quote,make_split_submission(event["submission"]))
            if automatic and getattr(result,"kind",None) == "planned":
                self.match(quote)
            self.events.append(event)
            return self.engine.snapshot()
        if event.get("type") == "continuation_zone":
            if set(event) != {"type", "zone", "time_ms"}:
                raise ValueError("continuation-zone event requires zone and time_ms")
            self.engine.register_continuation_level(Zone(**event["zone"]), event["time_ms"])
            self.events.append(event)
            return self.engine.snapshot()
        if event.get("type") in {"add", "reentry", "profit_add"}:
            if set(event) - {"type", "quote", "submission", "simulate_fills"}:
                raise ValueError("unknown add fields")
            automatic = event.get("simulate_fills", False)
            require_flags(automatic)
            quote = Quote(**event["quote"])
            reentry = event["type"] == "reentry"
            profit = event["type"] == "profit_add"
            method = self.engine.submit_profit_add if profit else self.engine.submit_reentry if reentry else self.engine.submit_add
            result = method(quote, make_add_submission(event["submission"], reentry=reentry, profit=profit))
            if automatic and getattr(result, "kind", None) == "add":
                self.match(quote)
            self.events.append(event)
            return self.engine.snapshot()
        if event.get("type") != "start":
            return super().process(event)
        unknown = set(event) - {"type", "plan", "quote", "submission", "simulate_fills"}
        if unknown:
            raise ValueError(f"unknown guarded start fields: {sorted(unknown)}")
        automatic = event.get("simulate_fills", False)
        require_flags(automatic)
        plan = make_plan(event["plan"])
        quote = Quote(**event["quote"])
        submission = make_submission(event.get("submission"))
        result = self.engine.start(plan, quote, submission=submission)
        if automatic and result["action"] == "plan_accepted":
            self.match(quote)
        self.events.append(event)
        return self.engine.snapshot()
