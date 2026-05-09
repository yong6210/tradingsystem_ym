from __future__ import annotations

from app.core.config import Settings
from app.services.execution_degradation_advisory import ExecutionDegradationAdvisoryService


def test_execution_degradation_advisory_tolerates_malformed_slippage_setting() -> None:
    settings = Settings(_env_file=None)
    settings.auto_trading_max_slippage_bps = "inf"
    service = ExecutionDegradationAdvisoryService(settings=settings)

    thresholds = service._slippage_thresholds()

    assert thresholds["manual_review_slippage_p95_bps"] == 12.0
    assert thresholds["watch_slippage_p95_bps"] == 8.4
