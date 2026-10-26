"""Diagnostic 'Connected' binary sensor."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import AtlonaConfigEntry, AtlonaCoordinator
from .entity import AtlonaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AtlonaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AtlonaConnectedSensor(entry.runtime_data)])


class AtlonaConnectedSensor(AtlonaEntity, BinarySensorEntity):
    """On while the matrix answers.

    "Last communication" is an attribute rather than a timestamp sensor:
    attribute-only changes do not show up in the logbook/activity, and it is
    excluded from the recorder so it does not grow the database every poll.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "connected"
    _unrecorded_attributes = frozenset({"last_communication"})

    def __init__(self, coordinator: AtlonaCoordinator) -> None:
        super().__init__(coordinator, "connected")

    @property
    def available(self) -> bool:
        return True  # this entity reports the connection itself

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        last = data.last_communication if data else None
        return {"last_communication": last.isoformat() if last else None}
