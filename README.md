# Facade

A Home Assistant add-on that brings a dweller ESP32 to life — a virtual pet with needs, personality, and AI-powered reactions to your smart home.

```
HA Event Bus ──→ Haiku Filter ──→ Sonnet Brain ──→ MQTT ──→ ESP32
                 "Worth it?"      "What face?"      dweller/mood
         ┌──────────────────────────────────────────────┐
         │  Pet State Engine                            │
         │  hunger · boredom · loneliness · energy      │
         │  persistent state · quiet hours · rate limit │
         └──────────────────────────────────────────────┘
```

## How it works

- **Needs engine** — hunger, boredom, loneliness, and energy decay over time. Happiness is derived from how well the pet's needs are met. Feed, pet, and play with it via MQTT commands.
- **AI brain** — events are filtered through Claude Haiku (cheap, fast), then interesting ones are evaluated by Claude Sonnet with full home context + pet needs to pick the right face.
- **Personality** — configurable name and traits that shape how the brain picks expressions.
- **Quiet hours** — no face changes during sleep hours.
- **Rate limiting** — max face changes per hour prevents runaway API costs.
- **Persistence** — pet state survives reboots.
- **Idle moods** — if a need gets critical and nothing has happened for 30 min, the pet expresses it on its own.

## Installation

1. Add this repository to Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add URL: `https://github.com/ryleysevier/ha-facade`
3. Install the **Facade** add-on
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
| `mqtt_topic_prefix` | `dweller` | MQTT topic prefix |
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

## MQTT Topics

### Published by the add-on

| Topic | Payload | Description |
|-------|---------|-------------|
| `dweller/mood` | `{"name": "happy"}` | Preset mood name |
| `dweller/pad` | `{"p": 80, "a": 50, "d": 50}` | PAD emotion values |
| `dweller/face` | Full parametric JSON | Custom expression with icon/fx |
| `dweller/status` | `{"name": "Buddy", "mood": "happy", "hunger": 23, ...}` | Pet status (retained) |

### Commands (subscribe to interact)

| Topic | Payload | Description |
|-------|---------|-------------|
| `dweller/command/feed` | *(any)* | Feed the pet (-30 hunger) |
| `dweller/command/pet` | *(any)* | Pet it (-25 loneliness) |
| `dweller/command/play` | *(any)* | Play with it (-35 boredom, -10 energy) |
| `dweller/command/mood` | `{"name": "excited"}` | Override mood directly |

## Home Assistant Entities

The add-on auto-creates entities via MQTT Discovery. No custom component needed.

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

### Buttons
| Entity | Description |
|--------|-------------|
| `button.feed_buddy` | Feed the pet (-30 hunger) |
| `button.pet_buddy` | Pet it (-25 loneliness) |
| `button.play_buddy` | Play with it (-35 boredom) |

### Select
| Entity | Description |
|--------|-------------|
| `select.dweller_mood_override` | Manually set a mood |

All entities are grouped under a single **Dweller** device in HA.

## Dashboard Card

The add-on automatically installs a custom Lovelace card on startup — copies the JS to `/config/www/` and registers it as a resource. Just add it to a dashboard:

```yaml
type: custom:dweller-card
name: Buddy
entity_prefix: dweller
```

The card shows:
- Pet name and mood emoji
- Current mood with reason
- Alert banner when a need is critical
- Need bars (hunger, boredom, loneliness, energy, happiness) with color coding
- Feed / Pet / Play buttons

## Cost

- **Haiku filter**: ~100-300 calls/day × $0.001 = $0.10-0.30/day
- **Brain**: ~5-20 calls/day × $0.01-0.05 = $0.05-1.00/day
- **Total**: ~$5-40/month
