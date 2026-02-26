import logging
from datetime import datetime

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import EcoguardCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

STATISTIC_ID = f"{DOMAIN}:energy_consumption"

METADATA = StatisticMetaData(
    mean_type=StatisticMeanType.NONE,
    has_sum=True,
    name="Ecoguard Energy Consumption",
    source=DOMAIN,
    statistic_id=STATISTIC_ID,
    unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    unit_class="energy",
)


def _build_statistics(entries: list[tuple[datetime, float]]) -> list[StatisticData]:
    accumulated = 0.0
    statistics: list[StatisticData] = []
    for dt, kwh in entries:
        accumulated += kwh
        statistics.append(StatisticData(start=dt, state=kwh, sum=accumulated))
    return statistics


def _import_statistics(hass: HomeAssistant, coordinator: EcoguardCoordinator) -> None:
    entries = coordinator.historical_entries
    if not entries:
        return
    statistics = _build_statistics(entries)
    async_add_external_statistics(hass, METADATA, statistics)
    _LOGGER.debug("Imported %d statistics entries", len(statistics))


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EcoguardCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    coordinator.async_add_listener(lambda: _import_statistics(hass, coordinator))
    _import_statistics(hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: EcoguardCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
