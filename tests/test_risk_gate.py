from app.core.enums import RiskGateState
from app.services.risk_gate import RiskGate, RiskGateInput


def test_risk_gate_closes_on_loss_streak() -> None:
    gate = RiskGate()
    out = gate.evaluate(RiskGateInput(consecutive_losses=5, jump_rate=0.1, api_healthy=True))
    assert out.state == RiskGateState.CLOSED
    assert not out.can_open_new_trade


def test_risk_gate_throttles_on_jump_rate() -> None:
    gate = RiskGate()
    out = gate.evaluate(RiskGateInput(consecutive_losses=0, jump_rate=0.9, api_healthy=True))
    assert out.state == RiskGateState.THROTTLED
    assert not out.can_open_new_trade
