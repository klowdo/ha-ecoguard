from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EcoguardCoordinator


@dataclass(frozen=True, kw_only=True)
class EcoguardSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict], float | str | None] = lambda data: None


def _month_sensors() -> list[EcoguardSensorDescription]:
    sensors: list[EcoguardSensorDescription] = []
    for i in range(1, 13):
        sensors.extend([
            EcoguardSensorDescription(
                key=f"month_{i}_name",
                translation_key=f"month_{i}_name",
                value_fn=lambda data, idx=i: data.get(f"month_{idx}_name"),
            ),
            EcoguardSensorDescription(
                key=f"month_{i}_kwh",
                translation_key=f"month_{i}_kwh",
                native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
                device_class=SensorDeviceClass.ENERGY,
                suggested_display_precision=1,
                value_fn=lambda data, idx=i: data.get(f"month_{idx}_kwh"),
            ),
            EcoguardSensorDescription(
                key=f"month_{i}_cost",
                translation_key=f"month_{i}_cost",
                native_unit_of_measurement="SEK",
                device_class=SensorDeviceClass.MONETARY,
                suggested_display_precision=2,
                value_fn=lambda data, idx=i: data.get(f"month_{idx}_cost"),
            ),
        ])
    return sensors


SENSOR_DESCRIPTIONS: list[EcoguardSensorDescription] = [
    *_month_sensors(),
    EcoguardSensorDescription(
        key="current_month_total_kwh",
        translation_key="current_month_total_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("current_month_total_kwh"),
    ),
    EcoguardSensorDescription(
        key="current_month_day_count",
        translation_key="current_month_day_count",
        native_unit_of_measurement="days",
        value_fn=lambda data: data.get("current_month_day_count"),
    ),
    EcoguardSensorDescription(
        key="today_kwh",
        translation_key="today_kwh",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda data: data.get("today_kwh"),
    ),
    EcoguardSensorDescription(
        key="price_per_kwh",
        translation_key="price_per_kwh",
        native_unit_of_measurement="SEK/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=lambda data: data.get("price_per_kwh"),
    ),
    EcoguardSensorDescription(
        key="price_valid_from",
        translation_key="price_valid_from",
        value_fn=lambda data: data.get("price_valid_from"),
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EcoguardCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        EcoguardSensor(coordinator, description, entry)
        for description in SENSOR_DESCRIPTIONS
    )


class EcoguardSensor(CoordinatorEntity[EcoguardCoordinator], SensorEntity):
    _attr_has_entity_name = True
    entity_description: EcoguardSensorDescription

    def __init__(
        self,
        coordinator: EcoguardCoordinator,
        description: EcoguardSensorDescription,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Ecoguard Insight",
            "manufacturer": "Ecoguard",
            "entry_type": DeviceEntryType.SERVICE,
        }

    @property
    def native_value(self) -> float | str | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)
