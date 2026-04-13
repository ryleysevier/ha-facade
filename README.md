# Facade

[![Add to Home Assistant](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=47772387_facade&repository_url=https%3A%2F%2Fgithub.com%2Fryleysevier%2Fha-facade)
[![GitHub Release](https://img.shields.io/github/v/release/ryleysevier/ha-facade)](https://github.com/ryleysevier/ha-facade/releases)
[![License](https://img.shields.io/github/license/ryleysevier/ha-facade)](LICENSE)

A Home Assistant add-on that powers a virtual pet living on a round ESP32 screen. The pet watches your smart home, reacts to events with expressive cartoon eyes, and has needs that decay over time — feed it, pet it, play with it, or it gets grumpy.

<!-- TODO: Add screenshots here -->

## How it works

```
HA Events → Entity Filter → Rules Engine → MQTT → ESP32 Display
                                  │
                          (no match?)
                                  │
                          AI Escalation (optional, budget-capped)
```

1. **Home Assistant events** stream in via websocket
2. **Entity filter** (configurable in the web UI) drops noisy entities
3. **Rules engine** matches events against `reactions.json` — instant, zero API calls
4. **MQTT** publishes face commands to the ESP32 display
5. **AI escalation** (optional) handles novel events via Claude Opus, budget-capped at N/day

The rules engine ships with 30 default rules and can be customized by exporting your HA data and generating rules tailored to your specific home.

## Features

- **Rules engine** — event-to-face mapping with per-rule cooldowns, priority resolution, and zero API cost
- **Needs system** — hunger, boredom, loneliness, and energy decay over time. Happiness is derived from how well needs are met
- **Interactions** — feed, pet, and play via HA buttons or MQTT
- **Event-based need modifiers** — someone arriving home lowers loneliness, music reduces boredom, storms scare the pet
- **AI escalation** — optionally route unknown events to Claude Opus (budget-capped, disabled by default)
- **Quiet hours** — no face changes while you sleep
- **Persistence** — pet state survives reboots
- **Idle moods** — the pet expresses unmet needs on its own if nothing happens for 30 min
- **HA entities** — sensors, buttons, and selects auto-created via MQTT Discovery
- **Dashboard card** — custom Lovelace card with need bars, mood emoji, and interaction buttons
- **Web UI** — entity picker and rules management via HA sidebar (ingress)
- **Data export** — export 30 days of HA entity data for batch rule generation

## Installation

Click the badge above, or:

1. **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add `https://github.com/ryleysevier/ha-facade`
3. Install **Facade**, configure MQTT credentials
4. Start the add-on

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `anthropic_api_key` | | Anthropic API key (only needed for AI escalation) |
| `mqtt_host` | `core-mosquitto` | MQTT broker hostname |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_user` | `facade` | MQTT username |
| `mqtt_password` | | MQTT password |
| `mqtt_topic_prefix` | `facade` | MQTT topic prefix |
| `pet_name` | `Buddy` | Your pet's name |
| `quiet_hours_start` | `23:00` | Start of quiet hours |
| `quiet_hours_end` | `06:00` | End of quiet hours |
| `escalation_enabled` | `true` | Enable AI escalation for unmatched events |
| `escalation_budget_per_day` | `10` | Max AI calls per day |
| `escalation_model` | `claude-opus-4-20250514` | Model for AI escalation |
| `need_decay_rates` | | Per-second decay rates for hunger, boredom, loneliness, energy |
| `log_level` | `info` | Logging verbosity |

## HA Entities

Auto-created via MQTT Discovery. All grouped under a **Facade** device.

| Entity | Type | Description |
|--------|------|-------------|
| `sensor.facade_buddy_hunger` | Sensor | Hunger level (0-100%) |
| `sensor.facade_buddy_boredom` | Sensor | Boredom level (0-100%) |
| `sensor.facade_buddy_loneliness` | Sensor | Loneliness level (0-100%) |
| `sensor.facade_buddy_energy` | Sensor | Energy level (0-100%) |
| `sensor.facade_buddy_happiness` | Sensor | Happiness level (0-100%) |
| `sensor.facade_buddy_mood` | Sensor | Current mood name |
| `sensor.facade_buddy_mood_reason` | Sensor | Why the mood changed |
| `sensor.facade_buddy_dominant_need` | Sensor | Most urgent need |
| `button.facade_buddy_feed` | Button | Feed the pet |
| `button.facade_buddy_pet` | Button | Pet it |
| `button.facade_buddy_play` | Button | Play with it |
| `select.facade_buddy_mood_override` | Select | Set mood manually |

## Dashboard Card

The add-on installs a custom Lovelace card automatically. Add it to any dashboard:

```yaml
type: custom:dweller-card
name: Buddy
entity_prefix: facade_buddy
```

<!-- TODO: Add card screenshot -->

## Web UI

Access via the **Facade** icon in the HA sidebar.

- **Entities** — browse all HA entities, toggle watch/ignore per entity or entire domain
- **Rules** — view loaded rules, import/export `reactions.json`, trigger data export, view unmatched events and escalation budget

## Customizing Rules

The add-on ships with 30 default rules. To generate rules tailored to your home:

1. Open the web UI → **Rules** → **Export HA Data**
2. Download the export file
3. Feed it to Claude Code or the Anthropic API with the batch learning prompt
4. Copy the generated `reactions.json` back into the web UI via **Import Rules**

Rules are matched using fnmatch patterns with support for negation (`!home`), numeric comparison (`>80`, `<20`), and wildcards (`*`).

## MQTT Topics

All topics use the configured prefix (default: `facade`).

| Topic | Direction | Description |
|-------|-----------|-------------|
| `facade/mood` | Out | Preset mood: `{"name": "happy"}` |
| `facade/pad` | Out | PAD values: `{"p": 80, "a": 50, "d": 50}` |
| `facade/face` | Out | Full parametric face command |
| `facade/status` | Out | Pet status JSON (retained) |
| `facade/feed` | In | Feed the pet |
| `facade/pet` | In | Pet it |
| `facade/play` | In | Play with it |
| `facade/reload` | In | Hot-reload rules engine |
| `facade/export` | In | Trigger HA data export |

## Hardware

This add-on is the brain. The display is a separate ESP32 project:

**[ha-facade-dweller](https://github.com/ryleysevier/ha-facade-dweller)** — ESP32 firmware for the 1.28" round GC9A01 display. 200 mood presets, PAD-driven procedural eye rendering, emoji animations. Subscribes to `facade/*` MQTT topics.

## License

MIT
