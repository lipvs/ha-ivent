# i-Vent Rekuperator — Home Assistant Integration

Custom HACS integration for [i-Vent](https://i-vent.com/) heat recovery ventilation units via local network — **no cloud dependency**.

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

## Why This Is Useful

i-Vent recuperators have no official Home Assistant integration or public API. This integration exposes your ventilation system to HA, enabling:

- **Temperature monitoring** — track supply and exhaust duct temperatures per room
- **Humidity tracking** — monitor indoor humidity levels from each unit
- **Climate cards** — control HVAC mode (recovery, ventilation, off) from your HA dashboard
- **Fan speed control** — set fan speed (low, medium, high, boost) per unit
- **Automations** — turn on boost ventilation when cooking, switch to night mode at bedtime, lower fan when nobody's home, trigger ventilation based on humidity thresholds
- **Multi-unit visibility** — see all recuperators in one dashboard instead of checking each room in the i-Vent app

## Installation

### HACS (Manual Repository)

1. In HACS, go to Integrations → ⋮ → Custom Repositories
2. Add this repository URL, category: Integration
3. Install "i-Vent Rekuperator"
4. Restart Home Assistant
5. Go to Settings → Devices & Services → Add Integration → i-Vent
6. Enter device IP and session token

### Manual

1. Copy `custom_components/ivent/` to your HA `config/custom_components/` directory
2. Restart Home Assistant
3. Add integration via Settings → Devices & Services

## Entities

Each i-Vent unit creates the following entities:

| Platform | Entity | Description |
|----------|--------|-------------|
| `climate` | i-Vent {name} | HVAC mode, target temperature, fan speed, presets |
| `fan` | {name} Ventilator | Fan speed control (low/medium/high/boost) |
| `sensor` | Dovod temperatura | Supply duct temperature (°C) |
| `sensor` | Odvod temperatura | Exhaust/extract duct temperature (°C) |
| `sensor` | Vlažnost | Humidity (%) |
| `sensor` | Filter | Filter status |

## Current Status

**Read-only sensors are fully working.** The integration polls each unit and exposes real-time temperature, humidity, fan state, and HVAC mode.

**Control commands are not yet functional.** The device acknowledges control packets but does not apply the changes. Further protocol analysis is needed — see Roadmap below.

## Roadmap

- [ ] **Control commands** — reverse-engineer the full control protocol so HA can set mode, fan speed, and target temperature
- [ ] **Multi-device testing** — the integration supports multiple units structurally, but only one unit has been tested so far
- [ ] **CO2 sensor** — requires i-Qube hardware module; field mapping unknown
- [ ] **Outdoor/indoor temperature** — sensor fields exist but contain computed differentials, not direct readings; needs further analysis
- [ ] **HACS default repository** — submit to HACS default repo once control is stable

## License

MIT
