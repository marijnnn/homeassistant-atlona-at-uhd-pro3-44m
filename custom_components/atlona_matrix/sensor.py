"""Diagnostic 'last communication' sensor."""
from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AtlonaConfigEntry, AtlonaCoordinator
from .entity import AtlonaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AtlonaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AtlonaLastCommunicationSensor(entry.runtime_data)])


class AtlonaLastCommunicationSensor(AtlonaEntity, SensorEntity):
    """Time of the last successful exchange with the matrix (poll or command)."""

    _attr_name = "Last communication"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: AtlonaCoordinator) -> None:
        # unique id kept from v1.3.x so the existing entity is reused
        super().__init__(coordinator, "communication_timestamp")

    @property
    def available(self) -> bool:
        # Keep showing the last successful time while the matrix is offline.
        return self.coordinator.data is not None

    @property
    def native_value(self):
        return self.coordinator.data.last_communication
