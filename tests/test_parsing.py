import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
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

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from custom_components.ecoguard.coordinator import _parse_hourly_rolling, TZ_STOCKHOLM


def _build_hourly_html(hours: list[int], kwh: float = 1.0) -> str:
    rows = ""
    for h in hours:
        rows += f"<tr><td>{h:02d}:00 - {h + 1:02d}:00</td><td>{kwh}</td></tr>\n"
    return f"<table><tbody>{rows}</tbody></table>"


def test_rolling_24h_splits_yesterday_and_today():
    now = datetime(2026, 2, 27, 10, 11, tzinfo=TZ_STOCKHOLM)
    yesterday = now.date() - timedelta(days=1)
    today = now.date()

    hours = list(range(10, 24)) + list(range(0, 10))
    html = _build_hourly_html(hours)

    entries = _parse_hourly_rolling(html, now)

    assert len(entries) == 24

    for dt, kwh in entries:
        if dt.hour >= 10:
            assert dt.date() == yesterday, f"Hour {dt.hour} should be yesterday"
        else:
            assert dt.date() == today, f"Hour {dt.hour} should be today"


def test_rolling_24h_at_midnight():
    now = datetime(2026, 2, 27, 0, 30, tzinfo=TZ_STOCKHOLM)
    yesterday = now.date() - timedelta(days=1)

    hours = list(range(0, 24))
    html = _build_hourly_html(hours)

    entries = _parse_hourly_rolling(html, now)

    assert len(entries) == 24
    for dt, _ in entries:
        assert dt.date() == yesterday


def test_rolling_24h_skips_missing_values():
    now = datetime(2026, 2, 27, 10, 0, tzinfo=TZ_STOCKHOLM)
    html = """<table><tbody>
        <tr><td>10:00 - 11:00</td><td>1,5</td></tr>
        <tr><td>11:00 - 12:00</td><td>-</td></tr>
        <tr><td>00:00 - 01:00</td><td>2,0</td></tr>
    </tbody></table>"""

    entries = _parse_hourly_rolling(html, now)

    assert len(entries) == 2
    assert entries[0][0].hour == 10
    assert entries[0][1] == 1.5
    assert entries[1][0].hour == 0
    assert entries[1][1] == 2.0


def test_empty_table_returns_empty():
    now = datetime(2026, 2, 27, 10, 0, tzinfo=TZ_STOCKHOLM)
    entries = _parse_hourly_rolling("<table></table>", now)
    assert entries == []
