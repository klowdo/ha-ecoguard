import logging
from datetime import datetime

from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.models.statistics import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant

from .const import CONF_IMPORT_HISTORY, DOMAIN
from .coordinator import EcoguardCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

ENERGY_METADATA = StatisticMetaData(
    mean_type=StatisticMeanType.NONE,
    has_sum=True,
    name="Ecoguard Energy Consumption",
    source=DOMAIN,
    statistic_id=f"{DOMAIN}:energy_consumption",
    unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    unit_class="energy",
)

COST_METADATA = StatisticMetaData(
    mean_type=StatisticMeanType.NONE,
    has_sum=True,
    name="Ecoguard Energy Cost",
    source=DOMAIN,
    statistic_id=f"{DOMAIN}:energy_cost",
    unit_of_measurement="SEK",
    unit_class=None,
)


def _build_energy_statistics(
    entries: list[tuple[datetime, float]],
    start_sum: float = 0.0,
) -> list[StatisticData]:
    accumulated = start_sum
    statistics: list[StatisticData] = []
    for dt, kwh in entries:
        accumulated += kwh
        statistics.append(StatisticData(start=dt, state=kwh, sum=accumulated))
    return statistics


def _build_cost_statistics(
    entries: list[tuple[datetime, float, float]],
    start_sum: float = 0.0,
) -> list[StatisticData]:
    accumulated = start_sum
    statistics: list[StatisticData] = []
    for dt, kwh, rate in entries:
        cost = kwh * rate
        accumulated += cost
        statistics.append(StatisticData(start=dt, state=cost, sum=accumulated))
    return statistics


def _get_last_stat(
    hass: HomeAssistant, statistic_id: str
) -> tuple[datetime | None, float]:
    result = get_last_statistics(hass, 1, statistic_id, False, {"sum", "start"})
    if not result or statistic_id not in result:
        return None, 0.0
    last = result[statistic_id][0]
    return last["start"], last.get("sum", 0.0)


def _import_statistics(hass: HomeAssistant, coordinator: EcoguardCoordinator) -> None:
    try:
        energy_entries = coordinator.historical_entries
        if not energy_entries:
            return

        last_energy_start, last_energy_sum = _get_last_stat(
            hass, f"{DOMAIN}:energy_consumption"
        )
        if last_energy_start is not None:
            energy_entries = [(dt, kwh) for dt, kwh in energy_entries if dt > last_energy_start]

        if energy_entries:
            energy_stats = _build_energy_statistics(energy_entries, start_sum=last_energy_sum)
            async_add_external_statistics(hass, ENERGY_METADATA, energy_stats)

        cost_entries = coordinator.historical_cost_entries
        if cost_entries:
            last_cost_start, last_cost_sum = _get_last_stat(
                hass, f"{DOMAIN}:energy_cost"
            )
            if last_cost_start is not None:
                cost_entries = [(dt, kwh, rate) for dt, kwh, rate in cost_entries if dt > last_cost_start]

            if cost_entries:
                cost_stats = _build_cost_statistics(cost_entries, start_sum=last_cost_sum)
                async_add_external_statistics(hass, COST_METADATA, cost_stats)

        _LOGGER.debug(
            "Imported %d energy and %d cost statistics (incremental)",
            len(energy_entries),
            len(cost_entries) if cost_entries else 0,
        )
    except Exception:
        _LOGGER.exception("Failed to import statistics")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = EcoguardCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    def _on_update():
        if entry.options.get(CONF_IMPORT_HISTORY, True):
            hass.async_add_executor_job(_import_statistics, hass, coordinator)

    coordinator.async_add_listener(_on_update)
    if entry.options.get(CONF_IMPORT_HISTORY, True):
        await hass.async_add_executor_job(_import_statistics, hass, coordinator)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: EcoguardCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
    return unload_ok
