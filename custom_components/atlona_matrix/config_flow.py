"""Config and options flow for the Atlona matrix."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback

from .api import AtlonaAuthError, AtlonaClient, AtlonaError
from .const import (
    CONF_HOST,
    CONF_INSTANT_UPDATES,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_USERNAME,
    DEFAULT_INSTANT_UPDATES,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    INPUT_KEYS,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    OUTPUT_KEYS,
    default_name,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_KEYS = (CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD)


def _connection_schema(d: dict[str, Any], include_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_name:
        fields[vol.Required(CONF_NAME, default=d.get(CONF_NAME, DEFAULT_NAME))] = str
    fields.update({
        vol.Required(CONF_HOST, default=d.get(CONF_HOST, "")): str,
        vol.Required(CONF_PORT, default=d.get(CONF_PORT, DEFAULT_PORT)): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        ),
        vol.Optional(CONF_USERNAME, description={"suggested_value": d.get(CONF_USERNAME)}): str,
        vol.Optional(CONF_PASSWORD, description={"suggested_value": d.get(CONF_PASSWORD)}): str,
        vol.Required(
            CONF_POLL_INTERVAL, default=d.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
        ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
        vol.Required(
            CONF_INSTANT_UPDATES, default=d.get(CONF_INSTANT_UPDATES, DEFAULT_INSTANT_UPDATES)
        ): bool,
    })
    return vol.Schema(fields)


def _names_schema(d: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required(key, default=d.get(key) or default_name(key)): str
        for key in INPUT_KEYS + OUTPUT_KEYS
    })


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_HOST] = data[CONF_HOST].strip()
    data[CONF_USERNAME] = (data.get(CONF_USERNAME) or "").strip()
    data[CONF_PASSWORD] = data.get(CONF_PASSWORD) or ""
    return data


def _validate_names(user_input: dict[str, Any]) -> dict[str, str]:
    names = [user_input[k].strip() for k in INPUT_KEYS]
    if any(not n for n in names) or any(not user_input[k].strip() for k in OUTPUT_KEYS):
        return {"base": "empty_name"}
    if len(set(names)) != len(names):
        return {"base": "duplicate_input_names"}
    return {}


async def _test_connection(data: dict[str, Any]) -> str | None:
    """Return an error key, or None when the matrix answered."""
    client = AtlonaClient(
        data[CONF_HOST], int(data[CONF_PORT]), data.get(CONF_USERNAME), data.get(CONF_PASSWORD)
    )
    try:
        await client.get_power()
    except AtlonaAuthError:
        return "invalid_auth"
    except AtlonaError as err:
        _LOGGER.debug("Connection test to %s failed: %s", data[CONF_HOST], err)
        return "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error testing Atlona connection")
        return "unknown"
    finally:
        await client.close()
    return None


class AtlonaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            data = _clean(user_input)
            await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            if error := await _test_connection(data):
                errors["base"] = error
            else:
                self._data = data
                return await self.async_step_names()
        return self.async_show_form(
            step_id="user",
            data_schema=_connection_schema(user_input or {}, include_name=True),
            errors=errors,
        )

    async def async_step_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_names(user_input)
            if not errors:
                names = {k: v.strip() for k, v in user_input.items()}
                return self.async_create_entry(
                    title=self._data[CONF_NAME], data={**self._data, **names}
                )
        return self.async_show_form(
            step_id="names", data_schema=_names_schema(user_input or {}), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AtlonaOptionsFlow()


class AtlonaOptionsFlow(OptionsFlow):
    """Menu: connection settings or input/output names.

    Note: ``self.config_entry`` is provided by Home Assistant; setting it
    manually (as v1.3.x did) is deprecated and breaks on HA 2025.12+.
    """

    @property
    def _current(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["names", "connection"])

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        current = self._current
        if user_input is not None:
            data = _clean(user_input)
            changed = any(str(data.get(k) or "") != str(current.get(k) or "") for k in CONNECTION_KEYS)
            if changed and (error := await _test_connection(data)):
                errors["base"] = error
            else:
                return self.async_create_entry(data={**self.config_entry.options, **data})
        return self.async_show_form(
            step_id="connection",
            data_schema=_connection_schema(user_input or current, include_name=False),
            errors=errors,
        )

    async def async_step_names(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_names(user_input)
            if not errors:
                names = {k: v.strip() for k, v in user_input.items()}
                return self.async_create_entry(data={**self.config_entry.options, **names})
        return self.async_show_form(
            step_id="names",
            data_schema=_names_schema(user_input or self._current),
            errors=errors,
        )
