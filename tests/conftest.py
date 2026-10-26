"""Shared fixtures. Runs on pytest-homeassistant-custom-component (a real Home Assistant)."""
import pytest

from .mock_atlona import MockAtlona

NAMES = {
    "input_1": "Apple TV", "input_2": "PS5", "input_3": "PC", "input_4": "Chromecast",
    "output_1": "Living room", "output_2": "Bedroom", "output_3": "Office",
    "output_4": "Kitchen", "output_5": "HDMI out",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/atlona_matrix in every test."""
    yield


@pytest.fixture
def expected_lingering_tasks() -> bool:
    """The simulated matrix's TCP server tasks may outlive a test by a moment."""
    return True


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Debounced refreshes / setup retries may still be scheduled at test end."""
    return True


@pytest.fixture
async def mock_atlona(socket_enabled):
    """A simulated AT-UHD-PRO3-44M on 127.0.0.1."""
    mock = await MockAtlona().start()
    yield mock
    await mock.stop()
