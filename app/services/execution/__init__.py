from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "ExecutionCoordinator": ("app.services.execution.coordinator", "ExecutionCoordinator"),
    "ExecutionPlanningService": ("app.services.execution.approval", "ExecutionPlanningService"),
    "ExecutionReconciliationService": ("app.services.execution.reconciliation", "ExecutionReconciliationService"),
    "OrderIntentService": ("app.services.execution.intents", "OrderIntentService"),
    "PaperExecutionAdapter": ("app.services.execution.coordinator", "PaperExecutionAdapter"),
    "RolloutPolicyBootstrap": ("app.services.execution.rollout", "RolloutPolicyBootstrap"),
    "RolloutPolicyService": ("app.services.execution.rollout", "RolloutPolicyService"),
    "SafetyLockService": ("app.services.execution.safety", "SafetyLockService"),
}

__all__ = [
    "ExecutionCoordinator",
    "ExecutionPlanningService",
    "ExecutionReconciliationService",
    "OrderIntentService",
    "PaperExecutionAdapter",
    "RolloutPolicyBootstrap",
    "RolloutPolicyService",
    "SafetyLockService",
]


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
