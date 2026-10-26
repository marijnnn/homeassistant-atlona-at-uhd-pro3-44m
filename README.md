# Atlona Matrix for Home Assistant (AT-UHD-PRO3-44M)

[![Validate](https://github.com/marijnnn/homeassistant-atlona-at-uhd-pro3-44m/actions/workflows/validate.yml/badge.svg)](https://github.com/marijnnn/homeassistant-atlona-at-uhd-pro3-44m/actions/workflows/validate.yml)
[![Tests](https://github.com/marijnnn/homeassistant-atlona-at-uhd-pro3-44m/actions/workflows/tests.yml/badge.svg)](https://github.com/marijnnn/homeassistant-atlona-at-uhd-pro3-44m/actions/workflows/tests.yml)

Custom integration that controls an Atlona AT-UHD-PRO3-44M 4×4 HDBaseT matrix
(+ HDMI output 5) over Telnet/TCP, with instant updates from the matrix.
Tested against a real AT-UHD-PRO3-44M with firmware 16.1.19.

## Entities

| Entity | What it does |
|---|---|
| 5 × `select` (one per output) | Choose which input goes to that output (`x{in}AVx{out}`) |
| 4 × `button` | Send one input to all outputs (`x{in}All`) |
| `switch` Power | Power on / standby (`PWON` / `PWOFF`), state from `PWSTA` |
| 5 × `switch` *<output> video* | Turn the video on an output on/off without standby (`x2$ on/off`) |
| Diagnostic `binary_sensor` Connected | On while the matrix answers; attribute *last communication* |

Entities become **unavailable** when the matrix cannot be reached, and recover by themselves.
If the matrix stays unreachable for more than 5 minutes, a warning appears under
*Settings → Repairs*; it disappears automatically when the matrix is back.

Entity names follow the Home Assistant language (English and Dutch included).

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/marijnnn/homeassistant-atlona-at-uhd-pro3-44m`,
   type **Integration**.
2. Search for *Atlona Matrix* in HACS, download it and restart Home Assistant.
3. *Settings → Devices & services → Add integration → Atlona Matrix*.

Updates then appear in HACS automatically.

### Manual

Download `atlona_matrix.zip` from the latest
[release](https://github.com/marijnnn/homeassistant-atlona-at-uhd-pro3-44m/releases), extract it to
`/config/custom_components/atlona_matrix/` (replace the old folder completely)
and restart Home Assistant.

Requires Home Assistant **2024.12 or newer** (the integration icon is shown from 2026.3).

Upgrading from 1.3.x: the existing entry and entity IDs are kept. Just copy the
new files over and restart.

## Telnet login (IPLogin)

The factory default on the matrix is `IPLogin on`, which means every Telnet
session asks for a username and password (same as the web GUI). You can either:

* enter the username/password in the integration, or
* switch the login off on the matrix (send `IPLogin off` once via Telnet or
  change it in the web GUI).

## Tips

* The matrix closes idle Telnet sessions after `IPTimeout` (default 300 s). The
  integration reconnects automatically, and polling every 15 s keeps the
  session open anyway.
* The matrix accepts a limited number of Telnet sessions. Close other Telnet
  clients (PuTTY, other controllers) if the connection fails.
* Not every firmware includes output 5 in the `Status` answer. The integration
  then asks `Statusx5` separately; if the firmware rejects that too, output 5
  shows the last value you selected.
* **Instant updates** (option, on by default) sets `Broadcast on` on the matrix.
  Changes from the web GUI and the front panel are then shown in Home Assistant
  immediately; polling is only a safety net and can be set to e.g. 30 s.

## Names

Settings → Devices & services → Atlona Matrix → **Configure** →
*Input and output names*. The entities are renamed right away.

## Diagnostics

Settings → Devices & services → Atlona Matrix → ⋮ → **Download diagnostics**:
configuration (password removed), state, connection info and the last 100
lines sent to / received from the matrix.

## Debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.atlona_matrix: debug
```

Every sent (`TX`) and received (`RX`) line is logged.

## Changelog

### 1.7.0
* New diagnostic **Connected** binary sensor. *Last communication* is now its
  attribute instead of a separate timestamp sensor, so it no longer fills the
  device's activity log every poll (and is not stored by the recorder).
  The old timestamp sensor is removed automatically.
* **Repairs warning** when the matrix is unreachable for more than 5 minutes.
* Faster reconnect: a dropped Telnet session triggers an immediate refresh.
* **Translated entity names** (English/Dutch): Power, "… video",
  "… to all outputs", Connected.
* Raw bytes from the matrix (`#*PORTn_[..]` link pulses, seen on the real
  device) are kept intact and counted per output in the diagnostics download.

### 1.6.0
* **Instant updates**: a background listener processes changes the matrix
  pushes (web GUI and front panel, verified on the device) immediately,
  instead of at the next poll. Enabled with the new option "Instant updates".
* **Output on/off switches** for outputs 1–5 (`x?$`), also polled.
* **Diagnostics download** with the last 100 TX/RX lines.
* Options are now a menu: *names* or *connection and polling*.
* Atlona logo as integration icon.

### 1.5.0
* The three diagnostic timestamp sensors are merged into one *Last communication*
  sensor (status and power are always polled together, so the values were the
  same). The two old sensors are removed from the entity registry automatically.
* Integration icon (`brand/`), shown by Home Assistant 2026.3+.

### 1.4.2
* Tested against the real AT-UHD-PRO3-44M (firmware 16.1.19).
* Errors are recognised in the format the device actually sends,
  `Command FAILED: (<command>)`, instead of waiting for a timeout.

### 1.4.1
* `PWOFF` without feedback (seen on the real device) is no longer an error:
  the power state is verified with `PWSTA`. PWON/PWOFF are never sent twice.

### 1.4.0
* **Entities now update in the UI.** In 1.3.x, entities were not linked to the
  coordinator, so after polling, front-panel changes, or "to all outputs", the
  states stayed stale until something else triggered a refresh.
* Matrix unreachable → entities are *unavailable* (used to keep showing stale
  values without any error); during startup HA retries automatically.
* Options flow fixed for HA 2025.12+ (setting `config_entry` manually is no
  longer allowed). Changes to names, IP address or interval now take effect
  immediately (the entry reloads) instead of after a restart.
* Telnet login support (username/password); clear error when the matrix asks
  for a login.
* The connection is tested in the config/options flow (errors: cannot connect,
  invalid login, duplicate input names).
* New line-based protocol handling: handles `Command FAILED`, Telnet echo, CR/CRLF
  split across packets, and Telnet negotiation; reconnects and retries once
  when the device has closed the session.
* Output 5 via `Statusx5` when `Status` only returns 4 outputs.
* Broadcast feedback from the matrix is processed.
* Firmware version shown in the device info; timestamp sensors are diagnostic.
* Labels and errors in the setup form (English and Dutch).

## Development

```bash
pip install -r requirements_test.txt
pytest
```

`tests/test_api.py` tests the Telnet protocol against a simulated matrix
(`tests/mock_atlona.py`, built from real device traffic); `test_init.py` and
`test_config_flow.py` run the integration inside a real Home Assistant test
instance. Releases: bump `version` in `manifest.json`, then push a tag `vX.Y.Z`.

Not affiliated with Atlona. Atlona and the Atlona logo are trademarks of their owner.
