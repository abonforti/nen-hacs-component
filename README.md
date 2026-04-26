# NeN Energy for Home Assistant

![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5?logo=homeassistant)
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2026.4.4%2B-41BDF5?logo=homeassistant)
![License](https://img.shields.io/badge/License-MIT-green)

Integrates the Italian energy provider NeN (nen.it) into Home Assistant via their unofficial API.

## What It Does

This integration polls NeN's API every 6 hours and exposes sensors for electricity and gas account monitoring, including year-to-date consumption, daily/monthly readings, subscription fees, and commodity unit prices. Data is pulled directly from your active NeN account.

## Sensors

| Sensor | Description | Unit |
|---|---|---|
| Consumption YTD | Year-to-date consumption | kWh / m³ |
| Last Day Consumption | Latest smart meter daily reading (electricity only) | kWh |
| Last Month Consumption | Latest distributor monthly reading (gas only) | m³ |
| Monthly Rate | Current monthly subscription fee | EUR |
| Unit Price | Current commodity unit price | EUR/kWh or EUR/m³ |

## Requirements

- Home Assistant 2026.4.4 or later
- Active NeN account at [nen.it](https://www.nen.it)

## Installation

### HACS (Recommended)

1. Open Home Assistant → Settings → Integrations
2. Click **Create Automation** → select **HACS**
3. In the HACS panel, click **⋯** → **Custom repositories**
4. Add repository URL: `https://github.com/abonforti/nen-hacs-component`
5. Select **Integration** and click **Create**
6. Search for "NeN Energy" and install

### Manual

1. Download this repository
2. Copy `custom_components/nen/` to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Navigate to Settings → Devices & Services → Integrations
2. Click **Create Integration** and search for "NeN Energy"
3. Enter your NeN account email and password
4. Sensors will be created for each contract/pod in your account

## Energy Dashboard Integration

These sensors expose account-level data (consumption totals, billing info). They are **not suitable as primary sources** for the Home Assistant Energy Dashboard.

For grid consumption:
- **Electricity**: use a real-time clamp meter (e.g., Shelly EM) paired with the NeN Energy sensors as sanity checks
- **Gas**: manual monthly readings from your distributor (NeN does not provide real-time gas consumption)

YTD sensors are useful for detecting anomalies or validating billing accuracy.

## Roadmap / TODO

- [ ] **Il Robo integration**: NeN's AI-based consumption optimization feature (`isRoboActive` field). The author does not have this feature enabled. Pull requests welcome from users who do.
- [ ] Contract renewal date sensor

## Disclaimer

*This integration is not affiliated with or endorsed by NeN S.r.l. It uses NeN's unofficial API, which may change without notice. Use at your own risk.*

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
