"""Base entity for the Atlona matrix."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import AtlonaCoordinator


class AtlonaEntity(CoordinatorEntity[AtlonaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AtlonaCoordinator, unique_suffix: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version=coordinator.sw_version,
            configuration_url=f"http://{coordinator.host}",
        )
