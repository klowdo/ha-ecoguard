# Ecoguard Insight

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Home Assistant integration for [Ecoguard Insight](https://insight.ecoguard.se) — scrapes electricity consumption and pricing data from your Ecoguard account.

## Features

- 12 months of historical electricity consumption (kWh and cost)
- Current month daily breakdown with running total
- Today's electricity usage
- Current electricity price per kWh
- All sensors grouped under a single device
- Automatic updates every hour

## Installation

### HACS (recommended)

1. Open HACS in Home Assistant
2. Click the three dots in the top right → **Custom repositories**
3. Add this repository URL with category **Integration**
4. Search for "Ecoguard Insight" and install
5. Restart Home Assistant

### Manual

Copy the `custom_components/ecoguard` folder to your Home Assistant `config/custom_components/` directory and restart.

## Setup

1. Go to **Settings → Integrations → Add Integration**
2. Search for **Ecoguard Insight**
3. Enter your credentials:
   - **Rentable Object Number** — e.g. `22-2087-1-361`
   - **Password**
   - **Database Name** — e.g. `HSBHisingsKärra`

## Sensors

| Sensor | Description | Unit |
|--------|-------------|------|
| Month 1–12 Name | Month label (e.g. "januari 2026") | — |
| Month 1–12 kWh | Monthly electricity consumption | kWh |
| Month 1–12 Cost | Monthly electricity cost | SEK |
| Current Month Total kWh | Running total for current month | kWh |
| Current Month Day Count | Days in current month data | days |
| Today kWh | Latest day's consumption | kWh |
| Price per kWh | Current electricity price | SEK/kWh |
| Price Valid From | Start date of current price | — |
