"""Atlona AT-UHD-PRO3-44M matrix integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .api import AtlonaClient, AtlonaError
from .const import (
    CONF_HOST,
    CONF_INSTANT_UPDATES,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_INSTANT_UPDATES,
    DEFAULT_PORT,
    DOMAIN,
)
from .coordinator import AtlonaConfigEntry, AtlonaCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SELECT,
    Platform.BUTTON,
    Platform.SWITCH,
    Platform.SENSOR,
]


def merged_config(entry: ConfigEntry) -> dict:
    """Options override the values entered during initial setup."""
    return {**entry.data, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: AtlonaConfigEntry) -> bool:
    config = merged_config(entry)
    client = AtlonaClient(
        config[CONF_HOST],
        int(config.get(CONF_PORT, DEFAULT_PORT)),
        config.get(CONF_USERNAME),
        config.get(CONF_PASSWORD),
    )
    coordinator = AtlonaCoordinator(hass, entry, client, config)
    try:
        # Raises ConfigEntryNotReady (HA retries automatically) when unreachable.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.close()
        raise

    try:
        coordinator.sw_version = (await client.get_text("Version")).replace("Firmware", "").strip()
    except AtlonaError as err:
        _LOGGER.debug("Could not read Atlona firmware version: %s", err)

    if config.get(CONF_INSTANT_UPDATES, DEFAULT_INSTANT_UPDATES):
        # Matrix pushes changes (web GUI, front panel) immediately.
        try:
            await client.set_broadcast(True)
        except AtlonaError as err:
            _LOGGER.warning("Could not enable Broadcast on the Atlona: %s", err)

    _remove_obsolete_entities(hass, entry)
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


# Sensors from v1.3.x - v1.4.2 that were merged into "Last communication".
_OBSOLETE_SENSORS = ("status_timestamp", "power_timestamp")


def _remove_obsolete_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    registry = er.async_get(hass)
    for suffix in _OBSOLETE_SENSORS:
        if entity_id := registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{suffix}"
        ):
            _LOGGER.debug("Removing obsolete entity %s", entity_id)
            registry.async_remove(entity_id)


async def _async_update_listener(hass: HomeAssistant, entry: AtlonaConfigEntry) -> None:
    """Options changed (names, host, interval...): reload so they apply."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AtlonaConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.close()
    return unload_ok
