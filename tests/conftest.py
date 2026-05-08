from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

os.environ.setdefault("PYDANTIC_DISABLE_PLUGINS", "1")

import pytest
from sqlalchemy.orm import close_all_sessions


_TEST_ROOT = Path(tempfile.mkdtemp(prefix="trading-pytest-")).resolve()
_TEST_REPORTS = _TEST_ROOT / "reports"
_TEST_DB = _TEST_ROOT / "trading_test.db"


def _configure_test_env() -> None:
    env_overrides = {
        "DATABASE_URL": f"sqlite:///{_TEST_DB}",
        "ENVIRONMENT": "test",
        "VALIDATION_REPORT_DIR": str(_TEST_REPORTS / "validation"),
        "OPERATIONS_CHECKLIST_REPORT_DIR": str(_TEST_REPORTS / "operations"),
        "KILL_CONDITION_AUTOMATION_REPORT_DIR": str(_TEST_REPORTS / "operations" / "kill_condition_automation"),
        "STRATEGY_FAMILY_EDGE_REVIEW_REPORT_DIR": str(_TEST_REPORTS / "validation" / "edge_reviews"),
        "LIVE_ALPHA_OPERATING_REVIEW_REPORT_DIR": str(_TEST_REPORTS / "validation" / "live_alpha_reviews"),
        "REPLAY_EVIDENCE_REVIEW_REPORT_DIR": str(_TEST_REPORTS / "validation" / "replay_evidence_reviews"),
        "EXECUTION_QUALITY_REPORT_DIR": str(_TEST_REPORTS / "execution"),
        "FEATURE_CALIBRATION_REPORT_DIR": str(_TEST_REPORTS / "calibration"),
        "FEATURE_CALIBRATION_SNAPSHOT_DIR": str(_TEST_REPORTS / "calibration" / "snapshots"),
        "PARAMETER_CHANGELOG_PATH": str(_TEST_REPORTS / "params" / "PARAM_CHANGELOG.md"),
        "PARAMETER_SNAPSHOT_DIR": str(_TEST_REPORTS / "params" / "snapshots"),
        "ALERT_METRICS_REPORT_DIR": str(_TEST_REPORTS / "alerts"),
        "PORTFOLIO_BUDGET_REPORT_DIR": str(_TEST_REPORTS / "portfolio"),
        "PAPER_LINEAGE_WATCH_REPORT_DIR": str(_TEST_REPORTS / "operations" / "paper_candidate_watch"),
        "PAPER_LINEAGE_WATCH_LATEST_RUN_FILE": str(
            _TEST_REPORTS / "operations" / "paper_candidate_watch" / "latest_launchd_run.json"
        ),
    }
    for key, value in env_overrides.items():
        os.environ[key] = value


_configure_test_env()


@pytest.fixture(autouse=True)
def _isolate_test_database() -> None:
    import app.core.config as config
    import app.db.models  # noqa: F401
    import app.db.session as session
    from app.db.base import Base

    config.get_settings.cache_clear()
    close_all_sessions()
    Base.metadata.drop_all(bind=session.engine)
    Base.metadata.create_all(bind=session.engine)
    session._initialized = True
    yield
    close_all_sessions()


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ARG001
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
