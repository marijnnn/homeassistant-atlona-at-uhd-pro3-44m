"""Constants for the Atlona Matrix integration."""
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

DOMAIN = "atlona_matrix"
MANUFACTURER = "Atlona"
MODEL = "AT-UHD-PRO3-44M"

DEFAULT_NAME = "Atlona Matrix"
DEFAULT_PORT = 23
DEFAULT_POLL_INTERVAL = 15
MIN_POLL_INTERVAL = 5
MAX_POLL_INTERVAL = 300

CONF_POLL_INTERVAL = "poll_interval"
CONF_INSTANT_UPDATES = "instant_updates"
DEFAULT_INSTANT_UPDATES = True

NUM_INPUTS = 4
NUM_OUTPUTS = 5
INPUT_KEYS = [f"input_{i}" for i in range(1, NUM_INPUTS + 1)]
OUTPUT_KEYS = [f"output_{i}" for i in range(1, NUM_OUTPUTS + 1)]

__all__ = [
    "CONF_HOST", "CONF_NAME", "CONF_PASSWORD", "CONF_PORT", "CONF_USERNAME",
]


def default_name(key: str) -> str:
    """input_1 -> 'Input 1'."""
    return key.replace("_", " ").title()
