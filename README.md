# i-Vent Rekuperator — Home Assistant Integration

Custom integration for [i-Vent](https://i-vent.com/) heat recovery ventilation units via **local UDP protocol** (no cloud dependency).

> **Status:** Read-only (sensors + state) working. Control commands (set temperature, mode, fan) acknowledged by device but not yet applied — protocol reverse-engineering in progress.

## Screenshots

### i-Vent Mobile App
<img src="docs/ivent-app-kabinet.png" width="500" alt="i-Vent app - Kabinet room control">

*Native i-Vent app showing room controls: mode (Rekuperacija/Bypass/Boost/OFF), fan speed (Low/Med/High), and presets (Normal/Snooze/Night/Night 2)*

### Home Assistant — Overview
<img src="docs/ha-rekuperatorji-overview.png" width="400" alt="HA overview of all recuperators">

*All 8 i-Vent units displayed in Home Assistant with power, fan, and mode controls*

### Home Assistant — Climate Card
<img src="docs/ha-climate-card.png" width="400" alt="HA climate thermostat card">

*Climate entity with thermostat dial showing current HVAC mode*

### Home Assistant — Mode Selection
<img src="docs/ha-mode-selector.png" width="400" alt="HA HVAC mode selector">

*Available HVAC modes: Heat/Cool (recovery), Fan only (ventilation), Off*

### Home Assistant — Preset Modes
<img src="docs/ha-preset-selector.png" width="400" alt="HA preset mode selector">

*Preset modes: None, Boost, Snooze, Night, Night Silent*

### Home Assistant — Fan Speed
<img src="docs/ha-fan-mode-selector.png" width="400" alt="HA fan mode selector">

*Fan speed control: Low, Medium, High, Boost*

## Entities

| Platform | Entity | Description |
|----------|--------|-------------|
| `climate` | i-Vent {name} | HVAC mode, target temperature, fan speed, presets |
| `fan` | {name} Ventilator | Fan speed control (low/medium/high/boost) |
| `sensor` | Dovod temperatura | Supply duct temperature (°C) |
| `sensor` | Odvod temperatura | Exhaust/extract duct temperature (°C) |
| `sensor` | Vlažnost | Humidity (%) |
| `sensor` | Filter | Filter status |

## Protocol

This integration communicates with i-Vent units over **UDP port 1028** using a raw **protobuf** wire format (not standard gRPC/HTTP).

### Key Details

- **Transport:** UDP, source port **must** be 1028
- **Encoding:** Raw protobuf (varint, fixed32, fixed64, length-delimited)
- **Discovery:** Message type 257 → returns device info + sensor data
- **Control:** Message type 4370 (MSG_SCHEDULE) → sets mode, setpoint, fan
- **Toggle:** Message type 4358 (MSG_DEVICE_STATE) → on/off
- **Session token:** Permanent, obtained during initial pairing
- **Multi-device:** Multiple units can share a single IP (WiFi bridge) via different session tokens

### Sensor Field Mapping (discovery response → f65.f10)

| Field | Type | Description |
|-------|------|-------------|
| f1 | varint | Exhaust/extract duct temp (°C) |
| f2 | varint | Supply duct temp (°C) |
| f3 | varint | Humidity (%) |
| f7 | varint | Mode (4=recovery) |
| f8 | varint | Fan level (5=boost) |
| f10 | varint | Temperature setpoint (16-33°C) |
| f12 | varint | Fan % (live) |

### Control Protocol (MSG_SCHEDULE 4370)

Sends 6 packets per command: 3 persistent nonce slots × 2 directions (extract + supply).

```
f88 {
  f1 = schedule_nonce (fixed32)
  f8 {
    f1 = mode (0=ventilation, 2=recovery)
    f2 = setpoint
    f3 = direction (1=supply, 2=extract)
    f4 = fan_level (1-2)
    f5 = sub_mode
    f6 = start_timestamp
    f7 = end_timestamp
    f8 = 65
    f9 = 65
  }
  f99 = 258 (fixed64)
}
```

## Installation

### HACS (Manual)

1. Copy `custom_components/ivent/` to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration → i-Vent
4. Enter device IP and session token

### Deployment (development)

```bash
# From this repo root — do NOT use scp -r (creates nested dirs)
scp hacs-ivent/custom_components/ivent/*.py *.json *.yaml root@<HA_IP>:/config/custom_components/ivent/

# Clean bytecode cache and restart
ssh root@<HA_IP> "rm -rf /config/custom_components/ivent/__pycache__/ && ha core restart"
```

## Project Structure

```
custom_components/ivent/
├── __init__.py          # Integration setup + platform loading
├── api.py               # UDP client, protobuf codec, control commands
├── climate.py           # Climate entity (HVAC mode, target temp, presets)
├── config_flow.py       # UI configuration flow
├── const.py             # Constants (ports, message types, field IDs)
├── coordinator.py       # DataUpdateCoordinator (polling via discovery)
├── fan.py               # Fan entity (speed control)
├── manifest.json        # Integration manifest (local_polling)
├── proto.py             # Raw protobuf encoder/decoder
├── sensor.py            # Temperature, humidity, filter sensors
├── strings.json         # UI strings
└── translations/
    └── en.json          # English translations
```

## Known Limitations

- **Control commands:** Device acknowledges packets (47-byte ACK, msg type 33279) but does not apply settings changes. Needs further PCAP analysis with confirmed state changes from the native app.
- **Single device:** Currently only tested with 1 unit ("Kabinet" on 192.168.1.164). Multi-device support is structurally ready but untested.
- **No outdoor/indoor temp:** Fields f4-f6 in sensor data are dynamic differentials, not direct temperature readings. Removed from entities.
- **No CO2 sensor:** Requires i-Qube hardware module, field mapping unknown.

## License

MIT
