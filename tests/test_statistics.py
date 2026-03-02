import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch


@dataclass
class StatisticData:
    start: datetime
    state: float
    sum: float


ha_mock = MagicMock()
for mod in [
    "homeassistant", "homeassistant.components",
    "homeassistant.components.recorder", "homeassistant.components.recorder.models",
    "homeassistant.components.recorder.models.statistics",
    "homeassistant.components.recorder.statistics",
    "homeassistant.config_entries", "homeassistant.const",
    "homeassistant.core", "homeassistant.exceptions",
    "homeassistant.helpers", "homeassistant.helpers.update_coordinator",
]:
    sys.modules.setdefault(mod, ha_mock)

models_mod = sys.modules["homeassistant.components.recorder.models"]
models_mod.StatisticData = StatisticData

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from custom_components.ecoguard.__init__ import (
    _build_cost_statistics,
    _build_energy_statistics,
    _get_last_stat,
    _import_statistics,
)


def _dt(hour: int) -> datetime:
    return datetime(2024, 1, 1, hour, tzinfo=timezone.utc)


def test_build_energy_statistics_from_zero():
    entries = [(_dt(0), 1.0), (_dt(1), 2.0), (_dt(2), 3.0)]
    stats = _build_energy_statistics(entries)
    sums = [s.sum for s in stats]
    assert sums == [1.0, 3.0, 6.0]


def test_build_energy_statistics_with_start_sum():
    entries = [(_dt(3), 1.5), (_dt(4), 2.5)]
    stats = _build_energy_statistics(entries, start_sum=10.0)
    sums = [s.sum for s in stats]
    assert sums == [11.5, 14.0]


def test_build_cost_statistics_from_zero():
    entries = [(_dt(0), 2.0, 0.5), (_dt(1), 3.0, 1.0)]
    stats = _build_cost_statistics(entries)
    sums = [s.sum for s in stats]
    assert sums == [1.0, 4.0]


def test_build_cost_statistics_with_start_sum():
    entries = [(_dt(0), 2.0, 0.5)]
    stats = _build_cost_statistics(entries, start_sum=5.0)
    assert stats[0].sum == 6.0


def test_get_last_stat_no_data():
    hass = MagicMock()
    with patch("custom_components.ecoguard.__init__.get_last_statistics", return_value={}):
        start, total = _get_last_stat(hass, "ecoguard:energy_consumption")
    assert start is None
    assert total == 0.0


def test_get_last_stat_with_data():
    hass = MagicMock()
    stat_id = "ecoguard:energy_consumption"
    mock_result = {stat_id: [{"start": _dt(5), "sum": 42.0}]}
    with patch("custom_components.ecoguard.__init__.get_last_statistics", return_value=mock_result):
        start, total = _get_last_stat(hass, stat_id)
    assert start == _dt(5)
    assert total == 42.0


def test_import_statistics_first_run():
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.historical_entries = [(_dt(0), 1.0), (_dt(1), 2.0)]
    coordinator.historical_cost_entries = [(_dt(0), 1.0, 0.5)]

    with patch("custom_components.ecoguard.__init__.get_last_statistics", return_value={}), \
         patch("custom_components.ecoguard.__init__.async_add_external_statistics") as mock_add:
        _import_statistics(hass, coordinator)

    assert mock_add.call_count == 2
    energy_stats = mock_add.call_args_list[0][0][2]
    assert [s.sum for s in energy_stats] == [1.0, 3.0]


def test_import_statistics_incremental():
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.historical_entries = [(_dt(0), 1.0), (_dt(1), 2.0), (_dt(2), 3.0)]
    coordinator.historical_cost_entries = []

    energy_id = "ecoguard:energy_consumption"
    last_stats = {energy_id: [{"start": _dt(1), "sum": 10.0}]}

    with patch("custom_components.ecoguard.__init__.get_last_statistics", return_value=last_stats), \
         patch("custom_components.ecoguard.__init__.async_add_external_statistics") as mock_add:
        _import_statistics(hass, coordinator)

    assert mock_add.call_count == 1
    energy_stats = mock_add.call_args_list[0][0][2]
    assert len(energy_stats) == 1
    assert energy_stats[0].sum == 13.0
    assert energy_stats[0].state == 3.0


def test_import_statistics_no_new_entries():
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.historical_entries = [(_dt(0), 1.0), (_dt(1), 2.0)]
    coordinator.historical_cost_entries = []

    energy_id = "ecoguard:energy_consumption"
    last_stats = {energy_id: [{"start": _dt(1), "sum": 10.0}]}

    with patch("custom_components.ecoguard.__init__.get_last_statistics", return_value=last_stats), \
         patch("custom_components.ecoguard.__init__.async_add_external_statistics") as mock_add:
        _import_statistics(hass, coordinator)

    mock_add.assert_not_called()
