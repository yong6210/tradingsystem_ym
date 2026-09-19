"""Reproduce the supplied video's two-cycle arithmetic through offline orders.

All locations, account snapshots and thresholds below are synthetic fixtures,
not calibrated strategy parameters or claims about real market profitability.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.recovery.cycling_admission import Capacity, Location
from app.research.recovery.cycling_orders import CyclingOrders
from app.research.recovery.directional_cycling import DirectionalCycling
from app.research.recovery.evidence import Evidence, ZoneEvent, ZoneHistory
from app.research.recovery.models import Costs, Quote, Zone, jsonable


def replay():
    model = DirectionalCycling('.001')
    orders = CyclingOrders(model, Costs(0, 0, 1, '.001', '.001', 1))
    orders.set_direction(-1, timeframe='4h', observed_ms=0, reason='synthetic 4h short assessment')
    rows = []

    def record(event, mark):
        rows.append(dict(event=event, mark=mark, direction=model.direction,
                         quantity=model.quantity, average=model.average,
                         realized_gross=model.realized_gross,
                         total_pnl=model.total_pnl(mark), break_evens=model.break_evens()))

    for i, (entry, retracement) in enumerate(((100000, None), (102000, 101200), (103000, 102200)), 1):
        now = i * 1000
        key = 'fixture_' + str(i)
        zone = Zone(key, 1, entry-100, entry+100, now-100, 'synthetic location')
        history = ZoneHistory(zone, (
            ZoneEvent(key+'formed', 'formed', Evidence('fixture', now-100, now-100, now-100, 'registered')),
            ZoneEvent(key+'reaction', 'validated', Evidence('fixture', now, now, now, 'synthetic reaction')),
        ))
        location = Location(history, -1, key+'reaction', entry-100, entry+100)
        quote = Quote(now, entry, entry, 10, 10, 10, True, True)
        capacity = Capacity(now, 100000, 50000, 10000, 10, 100000, (2000, 3000))
        assessment = orders.increase(key, location, quote, capacity, requested=5, now_ms=now, max_age_ms=0)
        if not assessment['allowed'] or assessment['quantity'] != 5:
            raise AssertionError('fixture entry rejected')
        orders.fill(key+'fill', key, 5, entry)
        record('increase_' + str(i), entry)
        if retracement is not None:
            reduction = orders.retracement(key+'reduce', key+'retracement', reference_price=retracement)
            orders.fill(key+'reduce_fill', reduction.id, reduction.quantity, retracement)
            record('reduce_' + str(i), retracement)
    assert model.quantity == 5 and model.average == 102000
    assert model.realized_gross == -2000 and model.total_pnl(102200) == -3000
    assert model.break_evens()['campaign'] == 101600
    return dict(kind='synthetic_arithmetic_replay', costs='zero for video comparison',
                parameter_status='fixture only, not approved production limits', rows=rows)


if __name__ == '__main__':
    print(json.dumps(jsonable(replay()), ensure_ascii=False, indent=2))
