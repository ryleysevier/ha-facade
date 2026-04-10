# Changelog

## 1.2.0

- **Entity picker web UI** — ingress-based config panel accessible from the HA sidebar. Browse all HA entities by domain, search, and toggle watch/ignore per entity. No more typing entity IDs manually.
- Ingress enabled with sidebar icon (`mdi:emoticon-outline`)
- Entity config persisted in `/data/entity_config.json`, takes priority over add-on options
- Web UI config feeds into `should_watch()` filter

## 1.1.1

- **Event-based need modifiers** — 60+ smart home events now affect pet needs (not just face changes). Someone arriving home lowers loneliness, music playing reduces boredom, thunderstorms scare the pet, etc.
- Stable MQTT Discovery unique IDs anchored to device ID — no more `_2`/`_3` suffixes on reinstall
- Entity names shortened (device provides context)
- Improved self-watch filter — ignores both `facade` and `dweller` entity patterns

## 1.1.0

- Stable MQTT Discovery IDs anchored to device ID
- Self-watch filter improved
- Default brain model corrected

## 1.0.9

- Dashboard card tolerates HA entity ID suffixes dynamically

## 1.0.8

- Fix brain model ID (`claude-sonnet-4-5-20241022`) — previous ID returned 404
- Auto-ignore own MQTT Discovery sensors to prevent self-triggering Haiku calls
- Update Lovelace resource cache-busting

## 1.0.7

- Align MQTT topics with ESP32 firmware (`facade/*` without `/command/` prefix)
- Default topic prefix changed to `facade`
- Subscribe to `facade/#` to catch all subtopics
- Entity IDs derived from topic prefix

## 1.0.6

- Fix card JS install path to `/homeassistant/www/` (homeassistant_config mount point)

## 1.0.5

- Add `homeassistant_config` map so add-on can write to `/config/www/`

## 1.0.4

- Use `#!/usr/bin/with-contenv bashio` shebang to inject `SUPERVISOR_TOKEN`
- Matches pattern used by official HA add-ons (git_pull, duckdns)

## 1.0.3

- Wait for HA Core to be ready before connecting websocket
- Exponential backoff on WS reconnect (5s → 60s max)
- "Add to Home Assistant" install button in README
- OCI container labels in Dockerfile
- MIT license

## 1.0.2

- Add `init: false` to resolve s6-overlay PID 1 conflict with tini

## 1.0.1

- Add needs engine (hunger, boredom, loneliness, energy) with configurable decay rates
- Persistent pet state in `/data/pet_state.json`
- Feed/pet/play commands via MQTT
- Configurable pet name and personality
- Quiet hours and rate limiting
- Idle mood expressions when needs go critical
- Presence events affect loneliness
- Status publishing with need levels (retained)
- Mood history tracking

## 1.0.0

- Initial release
- Two-tier AI pipeline: Haiku filter → Sonnet brain
- HA websocket event bus listener
- MQTT face command publishing
- Configurable entity domain/ID filtering
- Debounce
