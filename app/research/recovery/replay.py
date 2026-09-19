"""JSON event replay, synthetic quote broker and checksummed offline checkpoints."""
import hashlib
import json
from pathlib import Path

from app.research.observation.checkpoint import seal, unseal
from .engine import RecoveryEngine
from .models import Bar, Costs, Plan, Policy, Quote, Zone, dec, floor_step, jsonable


def make_plan(data):
    data = dict(data)
    data["support"] = Zone(**data["support"])
    data["target"] = Zone(**data["target"])
    return Plan(**data)


class Replay:
    def __init__(self, config):
        self.config = config
        self.engine = RecoveryEngine(config["initial_equity"], Costs(**config["costs"]),
                                     Policy(**config.get("policy", {})), config.get("mode", "confirmed"))
        self.events = []
        self.fill_sequence = 0
        self.binding = {"controller": "recovery-v0.1", "config_sha256": hashlib.sha256(
            json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()}

    def process(self, event):
        data = dict(event)
        kind = data.pop("type")
        e = self.engine
        if kind == "bar":
            e.on_bar(Bar(**data))
        elif kind == "start":
            e.start(make_plan(data["plan"]), Quote(**data["quote"]))
            if data.get("simulate_fills", False):
                self.match(Quote(**data["quote"]))
        elif kind == "quote":
            automatic = data.pop("simulate_fills", False)
            quote = Quote(**data)
            e.on_quote(quote)
            if automatic:
                self.match(quote)
        elif kind == "context":
            for key in ("support", "target"):
                if data.get(key) is not None:
                    data[key] = Zone(**data[key])
            e.set_context(**data)
        elif kind == "fill":
            e.fill(**data)
        elif kind == "cancel_ack":
            e.cancel_ack(**data)
        elif kind == "funding":
            e.funding(**data)
        elif kind == "fault":
            e.fault(**data)
        elif kind == "reconcile":
            e.reconcile(**data)
        elif kind == "heartbeat":
            e.heartbeat(**data)
        else:
            raise ValueError(f"unknown event type {kind}")
        self.events.append(jsonable(event))
        return e.snapshot()

    def match(self, quote):
        """Synthetic fills ONLY. Never assumes an OHLC touch fills a limit order.

        Liquidity is shared across orders. Cancel acknowledgment is immediate in
        this broker; explicit fill/cancel events are used for race scenarios.
        Orders created by a fill callback wait for the next matching invocation.
        """
        e = self.engine
        if not e.connected or not e.ledger:
            return
        if e.locks & {"position_mismatch", "archived_campaign_fill"}:
            return  # Attributed fills would invent a match to an untrusted position.
        remaining = quote.liquidity_qty
        margin_remaining = quote.margin_room_qty
        for o in sorted(list(e.ledger.orders.values()), key=lambda o: o.increasing):
            if o.status == "cancel_pending":
                e.cancel_ack(o.id, quote.time_ms)
                continue
            if not o.active or o.created_ms > quote.time_ms or remaining <= 0:
                continue
            if o.increasing:
                if e._blocked() or not quote.execution_ok or not quote.funding_known:
                    continue
                price = quote.entry(e.plan.side)
                if e.plan.side * (price - o.limit) > 0:
                    continue
                room = max(dec(0), quote.max_total_qty - e.ledger.quantity)
                qty = floor_step(min(o.remaining, remaining, margin_remaining, room), e.costs.step)
                if not e.costs.executable(qty, price):
                    continue
            else:
                price = quote.exit(e.plan.side)
                qty = min(o.remaining, remaining)
                # Synthetic close-position capability handles final dust explicitly.
                if qty < o.remaining:
                    qty = floor_step(qty, e.costs.step)
                if not qty:
                    continue
            self.fill_sequence += 1
            e.fill(f"sim:{self.fill_sequence}", o.id, qty, price, qty * price * e.costs.fee, quote.time_ms)
            remaining -= qty
            if o.increasing:
                margin_remaining -= qty

    def checkpoint(self):
        return seal(dict(events=self.events, snapshot=self.engine.snapshot()), self.binding)

    @classmethod
    def restore(cls, config, envelope, restart_ms):
        replay = cls(config)
        saved = unseal(envelope, replay.binding)
        for event in saved["events"]:
            replay.process(event)
        if replay.engine.snapshot() != saved["snapshot"]:
            raise ValueError("checkpoint replay/state mismatch")
        # Restart cannot silently resume increasing exposure.
        replay.process(dict(type="fault", time_ms=restart_ms, reason="restart"))
        return replay

    def write(self, directory):
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=False)
        rows = [row for ledger in self.engine.archived_ledgers.values() for row in ledger.rows]
        rows += self.engine.ledger.rows if self.engine.ledger else []
        rows.sort(key=lambda row: row["time_ms"])
        for name, data in (("events.jsonl", self.events), ("decisions.jsonl", self.engine.trace), ("ledger.jsonl", rows)):
            (path / name).write_text("".join(json.dumps(jsonable(row), ensure_ascii=False, allow_nan=False) + "\n" for row in data))
        (path / "snapshot.json").write_text(json.dumps(self.engine.snapshot(), indent=2, allow_nan=False) + "\n")
        (path / "checkpoint.json").write_text(json.dumps(self.checkpoint(), indent=2, allow_nan=False) + "\n")
        (path / "config.json").write_text(json.dumps(self.config, indent=2, allow_nan=False) + "\n")
