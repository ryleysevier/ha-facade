# Facade

[![Add to Home Assistant](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=47772387_facade&repository_url=https%3A%2F%2Fgithub.com%2Fryleysevier%2Fha-facade)
[![GitHub Release](https://img.shields.io/github/v/release/ryleysevier/ha-facade)](https://github.com/ryleysevier/ha-facade/releases)
[![License](https://img.shields.io/github/license/ryleysevier/ha-facade)](LICENSE)

A Home Assistant add-on that brings a virtual pet to life — a dweller with needs, personality, and AI-powered reactions to your smart home events, displayed on an ESP32 screen via MQTT.

```
HA Event Bus ──> Haiku Filter ──> Sonnet Brain ──> MQTT ──> ESP32
                 "Worth it?"      "What face?"     facade/mood
         ┌──────────────────────────────────────────────┐
         │  Pet State Engine                            │
         │  hunger · boredom · loneliness · energy      │
         │  persistent state · quiet hours · rate limit │
         └──────────────────────────────────────────────┘
```

## Features

- **Needs engine** — hunger, boredom, loneliness, and energy decay over time. Happiness is derived from how well the pet's needs are met.
- **AI brain** — events are filtered through Claude Haiku (cheap, fast), then interesting ones are evaluated by Claude Sonnet with full home context + pet needs to pick the right face. AI is optional — a rules engine fallback is planned.
- **Personality** — configurable name and traits that shape how the brain picks expressions.
- **Interactions** — feed, pet, and play with your dweller via MQTT commands or HA buttons.
- **Quiet hours** — no face changes during sleep hours.
- **Rate limiting** — max face changes per hour prevents runaway API costs.
- **Persistence** — pet state survives reboots.
- **Idle moods** — if a need gets critical and nothing has happened for 30 min, the pet expresses it on its own.
- **HA entities** — sensors, buttons, and selects auto-created via MQTT Discovery. No custom component needed.
- **Dashboard card** — auto-installed Lovelace card with need bars, mood display, and interaction buttons.

## Installation

Click the button above, or manually:

1. Go to **Settings > Add-ons > Add-on Store > ⋮ > Repositories**
2. Add: `https://github.com/ryleysevier/ha-facade`
3. Install **Facade**
4. Configure your Anthropic API key and MQTT credentials
5. Start the add-on

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `anthropic_api_key` | | Your Anthropic API key |
| `mqtt_host` | `core-mosquitto` | MQTT broker hostname |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_user` | `facade` | MQTT username |
| `mqtt_password` | | MQTT password |
| `mqtt_topic_prefix` | `facade` | MQTT topic prefix |
| `pet_name` | `Buddy` | Your pet's name |
| `personality` | `curious, empathetic, slightly dramatic` | Personality traits for the AI brain |
| `debounce_seconds` | `30` | Minimum seconds between AI evaluations |
| `max_changes_per_hour` | `12` | Rate limit on face changes |
| `quiet_hours_start` | `23:00` | Start of quiet hours (no face changes) |
| `quiet_hours_end` | `06:00` | End of quiet hours |
| `haiku_model` | `claude-haiku-4-5-20251001` | Filter model |
| `brain_model` | `claude-sonnet-4-6-20250514` | Brain model |
| `need_decay_rates` | hunger: 0.014, boredom: 0.055, loneliness: 0.028, energy: -0.008 | Need decay per second |
| `watched_domains` | binary_sensor, climate, cover, light, media_player, person, sensor, sun, zone | Entity domains to monitor |
| `watched_entities` | `[]` | Specific entity IDs to always watch |
| `ignored_entities` | `[]` | Entity IDs to never watch |
| `log_level` | `info` | Logging level |

## Home Assistant Entities

Auto-created via MQTT Discovery on startup. All grouped under a **Dweller** device.

### Sensors

| Entity | Description |
|--------|-------------|
| `sensor.dweller_hunger` | Hunger level (0-100%) |
| `sensor.dweller_boredom` | Boredom level (0-100%) |
| `sensor.dweller_loneliness` | Loneliness level (0-100%) |
| `sensor.dweller_energy` | Energy level (0-100%) |
| `sensor.dweller_happiness` | Happiness level (0-100%) |
| `sensor.dweller_mood` | Current mood name |
| `sensor.dweller_mood_reason` | Why the mood changed |
| `sensor.dweller_dominant_need` | Most urgent need (or "none") |

### Buttons & Select

| Entity | Description |
|--------|-------------|
| `button.feed_buddy` | Feed the pet (-30 hunger) |
| `button.pet_buddy` | Pet it (-25 loneliness) |
| `button.play_buddy` | Play with it (-35 boredom) |
| `select.dweller_mood_override` | Manually set a mood |

## Dashboard Card

Auto-installed on startup — the add-on copies `dweller-card.js` to `/config/www/` and registers it as a Lovelace resource. Add to any dashboard:

```yaml
type: custom:dweller-card
name: Buddy
entity_prefix: dweller
```

Shows need bars with color-coded thresholds, mood emoji, critical need alerts, and feed/pet/play buttons.

## MQTT Topics

All topics use the configurable prefix (default: `facade`).

### Published by the add-on

| Topic | Payload | Description |
|-------|---------|-------------|
| `facade/mood` | `{"name": "happy"}` | Preset mood name |
| `facade/pad` | `{"p": 80, "a": 50, "d": 50}` | PAD emotion values |
| `facade/face` | Full parametric JSON | Custom expression with icon/fx |
| `facade/status` | `{"name": "Buddy", "mood": "happy", "hunger": 23, ...}` | Pet status (retained) |

### Commands

| Topic | Payload | Description |
|-------|---------|-------------|
| `facade/feed` | *(any)* | Feed the pet |
| `facade/pet` | *(any)* | Pet it |
| `facade/play` | *(any)* | Play with it |
| `facade/mood_override` | `{"name": "excited"}` | Override mood (JSON) |
| `facade/mood_select` | `excited` | Override mood (string) |

## Related

- **[ha-facade-dweller](https://github.com/ryleysevier/ha-facade-dweller)** — ESP32 firmware for the physical display (CrowPanel GC9A01 round screen). The "dumb terminal" that renders face commands from this add-on.

## Cost

- **Haiku filter**: ~100-300 calls/day x $0.001 = $0.10-0.30/day
- **Brain**: ~5-20 calls/day x $0.01-0.05 = $0.05-1.00/day
- **Total**: ~$5-40/month

## License

MIT
