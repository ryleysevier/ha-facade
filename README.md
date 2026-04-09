# Facade

A Home Assistant add-on that gives a tamagotchi ESP32 expressive face reactions to your smart home events.

```
HA Event Bus → Haiku Filter → Opus/Sonnet Brain → MQTT → ESP32 Tamagotchi
               "Worth it?"     "What face?"        tamagotchi/mood
```

## How it works

1. **Listens** to Home Assistant's event bus for state changes (doors, presence, weather, media, etc.)
2. **Filters** each event through Claude Haiku — cheap and fast, decides if the event is interesting enough to react to (~90% are dropped)
3. **Thinks** with Claude Sonnet/Opus — given full home context (who's home, weather, recent events, time of day), picks the right facial expression
4. **Publishes** the face command via MQTT to the ESP32 tamagotchi device

## Installation

1. Add this repository to Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add URL: `https://github.com/ryleysevier/facade`
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
| `debounce_seconds` | `30` | Minimum seconds between face changes |
| `haiku_model` | `claude-haiku-4-5-20251001` | Filter model |
| `brain_model` | `claude-sonnet-4-6-20250514` | Brain model |
| `watched_domains` | binary_sensor, climate, cover, light, media_player, person, sensor, sun, zone | Entity domains to monitor |
| `watched_entities` | `[]` | Specific entity IDs to always watch |
| `ignored_entities` | `[]` | Entity IDs to never watch |
| `log_level` | `info` | Logging level |

## MQTT Topics

| Topic | Payload | When |
|-------|---------|------|
| `tamagotchi/mood` | `{"name": "happy"}` | Preset mood name |
| `tamagotchi/pad` | `{"p": 80, "a": 50, "d": 50}` | PAD emotion values |
| `tamagotchi/face` | Full parametric JSON | Custom expression with icon/fx |

## Cost

- **Haiku filter**: ~100-300 calls/day × $0.001 = $0.10-0.30/day
- **Brain**: ~5-20 calls/day × $0.01-0.05 = $0.05-1.00/day
- **Total**: ~$5-40/month
