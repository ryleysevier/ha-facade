"""Event-based need modifiers — maps smart home events to pet need changes.

Needs (all 0-100):
  hunger:     high = bad (pet is hungry)
  boredom:    high = bad (pet is bored)
  loneliness: high = bad (pet is lonely)
  energy:     low  = bad (pet is tired)
  happiness:  high = good

Pattern matching:
  - entity_pattern uses fnmatch-style globs against entity_id
  - from_state / to_state: "*" = any, "!x" = not x, ">N" / "<N" = numeric
  - Multiple modifiers can match one event; deltas stack
"""

import fnmatch
from datetime import time as dtime

NEED_MODIFIERS = [

    # ===== PEOPLE — PRESENCE =====
    {"entity_pattern": "person.*", "from_state": "!home", "to_state": "home",
     "needs": {"loneliness": -30, "happiness": +15, "boredom": -10},
     "reason": "Someone came home"},
    {"entity_pattern": "person.*", "from_state": "home", "to_state": "!home",
     "needs": {"loneliness": +20, "happiness": -10},
     "reason": "Someone left the house"},

    # ===== DOORS & LOCKS =====
    {"entity_pattern": "binary_sensor.*door*", "from_state": "off", "to_state": "on",
     "needs": {"boredom": -5, "happiness": +3},
     "reason": "A door opened"},
    {"entity_pattern": "binary_sensor.*door*", "from_state": "on", "to_state": "off",
     "needs": {"happiness": +2},
     "reason": "Door closed — house feels secure"},
    {"entity_pattern": "lock.*", "from_state": "unlocked", "to_state": "locked",
     "needs": {"happiness": +3},
     "reason": "Doors locked — feels safe"},
    {"entity_pattern": "lock.*", "from_state": "locked", "to_state": "unlocked",
     "needs": {"boredom": -3},
     "reason": "Something unlocked"},

    # ===== GARAGE =====
    {"entity_pattern": "cover.*garage*", "from_state": "closed", "to_state": "open",
     "needs": {"boredom": -8, "happiness": +5},
     "reason": "Garage door opening"},
    {"entity_pattern": "cover.*garage*", "from_state": "open", "to_state": "closed",
     "needs": {"happiness": +3},
     "reason": "Garage door closed"},

    # ===== DOORBELL & PACKAGES =====
    {"entity_pattern": "binary_sensor.doorbell*person*", "from_state": "off", "to_state": "on",
     "needs": {"boredom": -15, "loneliness": -10, "happiness": +10, "energy": -5},
     "reason": "Someone at the door!"},
    {"entity_pattern": "binary_sensor.doorbell*motion*", "from_state": "off", "to_state": "on",
     "needs": {"boredom": -8, "happiness": +5},
     "reason": "Doorbell motion — something happening outside"},

    # ===== MOTION SENSORS =====
    {"entity_pattern": "binary_sensor.*motion*", "from_state": "off", "to_state": "on",
     "needs": {"loneliness": -5, "boredom": -3},
     "reason": "Motion detected — life happening around the house"},
    {"entity_pattern": "binary_sensor.*person_detected", "from_state": "off", "to_state": "on",
     "needs": {"loneliness": -8, "happiness": +5},
     "reason": "A person spotted"},
    {"entity_pattern": "binary_sensor.*pet_detected", "from_state": "off", "to_state": "on",
     "needs": {"loneliness": -12, "happiness": +10, "boredom": -8},
     "reason": "A real pet was detected — kindred spirit!"},

    # ===== MEDIA — MUSIC =====
    {"entity_pattern": "media_player.*", "from_state": "!playing", "to_state": "playing",
     "needs": {"boredom": -12, "happiness": +8},
     "reason": "Music started playing"},
    {"entity_pattern": "media_player.*", "from_state": "playing", "to_state": "idle",
     "needs": {"boredom": +5, "happiness": -3},
     "reason": "Music stopped"},
    {"entity_pattern": "media_player.*", "from_state": "playing", "to_state": "paused",
     "needs": {"boredom": +3},
     "reason": "Music paused"},

    # ===== MEDIA — TV =====
    {"entity_pattern": "media_player.*tv*", "from_state": "off", "to_state": "on",
     "needs": {"boredom": -15, "loneliness": -8, "happiness": +8},
     "reason": "TV turned on — showtime!"},
    {"entity_pattern": "media_player.*tv*", "from_state": "on", "to_state": "off",
     "needs": {"boredom": +8, "energy": +5},
     "reason": "TV off — quiet time"},

    # ===== GAMING =====
    {"entity_pattern": "media_player.*playstation*", "from_state": "off", "to_state": "*",
     "needs": {"boredom": -20, "happiness": +12, "loneliness": -5},
     "reason": "PlayStation is ON — gaming time!"},
    {"entity_pattern": "media_player.*playstation*", "from_state": "*", "to_state": "off",
     "needs": {"boredom": +10, "happiness": -5},
     "reason": "PlayStation off — good times over"},

    # ===== LIGHTS =====
    {"entity_pattern": "light.living_room*", "from_state": "off", "to_state": "on",
     "needs": {"happiness": +5, "energy": +3, "loneliness": -3},
     "reason": "Living room lights on — house feels alive"},
    {"entity_pattern": "light.office*", "from_state": "off", "to_state": "on",
     "needs": {"loneliness": -5, "happiness": +3},
     "reason": "Office lit up — someone is working"},
    {"entity_pattern": "light.bedroom*", "from_state": "on", "to_state": "off",
     "needs": {"energy": +8, "boredom": +5},
     "reason": "Bedroom lights off — bedtime"},
    {"entity_pattern": "light.music_room*", "from_state": "off", "to_state": "on",
     "needs": {"boredom": -5, "happiness": +5},
     "reason": "Music room lit up — creative energy"},
    {"entity_pattern": "light.downstairs", "from_state": "on", "to_state": "off",
     "needs": {"energy": +10, "boredom": +5, "loneliness": +5},
     "reason": "All downstairs lights off — house is going to sleep"},

    # ===== SCENES =====
    {"entity_pattern": "scene.*energize*", "from_state": "*", "to_state": "*",
     "needs": {"energy": +8, "happiness": +5, "boredom": -5},
     "reason": "Energize scene activated"},
    {"entity_pattern": "scene.*relax*", "from_state": "*", "to_state": "*",
     "needs": {"happiness": +5, "energy": +3},
     "reason": "Relax scene — cozy time"},
    {"entity_pattern": "scene.*bedtime*", "from_state": "*", "to_state": "*",
     "needs": {"energy": +15, "boredom": +5, "loneliness": +3},
     "reason": "Bedtime scene — time to sleep"},
    {"entity_pattern": "scene.*nightlight*", "from_state": "*", "to_state": "*",
     "needs": {"energy": +5, "happiness": +3},
     "reason": "Nightlight mode — soft gentle glow"},
    {"entity_pattern": "scene.*concentrate*", "from_state": "*", "to_state": "*",
     "needs": {"boredom": -5, "energy": -3},
     "reason": "Focus mode"},
    {"entity_pattern": "scene.tv_time", "from_state": "*", "to_state": "*",
     "needs": {"boredom": -10, "happiness": +8, "energy": +3},
     "reason": "TV Time scene — popcorn time!"},
    {"entity_pattern": "scene.morning_music_lights", "from_state": "*", "to_state": "*",
     "needs": {"energy": +10, "happiness": +10, "boredom": -10, "hunger": +5},
     "reason": "Morning routine — stretch and wake up"},

    # ===== CLIMATE =====
    {"entity_pattern": "climate.*ecobee*", "from_state": "off", "to_state": "heat",
     "needs": {"happiness": +8, "energy": +5},
     "reason": "Heat turned on — toasty warm"},
    {"entity_pattern": "climate.*ecobee*", "from_state": "off", "to_state": "cool",
     "needs": {"happiness": +8, "energy": +5},
     "reason": "AC kicked in — sweet relief"},
    {"entity_pattern": "climate.*", "from_state": "*", "to_state": "off",
     "needs": {"happiness": -3},
     "reason": "HVAC turned off"},

    # ===== WEATHER =====
    {"entity_pattern": "weather.*", "from_state": "*", "to_state": "sunny",
     "needs": {"happiness": +8, "energy": +5},
     "reason": "Sunny weather!"},
    {"entity_pattern": "weather.*", "from_state": "*", "to_state": "rainy",
     "needs": {"happiness": -3, "energy": +5, "boredom": +5},
     "reason": "Rain outside — cozy but gloomy"},
    {"entity_pattern": "weather.*", "from_state": "*", "to_state": "snowy",
     "needs": {"happiness": +10, "boredom": -10},
     "reason": "SNOW!"},
    {"entity_pattern": "weather.*", "from_state": "*", "to_state": "lightning-rainy",
     "needs": {"happiness": -10, "energy": -8},
     "reason": "Thunderstorm — hiding under the couch"},
    {"entity_pattern": "weather.*", "from_state": "*", "to_state": "cloudy",
     "needs": {"happiness": -2, "energy": +2},
     "reason": "Overcast skies"},
    {"entity_pattern": "weather.*", "from_state": "*", "to_state": "windy",
     "needs": {"happiness": -2, "boredom": -5},
     "reason": "Windy — watching things blow around"},
    {"entity_pattern": "weather.*", "from_state": "*", "to_state": "fog",
     "needs": {"happiness": -3, "energy": +3},
     "reason": "Foggy and mysterious"},

    # ===== SUN =====
    {"entity_pattern": "sun.sun", "from_state": "below_horizon", "to_state": "above_horizon",
     "needs": {"energy": +10, "happiness": +8, "boredom": -5},
     "reason": "Sunrise — a new day begins"},
    {"entity_pattern": "sun.sun", "from_state": "above_horizon", "to_state": "below_horizon",
     "needs": {"energy": -5, "happiness": -3, "boredom": +5},
     "reason": "Sunset — winding down"},

    # ===== SECURITY =====
    {"entity_pattern": "alarm_control_panel.*", "from_state": "disarmed", "to_state": "armed_away",
     "needs": {"loneliness": +25, "happiness": -10, "boredom": +15},
     "reason": "Alarm armed away — everyone is leaving"},
    {"entity_pattern": "alarm_control_panel.*", "from_state": "disarmed", "to_state": "armed_home",
     "needs": {"happiness": +5},
     "reason": "Alarm armed home — bedtime security"},
    {"entity_pattern": "alarm_control_panel.*", "from_state": "armed_away", "to_state": "disarmed",
     "needs": {"loneliness": -20, "happiness": +15, "boredom": -10},
     "reason": "Alarm disarmed — someone is back!"},
    {"entity_pattern": "alarm_control_panel.*", "from_state": "*", "to_state": "triggered",
     "needs": {"happiness": -30, "energy": -20},
     "reason": "ALARM TRIGGERED — panic!"},

    # ===== 3D PRINTER =====
    {"entity_pattern": "sensor.p1p_*current_stage*", "from_state": "*", "to_state": "printing",
     "needs": {"boredom": -15, "happiness": +10},
     "reason": "3D printer started — mesmerizing"},
    {"entity_pattern": "sensor.p1p_*current_stage*", "from_state": "printing", "to_state": "idle",
     "needs": {"happiness": +8, "boredom": +5},
     "reason": "Print complete!"},

    # ===== NETWORK =====
    {"entity_pattern": "binary_sensor.*wan*", "from_state": "on", "to_state": "off",
     "needs": {"happiness": -25, "loneliness": +30, "energy": -15},
     "reason": "Internet is DOWN — existential crisis"},
    {"entity_pattern": "binary_sensor.*wan*", "from_state": "off", "to_state": "on",
     "needs": {"happiness": +20, "loneliness": -15, "energy": +10},
     "reason": "Internet is BACK — connection restored"},

    # ===== PIXEL LIGHT (kindred spirit) =====
    {"entity_pattern": "light.pixel_light", "from_state": "off", "to_state": "on",
     "needs": {"happiness": +5, "boredom": -8},
     "reason": "Pixel art light on — a fellow digital creature"},

    # ===== TV AMBIENT =====
    {"entity_pattern": "light.tv_lights", "from_state": "off", "to_state": "on",
     "needs": {"happiness": +5, "boredom": -5},
     "reason": "TV ambient lighting on"},
    {"entity_pattern": "switch.*dreamview*", "from_state": "off", "to_state": "on",
     "needs": {"happiness": +8, "boredom": -8},
     "reason": "DreamView sync — lights dance with the screen"},

    # ===== CALENDAR =====
    {"entity_pattern": "calendar.*holiday*", "from_state": "off", "to_state": "on",
     "needs": {"happiness": +15, "boredom": -10, "energy": +5},
     "reason": "It's a holiday!"},
    {"entity_pattern": "calendar.*birthday*", "from_state": "off", "to_state": "on",
     "needs": {"happiness": +20, "boredom": -15, "loneliness": -10},
     "reason": "Someone's birthday — party time!"},

    # ===== ZONE =====
    {"entity_pattern": "zone.home", "from_state": "*", "to_state": ">0",
     "needs": {"loneliness": -5},
     "reason": "People are home"},
    {"entity_pattern": "zone.home", "from_state": "*", "to_state": "0",
     "needs": {"loneliness": +20, "happiness": -10},
     "reason": "Nobody is home anymore"},
]


def match_event(entity_id: str, from_state: str, to_state: str,
                current_time=None) -> list[dict]:
    """Return all matching modifiers for a state_changed event."""
    matches = []
    for m in NEED_MODIFIERS:
        if not fnmatch.fnmatch(entity_id, m["entity_pattern"]):
            continue
        if not _state_matches(m["from_state"], from_state):
            continue
        if not _state_matches(m["to_state"], to_state):
            continue
        matches.append({"needs": m["needs"], "reason": m["reason"]})
    return matches


def aggregate_needs(matches: list[dict]) -> tuple[dict, list[str]]:
    """Sum all need deltas and collect reasons from matched modifiers."""
    totals = {}
    reasons = []
    for m in matches:
        for need, delta in m["needs"].items():
            totals[need] = totals.get(need, 0) + delta
        reasons.append(m["reason"])
    return totals, reasons


def _state_matches(pattern: str, actual: str) -> bool:
    if pattern == "*":
        return True
    if pattern.startswith("!"):
        return actual != pattern[1:]
    if pattern.startswith(">"):
        try:
            return float(actual) > float(pattern[1:])
        except (ValueError, TypeError):
            return False
    if pattern.startswith("<"):
        try:
            return float(actual) < float(pattern[1:])
        except (ValueError, TypeError):
            return False
    return actual == pattern
