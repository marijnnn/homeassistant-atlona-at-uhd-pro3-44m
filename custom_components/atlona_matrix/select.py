"""Per-output input selection."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import NUM_OUTPUTS
from .coordinator import AtlonaConfigEntry, AtlonaCoordinator
from .entity import AtlonaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AtlonaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        AtlonaOutputSelect(coordinator, output) for output in range(1, NUM_OUTPUTS + 1)
    )


class AtlonaOutputSelect(AtlonaEntity, SelectEntity):
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, coordinator: AtlonaCoordinator, output: int) -> None:
        super().__init__(coordinator, f"output_{output}")
        self.output = output
        self._attr_name = coordinator.names[f"output_{output}"]
        self._attr_options = coordinator.input_names

    @property
    def current_option(self) -> str | None:
        input_no = self.coordinator.data.routing.get(self.output)
        if input_no and 1 <= input_no <= len(self._attr_options):
            return self._attr_options[input_no - 1]
        return None

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "output": self.output,
            "input": self.coordinator.data.routing.get(self.output),
        }

    async def async_select_option(self, option: str) -> None:
        try:
            input_no = self._attr_options.index(option) + 1
        except ValueError:
            raise HomeAssistantError(f"Unknown input: {option}") from None
        await self.coordinator.async_route(input_no, self.output)
