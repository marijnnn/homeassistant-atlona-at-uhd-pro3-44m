"""Config flow and options flow in a real Home Assistant."""
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atlona_matrix.const import DOMAIN

from .conftest import NAMES
from .mock_atlona import MockAtlona


def connection(port: int, **extra) -> dict:
    return {"name": "Atlona", "host": "127.0.0.1", "port": port, "poll_interval": 15,
            "instant_updates": True, **extra}


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_atlona) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], connection(mock_atlona.port)
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "names"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**NAMES, "input_2": "Apple TV"}
    )
    assert result["errors"] == {"base": "duplicate_input_names"}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], NAMES)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Atlona"
    assert result["data"]["host"] == "127.0.0.1"
    assert result["data"]["output_5"] == "HDMI out"
    await hass.async_block_till_done()
    await hass.config_entries.async_unload(result["result"].entry_id)
    await hass.async_block_till_done()


async def test_user_flow_cannot_connect(hass: HomeAssistant, socket_enabled) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], connection(1))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_login(hass: HomeAssistant, socket_enabled) -> None:
    mock = await MockAtlona(login=True).start()
    try:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], connection(mock.port)
        )
        assert result["errors"] == {"base": "invalid_auth"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], connection(mock.port, username="root", password="Atlona")
        )
        assert result["step_id"] == "names"
    finally:
        await mock.stop()


async def test_already_configured(hass: HomeAssistant, mock_atlona) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id=f"127.0.0.1:{mock_atlona.port}").add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], connection(mock_atlona.port)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_names_and_connection(hass: HomeAssistant, mock_atlona) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Atlona", unique_id=f"127.0.0.1:{mock_atlona.port}",
        data={**connection(mock_atlona.port), **NAMES},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "names"}
    )
    assert result["step_id"] == "names"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {**NAMES, "output_1": "TV"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["output_1"] == "TV"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "connection"}
    )
    assert result["step_id"] == "connection"
    conn = connection(mock_atlona.port, poll_interval=30)
    conn.pop("name")
    result = await hass.config_entries.options.async_configure(result["flow_id"], conn)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert entry.options["poll_interval"] == 30
    assert entry.options["output_1"] == "TV"  # names kept
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
