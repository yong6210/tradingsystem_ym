import csv
import io
from datetime import UTC, datetime
from zipfile import ZipFile

import pytest

from scripts.prepare_local_kline_archives import HEADER, _parse_row, prepare_archives
from scripts.run_market_state_rotation_v6_backtest import _load_local_bars


def _row(ts):
    return [str(ts), '100', '102', '99', '101', '2', str(ts + 59999), '202', '1', '1', '101', '0']


def _archive(tmp_path, rows):
    path = tmp_path / 'BTCUSDT-1m-2025-02.zip'
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(HEADER)
    writer.writerows(rows)
    with ZipFile(path, 'w') as z:
        z.writestr(path.stem + '.csv', output.getvalue())
    return path


def test_complete_month_aggregates_without_future_or_partial_bars(tmp_path):
    start = int(datetime(2025, 2, 1, tzinfo=UTC).timestamp() * 1000)
    source = _archive(tmp_path, (_row(start + i * 60000) for i in range(28 * 1440)))
    destination = tmp_path / 'result'
    report = prepare_archives([source], destination)
    assert report['status'] == 'PASS'
    assert report['unique_minutes'] == 40320
    bars = _load_local_bars(destination, 'BTCUSDT', '5m')
    assert len(bars) == 8064
    assert bars[0].v == 10
    assert bars[0].o == 100 and bars[0].c == 101
    assert bars[0].open_ms == start
    target = destination / 'BTCUSDT_5m.json'
    target.write_text('{}')
    with pytest.raises(ValueError, match='checksum'):
        _load_local_bars(destination, 'BTCUSDT', '5m')
    with pytest.raises(ValueError, match='already exists'):
        prepare_archives([source], destination)


def test_invalid_month_cannot_be_used_for_replay(tmp_path):
    start = int(datetime(2025, 2, 1, tzinfo=UTC).timestamp() * 1000)
    rows = [_row(start), _row(start), _row(start + 120000)]
    report = prepare_archives([_archive(tmp_path, rows)], tmp_path / 'result')
    assert report['status'] == 'FAIL'
    assert report['errors']['duplicate_open_time'] == 1
    assert report['errors']['missing_minutes'] == 1
    assert not (tmp_path / 'result' / 'BTCUSDT_5m.json').exists()
    with pytest.raises(ValueError, match='not validated'):
        _load_local_bars(tmp_path / 'result', 'BTCUSDT', '5m')


def test_microsecond_archive_timestamps_are_normalized():
    row = _row(1738368000000)
    row[0] = str(int(row[0]) * 1000)
    row[6] = str((int(row[6]) + 1) * 1000 - 1)
    ts, values, unit = _parse_row(row)
    assert ts == 1738368000000
    assert unit == 'microseconds'
    assert values[3] == 101


@pytest.mark.parametrize('index,value', [(1, 'NaN'), (2, '90'), (5, '-1'), (9, '3'), (6, '0')])
def test_invalid_archive_rows_are_rejected(index, value):
    row = _row(1738368000000)
    row[index] = value
    with pytest.raises(ValueError):
        _parse_row(row)


def test_local_feature_loading_never_fetches_remote_data(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import scripts.run_market_state_rotation_v6_backtest as backtest
    start = int(datetime(2025, 2, 1, tzinfo=UTC).timestamp() * 1000)
    source = _archive(tmp_path, (_row(start + i * 60000) for i in range(28 * 1440)))
    destination = tmp_path / 'result'
    prepare_archives([source], destination)
    def unexpected(*args, **kwargs):
        pytest.fail('offline replay must not fetch remote data or load live settings')
    monkeypatch.setattr(backtest, '_load_bars', unexpected)
    monkeypatch.setattr(backtest, 'get_settings', unexpected)
    args = SimpleNamespace(local_data_dir=str(destination), symbol='BTCUSDT', days=28,
        load_days=28, exec_interval='5m', scenario_intervals='1h,4h',
        cache_dir=str(tmp_path / 'unused'), sleep_seconds=0)
    features, scenarios, mappings, metadata = backtest._load_feature_sets(args)
    assert len(features.bars) == 8064
    assert metadata['data_source'] == 'validated_local_archives'
    assert len(scenarios['1h'].bars) == 672
    assert len(mappings['1h']) == 8064
    assert not (tmp_path / 'unused').exists()
