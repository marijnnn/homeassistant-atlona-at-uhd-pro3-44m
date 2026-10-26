"""Polling coordinator for the Atlona matrix."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AtlonaAuthError,
    AtlonaClient,
    AtlonaCommandError,
    AtlonaConnectionError,
    AtlonaError,
)
from .const import (
    CONF_HOST,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    INPUT_KEYS,
    OUTPUT_KEYS,
    default_name,
)

_LOGGER = logging.getLogger(__name__)

type AtlonaConfigEntry = ConfigEntry["AtlonaCoordinator"]


@dataclass
class AtlonaData:
    routing: dict[int, int | None] = field(default_factory=dict)
    power: bool | None = None
    status_last_retrieved: datetime | None = None
    power_last_retrieved: datetime | None = None
    last_communication: datetime | None = None
    output_enabled: dict[int, bool | None] = field(default_factory=dict)


class AtlonaCoordinator(DataUpdateCoordinator[AtlonaData]):
    """Polls Status/PWSTA and executes commands for the entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: AtlonaClient,
        config: dict,
    ) -> None:
        self.client = client
        self.host = config[CONF_HOST]
        self.names = {k: (config.get(k) or default_name(k)) for k in INPUT_KEYS + OUTPUT_KEYS}
        self.sw_version: str | None = None
        self._status_last: datetime | None = None
        self._power_last: datetime | None = None
        self._last_comm: datetime | None = None
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.host}",
            update_interval=timedelta(
                seconds=int(config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL))
            ),
        )
        client.on_unsolicited = self._handle_unsolicited

    # ------------------------------------------------------------ helpers

    @property
    def input_names(self) -> list[str]:
        return [self.names[k] for k in INPUT_KEYS]

    def _snapshot(self) -> AtlonaData:
        return AtlonaData(
            routing=dict(self.client.state.routing),
            power=self.client.state.power,
            status_last_retrieved=self._status_last,
            power_last_retrieved=self._power_last,
            last_communication=self._last_comm,
            output_enabled=dict(self.client.state.output_enabled),
        )

    @callback
    def _handle_unsolicited(self) -> None:
        """Broadcast feedback from the matrix (e.g. web GUI change)."""
        self._last_comm = dt_util.utcnow()
        self.async_set_updated_data(self._snapshot())

    # ------------------------------------------------------------- polling

    async def _async_update_data(self) -> AtlonaData:
        now = dt_util.utcnow()
        failures: list[str] = []
        try:
            await self.client.get_routing()
            self._status_last = now
        except AtlonaCommandError as err:
            # e.g. some firmware rejects Status while in standby
            failures.append(str(err))
            _LOGGER.debug("Status rejected: %s", err)
        except AtlonaAuthError as err:
            raise UpdateFailed(f"Atlona login failed: {err}") from err
        except AtlonaConnectionError as err:
            raise UpdateFailed(f"Atlona {self.host} not reachable: {err}") from err

        try:
            await self.client.get_power()
            self._power_last = now
        except AtlonaCommandError as err:
            failures.append(str(err))
        except AtlonaError as err:
            raise UpdateFailed(f"Atlona {self.host} not reachable: {err}") from err

        if len(failures) == 2:
            raise UpdateFailed("; ".join(failures))

        for output in list(self.client.state.output_enabled):
            try:
                await self.client.get_output_enabled(output)
            except AtlonaCommandError as err:
                _LOGGER.debug("Output %s enable state not available: %s", output, err)
            except AtlonaError as err:
                raise UpdateFailed(f"Atlona {self.host} not reachable: {err}") from err
        self._last_comm = now
        return self._snapshot()

    # ------------------------------------------------------------ commands

    async def _run(self, description: str, coro) -> None:
        try:
            await coro
        except AtlonaCommandError as err:
            raise HomeAssistantError(f"Atlona rejected {description}: {err}") from err
        except AtlonaError as err:
            raise HomeAssistantError(f"Atlona {description} failed: {err}") from err
        self._last_comm = dt_util.utcnow()
        self.async_set_updated_data(self._snapshot())

    async def async_route(self, input_no: int, output_no: int) -> None:
        await self._run(
            f"routing input {input_no} to output {output_no}",
            self.client.route(input_no, output_no),
        )

    async def async_route_all(self, input_no: int) -> None:
        await self._run(f"routing input {input_no} to all outputs", self.client.route_all(input_no))
        # Confirm the full matrix from the device.
        await self.async_request_refresh()

    async def async_set_output_enabled(self, output_no: int, enabled: bool) -> None:
        await self._run(
            f"{'enabling' if enabled else 'disabling'} output {output_no}",
            self.client.set_output_enabled(output_no, enabled),
        )

    async def async_set_power(self, on: bool) -> None:
        await self._run("power on" if on else "standby", self.client.set_power(on))
        await self.async_request_refresh()
