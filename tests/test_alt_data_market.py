from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Candle
from app.db.models import MacroEvent
from app.db.repositories import BasisSnapshotRepository, CandleRepository, CrossAssetBreadthRepository, FundingRateRepository, MacroEventRepository, OpenInterestRepository
from app.services.alt_data_market import AltDataMarketService


class _FakeFundingRow:
    def __init__(self, symbol: str, ts: datetime, funding_rate: float, mark_price: float | None = None):
        self.symbol = symbol
        self.ts = ts
        self.funding_rate = funding_rate
        self.mark_price = mark_price
        self.raw = {"fundingRate": funding_rate}


class _FakeOIRow:
    def __init__(self, symbol: str, period: str, ts: datetime, open_interest: float, open_interest_value: float):
        self.symbol = symbol
        self.period = period
        self.ts = ts
        self.open_interest = open_interest
        self.open_interest_value = open_interest_value
        self.raw = {"sumOpenInterest": open_interest}


class _FakeBasisRow:
    def __init__(self, symbol: str, interval: str, open_time: datetime, close_value: float):
        self.symbol = symbol
        self.interval = interval
        self.open_time = open_time
        self.basis_open = close_value
        self.basis_high = close_value
        self.basis_low = close_value
        self.basis_close = close_value
        self.raw = [0, str(close_value), str(close_value), str(close_value), str(close_value)]


class _FakeClient:
    def __init__(self) -> None:
        base_ts = datetime(2026, 1, 1, tzinfo=UTC)
        self._funding = [
            _FakeFundingRow("BTCUSDC", base_ts, 0.0001, 100000.0),
            _FakeFundingRow("BTCUSDC", base_ts + timedelta(hours=8), 0.0002, 100100.0),
        ]
        self._oi = [
            _FakeOIRow("BTCUSDC", "15m", base_ts, 12345.0, 999999.0),
            _FakeOIRow("BTCUSDC", "15m", base_ts + timedelta(minutes=15), 12355.0, 1000005.0),
        ]
        self._basis = [
            _FakeBasisRow("BTCUSDC", "15m", base_ts, 0.0005),
            _FakeBasisRow("BTCUSDC", "15m", base_ts + timedelta(minutes=15), 0.0007),
        ]

    def fetch_funding_rates(self, **_: object):
        return list(self._funding)

    def fetch_open_interest_hist(self, **_: object):
        return list(self._oi)

    def fetch_premium_index_klines(self, **_: object):
        return list(self._basis)


class _FakeHttpResponse:
    text = """
    <p>For 2026:</p>
    <ul>
      <li>Tuesday, Notamonth 1, and Wednesday, Notamonth 2, 2026</li>
      <li>Tuesday, June 16, and Wednesday, June 17, 2026</li>
    </ul>
    """

    @staticmethod
    def raise_for_status() -> None:
        return None


class _FakeHttpClient:
    def __init__(self, **_: object) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):  # noqa: ANN001
        return False

    @staticmethod
    def get(_url: str) -> _FakeHttpResponse:
        return _FakeHttpResponse()


def test_alt_data_market_service_backfills_three_series(monkeypatch) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 2, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr("app.services.alt_data_market.datetime", FixedDatetime)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with session_factory() as db:
        candle_repo = CandleRepository(db)
        base_ts = datetime(2026, 1, 1, tzinfo=UTC)
        for idx in range(40):
            ts = base_ts + timedelta(minutes=15 * idx)
            candle_repo.upsert(Candle(symbol="BTCUSDC", timeframe="15m", ts=ts, o=100 + idx, h=101 + idx, l=99 + idx, c=100.5 + idx, v=1000 + idx, source="test", is_final=True))
            candle_repo.upsert(Candle(symbol="ETHUSDC", timeframe="15m", ts=ts, o=200 + idx, h=201 + idx, l=199 + idx, c=200.2 + idx * 0.9, v=2000 + idx, source="test", is_final=True))
        service = AltDataMarketService(
            funding_repo=FundingRateRepository(db),
            open_interest_repo=OpenInterestRepository(db),
            basis_repo=BasisSnapshotRepository(db),
            candle_repo=candle_repo,
            breadth_repo=CrossAssetBreadthRepository(db),
            client=_FakeClient(),
        )
        summary = service.backfill_symbol_alt_data(symbol="BTCUSDC", lookback_days=200)
        breadth_rows = service.backfill_cross_asset_breadth(
            leader_symbol="BTCUSDC",
            confirm_symbol="ETHUSDC",
            timeframe="15m",
            lookback_days=30,
        )
        db.commit()

        assert summary.funding_rows == 2
        assert summary.open_interest_rows == 2
        assert summary.basis_rows == 2
        assert breadth_rows > 0
        assert len(FundingRateRepository(db).list_range(symbol="BTCUSDC", start_ts=datetime(2025, 1, 1, tzinfo=UTC), end_ts=datetime(2027, 1, 1, tzinfo=UTC))) == 2
        assert len(OpenInterestRepository(db).list_range(symbol="BTCUSDC", period="15m", start_ts=datetime(2025, 1, 1, tzinfo=UTC), end_ts=datetime(2027, 1, 1, tzinfo=UTC))) == 2
        assert len(BasisSnapshotRepository(db).list_range(symbol="BTCUSDC", timeframe="15m", start_ts=datetime(2025, 1, 1, tzinfo=UTC), end_ts=datetime(2027, 1, 1, tzinfo=UTC))) == 2
        assert len(CrossAssetBreadthRepository(db).list_range(leader_symbol="BTCUSDC", confirm_symbol="ETHUSDC", timeframe="15m", start_ts=datetime(2025, 1, 1, tzinfo=UTC), end_ts=datetime(2027, 1, 1, tzinfo=UTC))) == breadth_rows


def test_macro_event_backfill_skips_malformed_fomc_dates(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    monkeypatch.setattr("app.services.alt_data_market.httpx.Client", _FakeHttpClient)
    with session_factory() as db:
        macro_repo = MacroEventRepository(db)
        service = AltDataMarketService(
            funding_repo=FundingRateRepository(db),
            open_interest_repo=OpenInterestRepository(db),
            basis_repo=BasisSnapshotRepository(db),
            macro_event_repo=macro_repo,
            client=_FakeClient(),
        )

        rows = service.backfill_macro_events(lookback_days=365)
        db.commit()

        assert rows == 1
        assert db.query(MacroEvent).count() == 1
