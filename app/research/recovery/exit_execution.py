"""Explicit trial execution rules; no interpretation of free-form instructions."""
from dataclasses import dataclass
from decimal import Decimal
from .evidence import timestamp
from .models import positive


@dataclass(frozen=True)
class ExitExecution:
    reaction_by_ms: int
    exit_by_ms: int
    reaction_price: Decimal
    residual_stop: Decimal
    timeout_action: str = "exit_all"
    first_response_qty: Decimal | None = None

    def __post_init__(self):
        timestamp(self.reaction_by_ms)
        timestamp(self.exit_by_ms)
        if self.reaction_by_ms > self.exit_by_ms or self.timeout_action != "exit_all":
            raise ValueError("only explicit exit_all with ordered deadlines supported")
        for name in ("reaction_price", "residual_stop"):
            object.__setattr__(self, name, positive(getattr(self, name)))
        if self.first_response_qty is not None:
            object.__setattr__(self, "first_response_qty", positive(self.first_response_qty))
