[![HACS Default](https://img.shields.io/badge/HACS-Default-blue?style=flat&logo=homeassistantcommunitystore&logoSize=auto)](https://my.home-assistant.io/redirect/hacs_repository/?owner=svalsemey&repository=hassio-lifedomus&category=plugin)
[![HACS Passing](https://github.com/svalsemey/hassio-lifedomus/actions/workflows/validate.yml/badge.svg)](https://github.com/svalsemey/hassio-lifedomus/actions/workflows/validate.yml)
[![Total Downloads](https://img.shields.io/github/downloads/svalsemey/hassio-lifedomus/total.svg)](https://github.com/svalsemey/hassio-lifedomus/releases)
[![Latest Release Downloads](https://img.shields.io/github/downloads/svalsemey/hassio-lifedomus/latest/total.svg)](https://github.com/svalsemey/hassio-lifedomus/releases/latest)

# Lifedomus for Home Assistant

Integration for the Delta Dore Lifedomus gateway.
It offers zero-configuration discovery, secure local communication, efficient coordinators, and an SSH-based push monitor for near real-time updates.

> Community project — not affiliated with or endorsed by Delta Dore S.A.

## Features

- Native config flow with automatic discovery (UDP multicast) and manual host fallback
- Per-site and per-user selection with authentication
- Optional 6-digit alarm access code management (with verification and reconfigure flow)
- Local push (SSH tunnel + XML dispatcher) to minimize polling where possible
- Supported platforms:
  - Binary Sensor: detectors, plus alarm boolean states with icon and fault attributes
  - Button: native push buttons and alarm action buttons (Full arming, Stop, Acknowledge events)
  - Climate: thermostats (direct setpoint and 6-position presets)
  - Cover: motors (shutters) with UP/DOWN/STOP and exact position
  - Light: dimmable and on/off devices
  - Sensor: raw measurement devices and alarm “Operating mode” sensors
  - Switch: alarm zones enable/disable
- Translations available (en, fr, and many others)
- iot_class: local_push (with a resilient SSH monitoring tunnel)

## Requirements

- Home Assistant 2023.11+ (recommended)
- Python 3.11+
- Lifedomus gateway (reachable on your LAN for discovery)
- asyncssh >= 2.14.2,<3.0.0 (installed automatically by Home Assistant)

## Installation

### HACS

Use this link to directly go to the repository in HACS

[![Add this integration to Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=svalsemey&repository=hassio-lifedomus&category=integration)

or

1. In HACS, go to Integrations.
2. Search for **Lifedomus**.
3. Install the integration and restart Home Assistant.

### Manual
1. Copy the `custom_components/lifedomus` directory into your Home Assistant `config/custom_components` folder.
2. Restart Home Assistant.

No YAML configuration is required; everything is handled via the config flow.

## Configuration (Config Flow)

Step overview:
1. Discovery
   - The integration sends a UDP multicast probe and lists discovered gateways.
   - If none is found, you can enter a hostname or IP manually.
2. Site selection
   - The gateway UUID and version are validated.
   - Select a site available on the gateway.
3. User selection
   - Choose a user for the selected site (displayed by nickname).
4. Authentication
   - Enter the user’s password. The session is validated via the gateway.
5. Alarm code (optional)
   - If an alarm panel is detected on the site, you can provide a 6-digit access code:
     - Initial configuration: supplying a correct code enables alarm actions and faults.
     - Reconfigure flow: you can keep, update, or clear the stored code.

Abort and error cases are clearly reported (invalid UUID/version, no site/user configured, invalid credentials, denied alarm code, etc.).

## Options

- Update interval (seconds): global polling interval used by coordinators (default: 60).

## Entities and Capabilities

- Binary Sensor
  - Detectors (category CLSID-DEVC-S-DT) with robust boolean parsing
  - Alarm boolean states (mapping from CLSID states), with icons and extra attributes (fault objects) when authorized

- Button
  - Native push buttons (CLSID-DEVC-A-PC), action: `CLSID-ACTION-PUSH`
  - Alarm buttons per device (CLSID-DEVC-S-PR):
    - Full arming: `CLSID-ACTION-ALARM-FULL-ARMING`
    - Stop: `CLSID-ACTION-ALARM-STOP`
    - Acknowledge events: `CLSID-ACTION-ALARM-ACKNOWLEDGE-EVENTS`

- Climate (Thermostats)
  - Direct setpoint:
    - States: AMBIANT TEMPERATURE, SETPOINT TEMPERATURE
    - Limits read from action descriptor of GENERALCONST (step: 0.5°C)
  - 6-position preset:
    - Presets mapped to Home Assistant presets (Away, Comfort, Eco)
    - STOP translates to HVAC OFF; others to HEAT

- Cover (Shutters/Motors)
  - UP/DOWN/STOP and exact position
  - Position mapping inverted between HA and Lifedomus (HA 100% open = Lifedomus 0%)

- Light
  - Dimmable: value action on `CLSID-DEVC-PROP-DIMMER-VA-POS`
  - On/off: TOR switch on `CLSID-DEVC-PROP-TOR-SW`

- Sensor
  - Raw measurement devices in category CLSID-DEVC-M-CS (value + unit)
  - Alarm Operating mode as text sensor with a context-aware icon

- Switch
  - Alarm zone enable/disable with `CLSID-ACTION-ALARM-ZONE-ENABLE` / `…-DISABLE`

## Local Push Monitor

- Establishes an SSH connection using the gateway’s SecureConnect key for user `ld-remote` on port 51023.
- Opens a direct TCP channel to `ld-remote:8090` and consumes XML notifications.
- Validates and throttles notifications, then triggers targeted per-device coordinator refreshes.
- This reduces latency and polling overhead for supported states.

## Security and Privacy

- Communication stays within your LAN; no third-party cloud involved.
- Sensitive data stored by Home Assistant:
  - Site key, user key, and password used to obtain a session key.
  - Optional alarm access code (6 digits) if you choose to store it.
- Do not expose your Lifedomus gateway or Home Assistant instance directly to the internet.
- The SSH key for monitoring is fetched from the gateway SecureConnect endpoint and used only for the monitoring tunnel.

## Troubleshooting

- Discovery not finding gateways:
  - Ensure multicast traffic is not blocked on your network.
  - Use manual host entry as a fallback.
- Authentication failures:
  - Double-check user credentials and gateway reachability.
- Alarm code denied:
  - The gateway must grant USER-level access for the provided code.
- Logs:
  - Enable debug logging for the integration to assist diagnosis.

Example logger configuration in Home Assistant:
```yaml
logger:
  default: info
  logs:
    custom_components.lifedomus: debug
```

## Translations

Includes English, French, and many additional locales. Key UI strings cover:
- Discovery flow (gateway, manual host)
- Site and user selection
- Authentication
- Alarm code with verification and reconfigure semantics
- Options (update interval)
- Entity names and states (including alarm operating modes and booleans)

## Acknowledgments

- Delta Dore Lifedomus protocol and device categories
- Home Assistant community and reviewers

## License

MIT — see [LICENSE](./LICENSE).

## Issue Tracking

Please use GitHub Issues and fill in the provided templates for bug reports and feature requests.
