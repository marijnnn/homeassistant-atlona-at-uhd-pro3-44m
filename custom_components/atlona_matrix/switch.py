"""Power / standby switch and per-output enable switches."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NUM_SWITCHABLE_OUTPUTS
from .coordinator import AtlonaConfigEntry, AtlonaCoordinator
from .entity import AtlonaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AtlonaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [AtlonaPowerSwitch(coordinator)]
    entities += [
        AtlonaOutputEnableSwitch(coordinator, o) for o in range(1, NUM_SWITCHABLE_OUTPUTS + 1)
    ]
    async_add_entities(entities)


class AtlonaPowerSwitch(AtlonaEntity, SwitchEntity):
    _attr_name = "Power"
    _attr_icon = "mdi:power"

    def __init__(self, coordinator: AtlonaCoordinator) -> None:
        super().__init__(coordinator, "power")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.power

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)


class AtlonaOutputEnableSwitch(AtlonaEntity, SwitchEntity):
    """Turns the video on an output on/off (``x2$ on`` / ``x2$ off``)."""

    def __init__(self, coordinator: AtlonaCoordinator, output: int) -> None:
        super().__init__(coordinator, f"output_{output}_enabled")
        self.output = output
        self._attr_name = f"{coordinator.names[f'output_{output}']} output"

    @property
    def icon(self) -> str:
        return "mdi:television" if self.is_on is not False else "mdi:television-off"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.output_enabled.get(self.output)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_output_enabled(self.output, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_output_enabled(self.output, False)
