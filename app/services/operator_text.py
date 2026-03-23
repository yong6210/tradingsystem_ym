from __future__ import annotations


_WHY_NOW_MAPPING = {
    "sweep_reversal_limit": "extreme location + rejection + clean limit",
    "sweep_reversal_confirm_only": "extreme location + rejection + confirmation required",
    "sweep_reversal_sweep_confirm": "extreme location + sweep rejection + confirm break",
    "trend_continuation_limit": "trend regime + pullback held + clean continuation",
    "trend_continuation_confirm_only": "trend regime + pullback + confirmation required",
    "range_rotation_research_only": "range regime + reversal signal + research-only",
}

_ENTRY_CONDITION_MAPPING = {
    "limit_on_touch": "limit on touch",
    "touch_then_confirm": "touch then confirm",
    "sweep_then_confirm": "sweep then confirm",
}


def humanize_snake_case(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.replace("_", " ")


def why_now_message(reason: str | None) -> str:
    key = str(reason or "").strip()
    if not key:
        return ""
    return _WHY_NOW_MAPPING.get(key, humanize_snake_case(key))


def entry_condition_message(condition: str | None, *, fallback_entry_model: str | None = None) -> str:
    key = str(condition or "").strip()
    if key:
        return _ENTRY_CONDITION_MAPPING.get(key, humanize_snake_case(key))

    model = str(fallback_entry_model or "").upper()
    if model == "LIMIT":
        return "limit on touch"
    if model == "SWEEP_CONFIRM":
        return "sweep then confirm"
    if model == "CONFIRM":
        return "touch then confirm"
    return ""
