"""Hourly consumption sensors for discovered MeterConnex meters."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import LAG_HOURS, ProvidentCoordinator
from .api import Meter
from .const import DOMAIN
from .data import utility_type

UTILITY_INFO = {
    "electricity": (SensorDeviceClass.ENERGY, UnitOfEnergy.KILO_WATT_HOUR),
    "cold_water": (SensorDeviceClass.WATER, UnitOfVolume.CUBIC_METERS),
    "hot_water": (SensorDeviceClass.WATER, UnitOfVolume.CUBIC_METERS),
    "heating": (None, "ekWh"),
    "cooling": (None, "ekWh"),
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one hourly sensor per supported discovered meter."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ProvidentHourSensor(coordinator, entry, meter) for meter in coordinator.meters
    )


class ProvidentHourSensor(CoordinatorEntity[ProvidentCoordinator], SensorEntity):
    """Last selected completed hourly amount for a meter."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: ProvidentCoordinator, entry: ConfigEntry, meter: Meter
    ) -> None:
        super().__init__(coordinator)
        self.meter_id = meter.id
        self.meter_name = meter.name
        self.meter_title = meter.title
        self.utility_type = utility_type(f"{meter.title} {meter.name}")
        self._attr_unique_id = f"{entry.entry_id}_{meter.id}_hourly"
        self._attr_name = f"{meter.name} hourly usage"
        self._attr_device_class, self._attr_native_unit_of_measurement = UTILITY_INFO[
            self.utility_type
        ]

    @property
    def native_value(self) -> float | None:
        """Return a single noncumulative hour, if available."""
        hour = self.coordinator.data.get(self.meter_id)
        return hour.value if hour else None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose meter context and the chosen hour's source position."""
        hour = self.coordinator.data.get(self.meter_id)
        return {
            "meter_id": self.meter_id,
            "meter_name": self.meter_name,
            "meter_title": self.meter_title,
            "utility_type": self.utility_type,
            "delay_hours": LAG_HOURS[self.utility_type],
            "hour_timestamp": hour.timestamp.isoformat() if hour else None,
            "hour_index": hour.index if hour else None,
        }
