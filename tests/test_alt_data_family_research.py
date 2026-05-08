from sqlalchemy import create_engine

from app.services.alt_data_family_research import inspect_alt_data_feasibility


def test_alt_data_family_feasibility_marks_missing_tables_as_blocked() -> None:
    engine = create_engine("sqlite:///:memory:")
    payload = inspect_alt_data_feasibility(bind=engine)
    assert payload["datasets"]["funding_rate"]["available"] is False
    assert payload["families"]["funding_oi_squeeze_reversal"]["decision"] == "BLOCKED_MISSING_DATA"
    assert "funding_rate" in payload["families"]["funding_oi_squeeze_reversal"]["missing_datasets"]
