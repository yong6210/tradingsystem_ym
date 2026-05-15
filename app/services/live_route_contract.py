from __future__ import annotations

from typing import Any


AUTHORITY = "live_candidate_promotion_readiness_is_order_truth"


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", "none", "null", ""}:
        return False
    return bool(default)


def csv_items(raw: Any, *, case: str = "asis") -> list[str]:
    items: list[str] = []
    for value in str(raw or "").split(","):
        item = str(value or "").strip()
        if not item:
            continue
        if case == "upper":
            item = item.upper()
        elif case == "lower":
            item = item.lower()
        if item not in items:
            items.append(item)
    return items


def parse_direction_contract(raw: Any) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for item in str(raw or "").split(","):
        token = str(item or "").strip()
        if not token or ":" not in token:
            continue
        symbol, raw_directions = token.split(":", 1)
        normalized_symbol = str(symbol or "").strip().upper()
        if not normalized_symbol:
            continue
        directions: list[str] = []
        for direction in str(raw_directions or "").replace("/", "|").split("|"):
            normalized_direction = str(direction or "").strip().upper()
            if normalized_direction and normalized_direction not in directions:
                directions.append(normalized_direction)
        if directions:
            mapping[normalized_symbol] = directions
    return mapping


def live_route_contract_from_settings(settings: Any) -> dict[str, Any]:
    execution_mode = str(_enum_value(getattr(settings, "auto_trading_execution_mode", "")) or "").strip().upper()
    if execution_mode == "MICRO_LIVE":
        return {
            "authority": AUTHORITY,
            "execution_mode": execution_mode,
            "symbols": csv_items(getattr(settings, "auto_trading_micro_live_allowed_symbols", ""), case="upper"),
            "strategy_families": csv_items(
                getattr(settings, "auto_trading_micro_live_allowed_families", ""),
                case="lower",
            ),
            "entry_models": csv_items(
                getattr(settings, "auto_trading_micro_live_allowed_entry_models", ""),
                case="upper",
            ),
            "sessions": csv_items(getattr(settings, "auto_trading_micro_live_allowed_sessions", ""), case="lower"),
            "direction_contract": parse_direction_contract(
                getattr(settings, "auto_trading_micro_live_direction_contract", "")
            ),
        }
    if execution_mode == "LIVE":
        return {
            "authority": AUTHORITY,
            "execution_mode": execution_mode,
            "symbols": csv_items(getattr(settings, "auto_trading_allowed_symbols", ""), case="upper"),
            "strategy_families": csv_items(getattr(settings, "auto_trading_allowed_families", ""), case="lower"),
            "entry_models": csv_items(
                getattr(settings, "auto_trading_micro_live_allowed_entry_models", ""),
                case="upper",
            ),
            "sessions": [],
            "direction_contract": {},
        }
    return {
        "authority": AUTHORITY,
        "execution_mode": execution_mode or "UNKNOWN",
        "symbols": [],
        "strategy_families": [],
        "entry_models": [],
        "sessions": [],
        "direction_contract": {},
    }


def live_route_contract_from_readiness(settings: Any, readiness: dict[str, Any] | None) -> dict[str, Any]:
    contract = live_route_contract_from_settings(settings)
    payload = dict(readiness or {})
    readiness_symbols = [
        str(item or "").strip().upper()
        for item in list(payload.get("live_routable_symbols") or [])
        if str(item or "").strip()
    ]
    readiness_families = [
        str(item or "").strip().lower()
        for item in list(payload.get("filter_strategy_families") or [])
        if str(item or "").strip()
    ]
    if readiness_symbols:
        contract["symbols"] = readiness_symbols
    if readiness_families:
        contract["strategy_families"] = readiness_families
    return contract


def row_strategy_family(row: dict[str, Any]) -> str:
    payload = dict(row or {})
    validity = dict(payload.get("validity") or {})
    thesis = dict(payload.get("thesis_fingerprint") or {})
    return str(
        payload.get("strategy_family")
        or validity.get("strategy_family")
        or thesis.get("strategy_family")
        or ""
    ).strip().lower()


def row_entry_model(row: dict[str, Any]) -> str:
    payload = dict(row or {})
    validity = dict(payload.get("validity") or {})
    return str(payload.get("entry_model") or validity.get("entry_model") or "").strip().upper()


def row_direction(row: dict[str, Any]) -> str:
    payload = dict(row or {})
    validity = dict(payload.get("validity") or {})
    return str(payload.get("direction") or validity.get("direction") or "").strip().upper()


def row_session_name(row: dict[str, Any]) -> str:
    payload = dict(row or {})
    session_guidance = dict(payload.get("session_guidance") or {})
    guidance_state = str(session_guidance.get("state") or session_guidance.get("guidance_state") or "").strip().lower()
    if guidance_state == "dead_session" or bool(session_guidance.get("dead_session")):
        return "dead_session"

    operating_lock = dict(payload.get("operating_lock") or {})
    current_session = dict(operating_lock.get("current_session") or {})
    current_session_name = str(current_session.get("name") or "").strip().lower()
    if current_session_name and current_session_name != "inactive":
        return current_session_name

    guidance_session = dict(session_guidance.get("current_session") or {})
    guidance_session_name = str(guidance_session.get("name") or "").strip().lower()
    if guidance_session_name and guidance_session_name != "inactive":
        return guidance_session_name

    if str(session_guidance.get("session_name") or "").strip():
        return str(session_guidance.get("session_name") or "").strip().lower()
    if guidance_state:
        return guidance_state
    if current_session_name:
        return current_session_name
    if guidance_session_name:
        return guidance_session_name

    validity = dict(payload.get("validity") or {})
    validity_guidance_state = str(validity.get("session_guidance_state") or "").strip().lower()
    if validity_guidance_state == "dead_session":
        return "dead_session"
    for key in (
        "session_guidance_session_name",
        "session_guidance_state",
        "generated_session",
        "session_name",
        "session",
    ):
        if str(validity.get(key) or "").strip():
            return str(validity.get(key) or "").strip().lower()
    for key in ("generated_session", "session_name", "session"):
        if str(payload.get(key) or "").strip():
            return str(payload.get(key) or "").strip().lower()
    return ""


def live_route_status(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").strip().upper()
    family = row_strategy_family(row)
    entry_model = row_entry_model(row)
    direction = row_direction(row)
    session_name = row_session_name(row)
    live_symbols = {str(item or "").strip().upper() for item in list(contract.get("symbols") or [])}
    live_families = {str(item or "").strip().lower() for item in list(contract.get("strategy_families") or [])}
    live_entry_models = {str(item or "").strip().upper() for item in list(contract.get("entry_models") or [])}
    live_sessions = {str(item or "").strip().lower() for item in list(contract.get("sessions") or [])}
    direction_contract = dict(contract.get("direction_contract") or {})
    allowed_directions = {
        str(item or "").strip().upper() for item in list(direction_contract.get(symbol) or []) if str(item or "").strip()
    }

    reasons: list[str] = []
    if str(contract.get("execution_mode") or "").upper() not in {"MICRO_LIVE", "LIVE"}:
        reasons.append("execution_mode_not_live")
    if not (symbol and symbol in live_symbols):
        reasons.append("symbol_not_live_routable")
    if not (family and family in live_families):
        reasons.append("strategy_family_not_live_route")
    if live_entry_models and entry_model not in live_entry_models:
        reasons.append("entry_model_not_live_route")
    if allowed_directions and direction not in allowed_directions:
        reasons.append("direction_missing_for_live_route" if not direction else "direction_not_live_route")
    if live_sessions and session_name not in live_sessions:
        reasons.append("session_missing_for_live_route" if not session_name else "session_not_live_route")

    live_routable = not reasons
    return {
        "authority": str(contract.get("authority") or AUTHORITY),
        "execution_mode": str(contract.get("execution_mode") or ""),
        "status": "live_route_candidate" if live_routable else "context_only",
        "live_routable": live_routable,
        "reasons": reasons,
        "symbol": symbol,
        "strategy_family": family,
        "entry_model": entry_model,
        "direction": direction,
        "session_name": session_name,
        "allowed_directions": sorted(allowed_directions),
    }


def attach_live_route_status(row: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    route = live_route_status(enriched, contract)
    enriched["entry_surface_route"] = route
    enriched["live_routable"] = bool(route.get("live_routable"))
    return enriched


def unique_symbols(rows: list[dict[str, Any]]) -> list[str]:
    return [
        symbol
        for symbol in dict.fromkeys(
            str(row.get("symbol") or "").strip().upper()
            for row in rows
            if str(row.get("symbol") or "").strip()
        )
    ]


def portfolio_live_route_context(
    *,
    accepted_candidates: list[dict[str, Any]],
    contract: dict[str, Any],
    accepted_count: int | None = None,
    readiness: dict[str, Any] | None = None,
    filter_direction_contract_to_live_symbols: bool = False,
) -> dict[str, Any]:
    enriched_rows = [attach_live_route_status(row, contract) for row in accepted_candidates]
    live_rows = [row for row in enriched_rows if _safe_bool(row.get("live_routable"))]
    context_rows = [row for row in enriched_rows if not _safe_bool(row.get("live_routable"))]
    resolved_accepted_count = len(enriched_rows) if accepted_count is None else int(accepted_count)
    live_count = len(live_rows)
    context_count = max(resolved_accepted_count - live_count, 0)

    if resolved_accepted_count and live_count == 0:
        message = (
            "Portfolio accepted candidates are context-only for the current live route; "
            "order truth remains live_candidate_promotion_readiness."
        )
        route_value = "portfolio_context_only_no_live_route_candidate"
    elif context_count:
        message = (
            "Some portfolio accepted candidates are outside the current live route; "
            "read live_candidate_promotion_readiness before treating them as order candidates."
        )
        route_value = "portfolio_mixed_route_candidates_require_readiness"
    elif live_count > 0:
        message = "Portfolio accepted candidates align with the current live route contract."
        route_value = "portfolio_route_aligned_candidate_requires_readiness"
    else:
        message = "No portfolio accepted context candidates are visible; wait for a live-route candidate."
        route_value = "no_portfolio_accepted_candidates"

    live_symbols = list(contract.get("symbols") or [])
    direction_contract = dict(contract.get("direction_contract") or {})
    if filter_direction_contract_to_live_symbols:
        live_symbol_set = {str(item or "").strip().upper() for item in live_symbols}
        direction_contract = {
            symbol: list(directions)
            for symbol, directions in sorted(direction_contract.items())
            if symbol in live_symbol_set
        }
    readiness_payload = dict(readiness or {})
    return {
        "authority": AUTHORITY,
        "portfolio_candidates_are_context_only": bool(resolved_accepted_count and live_count == 0),
        "accepted_candidate_count": resolved_accepted_count,
        "live_routable_accepted_candidate_count": live_count,
        "context_only_accepted_candidate_count": context_count,
        "context_only_accepted_symbols": unique_symbols(context_rows),
        "live_routable_accepted_symbols": unique_symbols(live_rows),
        "accepted_candidate_route_statuses": [
            dict(row.get("entry_surface_route") or live_route_status(row, contract)) for row in enriched_rows
        ],
        "active_strategy_families": list(contract.get("strategy_families") or []),
        "active_entry_models": list(contract.get("entry_models") or []),
        "active_sessions": list(contract.get("sessions") or []),
        "active_direction_contract": direction_contract,
        "live_routable_symbols": live_symbols,
        "live_candidate_headline_state": readiness_payload.get("headline_state", ""),
        "live_candidate_headline_reason": readiness_payload.get("headline_reason", ""),
        "live_candidate_headline_scope": readiness_payload.get("headline_scope", ""),
        "approve_value": route_value,
        "approve_reason": message,
        "message": message,
    }
