"""Integration tests: setup, entities, commands and pushes in a real Home Assistant."""
import asyncio

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from datetime import timedelta

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.atlona_matrix.const import DOMAIN
from custom_components.atlona_matrix.diagnostics import async_get_config_entry_diagnostics

from .conftest import NAMES


def make_entry(port: int, **extra) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Atlona",
        unique_id=f"127.0.0.1:{port}",
        data={"name": "Atlona", "host": "127.0.0.1", "port": port, "poll_interval": 15,
              "instant_updates": True, **NAMES, **extra},
    )


async def setup_entry(hass: HomeAssistant, port: int, **extra) -> MockConfigEntry:
    entry = make_entry(port, **extra)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def eid(hass: HomeAssistant, platform: str, entry, suffix: str) -> str:
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")
    assert entity_id, f"{platform} {suffix} not registered"
    return entity_id


async def unload(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_creates_entities(hass: HomeAssistant, mock_atlona) -> None:
    entry = await setup_entry(hass, mock_atlona.port)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(eid(hass, "select", entry, "output_1")).state == "Apple TV"
    assert hass.states.get(eid(hass, "select", entry, "output_2")).state == "PS5"
    assert hass.states.get(eid(hass, "select", entry, "output_5")).state == "Apple TV"
    select_state = hass.states.get(eid(hass, "select", entry, "output_1"))
    assert select_state.attributes["options"] == ["Apple TV", "PS5", "PC", "Chromecast"]
    assert hass.states.get(eid(hass, "switch", entry, "power")).state == STATE_ON
    for output in range(1, 6):
        assert hass.states.get(eid(hass, "switch", entry, f"output_{output}_enabled")).state == STATE_ON
    connected = hass.states.get(eid(hass, "binary_sensor", entry, "connected"))
    assert connected.state == STATE_ON
    assert connected.attributes["last_communication"]
    assert mock_atlona.broadcast is True  # instant updates enabled Broadcast
    await unload(hass, entry)


async def test_select_routes_input(hass: HomeAssistant, mock_atlona) -> None:
    entry = await setup_entry(hass, mock_atlona.port)
    entity_id = eid(hass, "select", entry, "output_2")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": "Chromecast"}, blocking=True
    )
    assert mock_atlona.routing[2] == 4
    assert hass.states.get(entity_id).state == "Chromecast"
    await unload(hass, entry)


async def test_button_routes_to_all(hass: HomeAssistant, mock_atlona) -> None:
    entry = await setup_entry(hass, mock_atlona.port)
    await hass.services.async_call(
        "button", "press", {"entity_id": eid(hass, "button", entry, "input_3_all")}, blocking=True
    )
    await hass.async_block_till_done()
    assert set(mock_atlona.routing.values()) == {3}
    for output in range(1, 6):
        assert hass.states.get(eid(hass, "select", entry, f"output_{output}")).state == "PC"
    await unload(hass, entry)


async def test_power_and_output_switches(hass: HomeAssistant, mock_atlona) -> None:
    entry = await setup_entry(hass, mock_atlona.port)
    power = eid(hass, "switch", entry, "power")
    await hass.services.async_call("switch", "turn_off", {"entity_id": power}, blocking=True)
    await hass.async_block_till_done()
    assert mock_atlona.power is False
    assert hass.states.get(power).state == STATE_OFF
    await hass.services.async_call("switch", "turn_on", {"entity_id": power}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(power).state == STATE_ON

    out3 = eid(hass, "switch", entry, "output_3_enabled")
    await hass.services.async_call("switch", "turn_off", {"entity_id": out3}, blocking=True)
    assert mock_atlona.enabled[3] is False
    assert hass.states.get(out3).state == STATE_OFF
    await unload(hass, entry)


async def test_push_from_matrix_updates_state(hass: HomeAssistant, mock_atlona) -> None:
    """Change made in the web GUI / front panel arrives without a poll."""
    entry = await setup_entry(hass, mock_atlona.port)
    await mock_atlona.push_raw(b"#*PORT1_[\x00]\r\n")  # noise seen on the real device
    await mock_atlona.push("x2AVx1,x3AVx4")
    await asyncio.sleep(0.2)
    await hass.async_block_till_done()
    assert hass.states.get(eid(hass, "select", entry, "output_1")).state == "PS5"
    assert hass.states.get(eid(hass, "select", entry, "output_4")).state == "PC"
    await unload(hass, entry)


async def test_unreachable_matrix_retries_setup(hass: HomeAssistant, socket_enabled) -> None:
    entry = make_entry(1)  # nothing listens on port 1
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_obsolete_sensors_removed(hass: HomeAssistant, mock_atlona) -> None:
    entry = make_entry(mock_atlona.port)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for suffix in ("status_timestamp", "power_timestamp", "communication_timestamp"):
        registry.async_get_or_create("sensor", DOMAIN, f"{entry.entry_id}_{suffix}", config_entry=entry)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_status_timestamp") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_power_timestamp") is None
    assert registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_communication_timestamp") is None
    assert eid(hass, "binary_sensor", entry, "connected")
    await unload(hass, entry)


async def test_diagnostics_redacts_password(hass: HomeAssistant, mock_atlona) -> None:
    entry = await setup_entry(hass, mock_atlona.port, username="", password="secret")
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["config"]["password"] == "**REDACTED**"
    assert diag["device"]["firmware"] == "16.1.19"
    assert diag["state"]["routing_output_to_input"][1] == 1
    assert any(row["dir"] == "TX" for row in diag["history"])
    await unload(hass, entry)


async def test_translated_names(hass: HomeAssistant, mock_atlona) -> None:
    entry = await setup_entry(hass, mock_atlona.port)
    state = hass.states.get(eid(hass, "switch", entry, "output_2_enabled"))
    assert state.attributes["friendly_name"] == "Atlona Bedroom video"
    state = hass.states.get(eid(hass, "button", entry, "input_3_all"))
    assert state.attributes["friendly_name"] == "Atlona PC to all outputs"
    assert hass.states.get(eid(hass, "switch", entry, "power")).attributes["friendly_name"] == "Atlona Power"
    await unload(hass, entry)


async def test_unreachable_raises_and_clears_repair_issue(hass: HomeAssistant, mock_atlona) -> None:
    entry = await setup_entry(hass, mock_atlona.port)
    coordinator = entry.runtime_data
    connected = eid(hass, "binary_sensor", entry, "connected")
    issues = ir.async_get(hass)

    await mock_atlona.stop()
    await coordinator.client.close()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(connected).state == STATE_OFF
    assert hass.states.get(eid(hass, "select", entry, "output_1")).state == STATE_UNAVAILABLE
    assert issues.async_get_issue(DOMAIN, coordinator.issue_id) is None  # not yet: < 5 min

    coordinator._unreachable_since -= timedelta(minutes=6)
    await coordinator.async_refresh()
    assert issues.async_get_issue(DOMAIN, coordinator.issue_id) is not None

    mock2 = await type(mock_atlona)().start()
    try:
        coordinator.client.port = mock2.port
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(connected).state == STATE_ON
        assert issues.async_get_issue(DOMAIN, coordinator.issue_id) is None
        await unload(hass, entry)
    finally:
        await mock2.stop()
