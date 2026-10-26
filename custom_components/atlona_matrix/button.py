"""'Input X to all outputs' buttons."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NUM_INPUTS
from .coordinator import AtlonaConfigEntry, AtlonaCoordinator
from .entity import AtlonaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AtlonaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(AtlonaAllButton(coordinator, i) for i in range(1, NUM_INPUTS + 1))


class AtlonaAllButton(AtlonaEntity, ButtonEntity):
    _attr_icon = "mdi:arrow-split-vertical"

    def __init__(self, coordinator: AtlonaCoordinator, input_no: int) -> None:
        super().__init__(coordinator, f"input_{input_no}_all")
        self.input_no = input_no
        self._attr_name = f"{coordinator.names[f'input_{input_no}']} to all outputs"

    async def async_press(self) -> None:
        await self.coordinator.async_route_all(self.input_no)
