"""Diagnostics download (Settings > Devices & services > Atlona > ... > Download diagnostics)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PASSWORD, CONF_USERNAME, MODEL
from .coordinator import AtlonaConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: AtlonaConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    client = coordinator.client
    data = coordinator.data
    return {
        "config": async_redact_data({**entry.data, **entry.options}, TO_REDACT),
        "device": {
            "model": MODEL,
            "firmware": coordinator.sw_version,
            "host": client.host,
            "port": client.port,
        },
        "connection": {
            "connected": client.connected,
            "connect_count": client.connect_count,
            "last_error": client.last_error,
            "last_update_success": coordinator.last_update_success,
            "update_interval_s": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "supports_statusx5": client.supports_statusx5,
        },
        "state": {
            "power": data.power if data else None,
            "routing_output_to_input": data.routing if data else None,
            "output_enabled": data.output_enabled if data else None,
            "last_communication": data.last_communication.isoformat()
            if data and data.last_communication
            else None,
        },
        "names": coordinator.names,
        # Last 100 lines sent to / received from the matrix.
        "history": [
            {"time": t, "dir": d, "text": text} for t, d, text in client.history
        ],
    }
