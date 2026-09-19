"""Versioned JSON checkpoints with ledger event replay and restart interlock."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .directional_cycling import DirectionalCycling
from .models import Costs, dec, jsonable


def _digest(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def _state(model):
    return jsonable(dict(direction=model.direction, position_side=model.position_side,
                         quantity=model.quantity, average=model.average,
                         realized_gross=model.realized_gross, net_costs=model.net_costs,
                         position_costs=model.position_costs,
                         reduction=model.reduction,
                         reductions={k: [f, r] for k, (f, r) in model._reductions.items()}))


def checkpoint(controller):
    body = jsonable(dict(version='directional-cycling-1', costs=asdict(controller.costs),
                         events=controller.model.events, state=_state(controller.model),
                         orders={k: asdict(v) for k, v in controller.orders.items()},
                         fills=controller.fills, used_reactions=sorted(controller.used_reactions),
                         locked=controller.locked, transition=controller.transition))
    return dict(body=body, sha256=_digest(body))


def restore(payload):
    from .cycling_orders import CyclingOrder, CyclingOrders
    body = payload['body']
    if payload.get('sha256') != _digest(body) or body.get('version') != 'directional-cycling-1':
        raise ValueError('checkpoint checksum or version mismatch')
    costs = Costs(**body['costs'])
    model = DirectionalCycling(costs.step)
    actions = {'set_direction', 'increase', 'reduce', 'begin_retracement',
               'funding', 'supersede_reduction'}
    for event in body['events']:
        if event['action'] not in actions:
            raise ValueError('unknown ledger event')
        getattr(model, event['action'])(**event['args'])
    if _state(model) != body['state']:
        raise ValueError('checkpoint ledger disagrees with replayed events')
    controller = CyclingOrders(model, costs)
    for key, raw in body['orders'].items():
        data = dict(raw)
        for name in ('quantity', 'filled'):
            data[name] = dec(data[name])
        data['price_cap'] = None if data['price_cap'] is None else dec(data['price_cap'])
        order = CyclingOrder(**data)
        if (key != order.id or not key or order.kind not in ('increase', 'reduce', 'exit') or
                type(order.side) is not int or order.side not in (-1, 1) or
                order.status not in ('open', 'cancel_pending', 'filled', 'cancelled') or
                order.quantity <= 0 or order.quantity % costs.step or order.filled % costs.step or
                not 0 <= order.filled <= order.quantity or
                (order.status == 'filled') != (order.filled == order.quantity)):
            raise ValueError('invalid checkpoint order')
        if order.kind == 'increase':
            if order.price_cap is None or order.price_cap <= 0 or order.event_id is not None:
                raise ValueError('invalid increasing order')
        elif order.price_cap is not None or (order.kind == 'reduce' and order.event_id not in model._reductions):
            raise ValueError('invalid reduction order')
        elif order.kind == 'exit' and order.event_id is not None:
            raise ValueError('invalid exit order')
        controller.orders[key] = order
    active = [o for o in controller.orders.values() if o.status in ('open', 'cancel_pending')]
    if len(active) > 1:
        raise ValueError('multiple active orders in serial controller')
    totals = {k: dec(0) for k in controller.orders}
    for key, raw in body['fills'].items():
        order_id, qty, price, fee = raw
        qty, price, fee = dec(qty), dec(price), dec(fee)
        order = controller.orders[order_id]
        expected = ('increase', order.side, qty, price, fee, None) if order.kind == 'increase' else (
            'reduce', None, qty, price, fee, order.event_id)
        if model._fills.get(key) != expected:
            raise ValueError('order fill disagrees with ledger')
        if order.kind == 'increase' and order.side * (price - order.price_cap) > 0:
            raise ValueError('fill exceeds entry cap')
        controller.fills[key] = (order_id, qty, price, fee)
        totals[order_id] += qty
    if any(totals[k] != o.filled for k, o in controller.orders.items()):
        raise ValueError('order cumulative fill mismatch')
    if active:
        order = active[0]
        if order.kind in ('reduce', 'exit'):
            if order.side != model.position_side or order.remaining > model.quantity:
                raise ValueError('active reduction exceeds position')
            if order.kind == 'reduce' and (model.reduction is None or
                    order.event_id != model.reduction.event_id or
                    order.remaining != model.reduction.remaining):
                raise ValueError('active reduction disagrees with target')
    for item in body['used_reactions']:
        if len(item) != 2 or any(not isinstance(x, str) or not x for x in item):
            raise ValueError('invalid reaction key')
        controller.used_reactions.add(tuple(item))
    if type(body['locked']) is not bool:
        raise ValueError('invalid lock')
    controller.locked = body['locked']
    controller.transition = body['transition']
    if controller.transition is not None:
        # Validate without changing the recovered position or direction history.
        from copy import deepcopy
        deepcopy(model).set_direction(**controller.transition)
    controller.restart_required = True
    return controller


def save_checkpoint(controller, path):
    """Replace a checkpoint only after the new file is flushed to disk."""
    path = Path(path)
    payload = checkpoint(controller)
    restore(payload)  # Validate the complete artifact before replacing anything.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def load_checkpoint(path):
    return restore(json.loads(Path(path).read_text(encoding='utf-8')))
