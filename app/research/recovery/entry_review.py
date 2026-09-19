"""Descriptive pre-entry evidence only; no optimized admission threshold."""
import pandas as pd


def review_entry(plan, trade):
    now = pd.to_datetime(plan["created_ms"], unit="ms", utc=True)
    # Minute timestamps denote opens: only preceding complete minutes are usable.
    past = trade.loc[(trade.index >= now - pd.Timedelta(hours=24)) & (trade.index < now)]
    expected = pd.date_range(now - pd.Timedelta(hours=24), periods=1440, freq="min")
    if not past.index.equals(expected):
        raise ValueError("complete contiguous prior 24 hours required")
    reference = float(past.c.iloc[-1])
    side = plan["side"]
    target = float(plan["target"]["low" if side == 1 else "high"])
    distance = side * (target - reference)
    span = float(past.h.max() - past.l.min())
    low, high = float(plan["support"]["low"]), float(plan["support"]["high"])
    touches = past[(past.l <= high) & (past.h >= low)]
    # Today's zone is projected onto old bars for description, not claimed to
    # have existed then. This does not validate historical support reactions.
    context = int(plan["reason"].split("context=")[1].split(";")[0])
    if max(plan[k]["available_ms"] for k in ("support", "target")) > plan["created_ms"]:
        raise ValueError("future zone evidence")
    return dict(plan_id=plan["id"], decision_ms=plan["created_ms"], side=side,
                context=context, aligned=side == context,
                last_closed_price=reference, target_distance_pct=distance / reference * 100,
                prior_24h_range=span, target_to_prior_range=distance / span if span else None,
                last_overlap_close_ms=None if touches.empty else int(touches.index[-1].timestamp()*1000)+60000,
                overlap_minutes=len(touches),
                missing_contract=["zone_lifecycle", "target_horizon", "target_reachability", "intervening_structure"]
                    + ([] if side == context else ["countertrend_exit_contract"]),
                status="UNASSESSED_CONTRACT", reference_kind="last_closed_minute_not_fill")
