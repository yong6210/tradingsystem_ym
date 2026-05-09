from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.execution.approval import ExecutionPlanningService
    from app.services.execution.coordinator import ExecutionCoordinator, PaperExecutionAdapter
    from app.services.execution.intents import OrderIntentService
    from app.services.execution.reconciliation import ExecutionReconciliationService
    from app.services.execution.rollout import RolloutPolicyBootstrap, RolloutPolicyService
    from app.services.execution.safety import SafetyLockService

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

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
