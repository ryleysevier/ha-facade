"""Facade — dweller pet manager for Home Assistant."""

import json
import logging
import os
import re
import threading
import time
from collections import deque
from datetime import datetime

import anthropic
import paho.mqtt.client as mqtt
import requests

from need_modifiers import match_event as match_need_modifiers, aggregate_needs
from web import start_web_server, load_entity_config, entity_config as web_entity_config

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OPTIONS_PATH = "/data/options.json"
STATE_PATH = "/data/pet_state.json"

def load_options():
    if os.path.exists(OPTIONS_PATH):
        with open(OPTIONS_PATH) as f:
            return json.load(f)
    return {}

OPTIONS = load_options()

ANTHROPIC_API_KEY = OPTIONS.get("anthropic_api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
MQTT_HOST = OPTIONS.get("mqtt_host", "core-mosquitto")
MQTT_PORT = OPTIONS.get("mqtt_port", 1883)
MQTT_USER = OPTIONS.get("mqtt_user", "facade")
MQTT_PASSWORD = OPTIONS.get("mqtt_password", "")
DEBOUNCE_SECONDS = OPTIONS.get("debounce_seconds", 30)
HAIKU_MODEL = OPTIONS.get("haiku_model", "claude-haiku-4-5-20251001")
BRAIN_MODEL = OPTIONS.get("brain_model", "claude-sonnet-4-5-20241022")
WATCHED_DOMAINS = set(OPTIONS.get("watched_domains", [
    "binary_sensor", "climate", "cover", "light",
    "media_player", "person", "sensor", "sun", "zone",
]))
WATCHED_ENTITIES = set(OPTIONS.get("watched_entities", []))
IGNORED_ENTITIES = set(OPTIONS.get("ignored_entities", []))
LOG_LEVEL = OPTIONS.get("log_level", "info").upper()
TOPIC_PREFIX = OPTIONS.get("mqtt_topic_prefix", "facade")
PET_NAME = OPTIONS.get("pet_name", "Buddy")
PERSONALITY = OPTIONS.get("personality", "curious, empathetic, slightly dramatic")
MAX_CHANGES_PER_HOUR = OPTIONS.get("max_changes_per_hour", 12)
QUIET_START = OPTIONS.get("quiet_hours_start", "23:00")
QUIET_END = OPTIONS.get("quiet_hours_end", "06:00")
NEED_DECAY = OPTIONS.get("need_decay_rates", {
    "hunger": 0.0015,     # ~3 feeds/day to maintain
    "boredom": 0.0012,    # ~2 play sessions/day
    "loneliness": 0.0016, # ~4 pets/day
    "energy": -0.0016,    # drains over ~17h active hours
})

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("facade")

# ---------------------------------------------------------------------------
# HA API
# ---------------------------------------------------------------------------

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_WS_URL = "ws://supervisor/core/websocket"
HA_REST_URL = "http://supervisor/core/api"

# ---------------------------------------------------------------------------
# Pet State
# ---------------------------------------------------------------------------

class PetState:
    """Persistent pet needs and mood state."""

    def __init__(self):
        self.hunger = 0.0       # 0 = full, 100 = starving
        self.boredom = 0.0      # 0 = entertained, 100 = bored out of mind
        self.loneliness = 0.0   # 0 = loved, 100 = abandoned
        self.energy = 100.0     # 100 = fully rested, 0 = exhausted
        self.happiness = 75.0   # 0 = miserable, 100 = ecstatic
        self.mood = "content"
        self.mood_reason = ""
        self.mood_set_at = time.time()
        self.last_fed = time.time()
        self.last_petted = time.time()
        self.last_played = time.time()
        self.last_decay_tick = time.time()
        self.recent_events: deque = deque(maxlen=10)
        self.mood_history: deque = deque(maxlen=100)
        self.face_changes_this_hour: list[float] = []
        self.load()

    def load(self):
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH) as f:
                    data = json.load(f)
                self.hunger = data.get("hunger", self.hunger)
                self.boredom = data.get("boredom", self.boredom)
                self.loneliness = data.get("loneliness", self.loneliness)
                self.energy = data.get("energy", self.energy)
                self.happiness = data.get("happiness", self.happiness)
                self.mood = data.get("mood", self.mood)
                self.mood_reason = data.get("mood_reason", self.mood_reason)
                self.mood_set_at = data.get("mood_set_at", self.mood_set_at)
                self.last_fed = data.get("last_fed", self.last_fed)
                self.last_petted = data.get("last_petted", self.last_petted)
                self.last_played = data.get("last_played", self.last_played)
                self.last_decay_tick = data.get("last_decay_tick", self.last_decay_tick)
                for e in data.get("recent_events", []):
                    self.recent_events.append(e)
                for m in data.get("mood_history", []):
                    self.mood_history.append(m)
                log.info("Loaded pet state: mood=%s hunger=%.0f energy=%.0f", self.mood, self.hunger, self.energy)
            except Exception as e:
                log.warning("Failed to load pet state: %s — starting fresh", e)

    def save(self):
        data = {
            "hunger": self.hunger,
            "boredom": self.boredom,
            "loneliness": self.loneliness,
            "energy": self.energy,
            "happiness": self.happiness,
            "mood": self.mood,
            "mood_reason": self.mood_reason,
            "mood_set_at": self.mood_set_at,
            "last_fed": self.last_fed,
            "last_petted": self.last_petted,
            "last_played": self.last_played,
            "last_decay_tick": self.last_decay_tick,
            "recent_events": list(self.recent_events),
            "mood_history": list(self.mood_history),
        }
        try:
            with open(STATE_PATH, "w") as f:
                json.dump(data, f)
        except Exception as e:
            log.error("Failed to save pet state: %s", e)

    def decay_tick(self):
        """Apply need decay based on elapsed time since last tick."""
        now = time.time()
        elapsed = now - self.last_decay_tick
        self.last_decay_tick = now

        self.hunger = min(100, max(0, self.hunger + NEED_DECAY.get("hunger", 0.014) * elapsed))
        self.boredom = min(100, max(0, self.boredom + NEED_DECAY.get("boredom", 0.055) * elapsed))
        self.loneliness = min(100, max(0, self.loneliness + NEED_DECAY.get("loneliness", 0.028) * elapsed))
        self.energy = min(100, max(0, self.energy + NEED_DECAY.get("energy", -0.008) * elapsed))

        # happiness is derived from needs
        need_avg = (self.hunger + self.boredom + self.loneliness + (100 - self.energy)) / 4
        self.happiness = max(0, min(100, 100 - need_avg))

    def feed(self):
        self.hunger = max(0, self.hunger - 30)
        self.last_fed = time.time()
        self.happiness = min(100, self.happiness + 10)
        log.info("Fed %s! hunger=%.0f", PET_NAME, self.hunger)

    def pet(self):
        self.loneliness = max(0, self.loneliness - 25)
        self.last_petted = time.time()
        self.happiness = min(100, self.happiness + 15)
        log.info("Petted %s! loneliness=%.0f", PET_NAME, self.loneliness)

    def play(self):
        self.boredom = max(0, self.boredom - 35)
        self.energy = max(0, self.energy - 10)
        self.last_played = time.time()
        self.happiness = min(100, self.happiness + 20)
        log.info("Played with %s! boredom=%.0f energy=%.0f", PET_NAME, self.boredom, self.energy)

    def set_mood(self, mood: str, reason: str = ""):
        self.mood = mood
        self.mood_reason = reason
        self.mood_set_at = time.time()
        self.mood_history.append({
            "mood": mood,
            "reason": reason,
            "time": datetime.now().isoformat(),
        })

    def can_change_face(self) -> bool:
        """Rate limit face changes per hour."""
        now = time.time()
        cutoff = now - 3600
        self.face_changes_this_hour = [t for t in self.face_changes_this_hour if t > cutoff]
        return len(self.face_changes_this_hour) < MAX_CHANGES_PER_HOUR

    def record_face_change(self):
        self.face_changes_this_hour.append(time.time())

    def needs_summary(self) -> str:
        return (
            f"hunger={self.hunger:.0f}/100 "
            f"boredom={self.boredom:.0f}/100 "
            f"loneliness={self.loneliness:.0f}/100 "
            f"energy={self.energy:.0f}/100 "
            f"happiness={self.happiness:.0f}/100"
        )

    def dominant_need(self) -> str | None:
        needs = {
            "hungry": self.hunger,
            "bored": self.boredom,
            "lonely": self.loneliness,
            "exhausted": 100 - self.energy,
        }
        worst = max(needs, key=needs.get)
        if needs[worst] > 70:
            return worst
        return None


pet = PetState()

# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def is_quiet_hours() -> bool:
    try:
        now = datetime.now().strftime("%H:%M")
        if QUIET_START <= QUIET_END:
            return QUIET_START <= now <= QUIET_END
        return now >= QUIET_START or now <= QUIET_END
    except Exception:
        return False

# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="facade-addon")
if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

def on_mqtt_message(client, userdata, msg):
    """Handle incoming MQTT commands (feed, pet, play)."""
    topic = msg.topic
    try:
        if topic == f"{TOPIC_PREFIX}/feed":
            pet.feed()
            publish_status()
            publish_face({"name": "happy"}, reason="just got fed")
        elif topic == f"{TOPIC_PREFIX}/pet":
            pet.pet()
            publish_status()
            publish_face({"name": "love"}, reason="being petted")
        elif topic == f"{TOPIC_PREFIX}/play":
            pet.play()
            publish_status()
            publish_face({"name": "excited"}, reason="playtime!")
        elif topic == f"{TOPIC_PREFIX}/mood_override":
            payload = json.loads(msg.payload.decode())
            publish_face(payload, reason="mood override")
        elif topic == f"{TOPIC_PREFIX}/mood_select":
            mood_name = msg.payload.decode().strip()
            publish_face({"name": mood_name}, reason="mood override")
    except Exception as e:
        log.error("Error handling MQTT command on %s: %s", topic, e)

mqtt_client.on_message = on_mqtt_message

def connect_mqtt():
    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT)
            mqtt_client.subscribe(f"{TOPIC_PREFIX}/#")
            mqtt_client.loop_start()
            log.info("MQTT connected to %s:%s, subscribed to %s/#", MQTT_HOST, MQTT_PORT, TOPIC_PREFIX)
            return
        except Exception as e:
            log.warning("MQTT connect failed: %s — retrying in 5s", e)
            time.sleep(5)

# ---------------------------------------------------------------------------
# MQTT Discovery — auto-create HA entities
# ---------------------------------------------------------------------------

DISCOVERY_PREFIX = "homeassistant"
DEVICE_ID = f"facade_{PET_NAME.lower().replace(' ', '_')}"
DEVICE_INFO = {
    "identifiers": [DEVICE_ID],
    "name": f"Facade ({PET_NAME})",
    "manufacturer": "Facade",
    "model": "AI Pet",
    "sw_version": "1.0.9",
}

def publish_discovery():
    """Publish MQTT discovery configs so HA auto-creates entities."""
    status_topic = f"{TOPIC_PREFIX}/status"
    # Use stable unique IDs anchored to device + entity key
    uid_prefix = DEVICE_ID

    # --- Sensors ---
    sensors = [
        ("hunger", "Hunger", "mdi:food-drumstick"),
        ("boredom", "Boredom", "mdi:emoticon-neutral-outline"),
        ("loneliness", "Loneliness", "mdi:account-heart-outline"),
        ("energy", "Energy", "mdi:lightning-bolt"),
        ("happiness", "Happiness", "mdi:emoticon-happy-outline"),
    ]
    for key, name, icon in sensors:
        mqtt_client.publish(
            f"{DISCOVERY_PREFIX}/sensor/{uid_prefix}_{key}/config",
            json.dumps({
                "name": name,
                "unique_id": f"{uid_prefix}_{key}",
                "object_id": f"{uid_prefix}_{key}",
                "state_topic": status_topic,
                "value_template": f"{{{{ value_json.{key} }}}}",
                "unit_of_measurement": "%",
                "icon": icon,
                "state_class": "measurement",
                "device": DEVICE_INFO,
            }),
            retain=True,
        )

    # Mood sensor (text)
    mqtt_client.publish(
        f"{DISCOVERY_PREFIX}/sensor/{uid_prefix}_mood/config",
        json.dumps({
            "name": "Mood",
            "unique_id": f"{uid_prefix}_mood",
            "object_id": f"{uid_prefix}_mood",
            "state_topic": status_topic,
            "value_template": "{{ value_json.mood }}",
            "icon": "mdi:emoticon-outline",
            "device": DEVICE_INFO,
        }),
        retain=True,
    )

    # Mood reason sensor
    mqtt_client.publish(
        f"{DISCOVERY_PREFIX}/sensor/{uid_prefix}_mood_reason/config",
        json.dumps({
            "name": "Mood Reason",
            "unique_id": f"{uid_prefix}_mood_reason",
            "object_id": f"{uid_prefix}_mood_reason",
            "state_topic": status_topic,
            "value_template": "{{ value_json.mood_reason }}",
            "icon": "mdi:thought-bubble-outline",
            "device": DEVICE_INFO,
        }),
        retain=True,
    )

    # Dominant need sensor
    mqtt_client.publish(
        f"{DISCOVERY_PREFIX}/sensor/{uid_prefix}_dominant_need/config",
        json.dumps({
            "name": "Dominant Need",
            "unique_id": f"{uid_prefix}_dominant_need",
            "object_id": f"{uid_prefix}_dominant_need",
            "state_topic": status_topic,
            "value_template": "{{ value_json.dominant_need | default('none', true) }}",
            "icon": "mdi:alert-circle-outline",
            "device": DEVICE_INFO,
        }),
        retain=True,
    )

    # --- Buttons ---
    buttons = [
        ("feed", "Feed", "mdi:food-drumstick"),
        ("pet", "Pet", "mdi:hand-heart"),
        ("play", "Play", "mdi:gamepad-variant-outline"),
    ]
    for key, name, icon in buttons:
        mqtt_client.publish(
            f"{DISCOVERY_PREFIX}/button/{uid_prefix}_{key}/config",
            json.dumps({
                "name": f"{name}",
                "unique_id": f"{uid_prefix}_{key}",
                "object_id": f"{uid_prefix}_{key}",
                "command_topic": f"{TOPIC_PREFIX}/{key}",
                "icon": icon,
                "device": DEVICE_INFO,
            }),
            retain=True,
        )

    # --- Mood override select ---
    mood_options = [
        "happy", "sad", "angry", "scared", "surprised", "content", "excited",
        "bored", "curious", "love", "peaceful", "mischievous", "confused",
        "cozy_evening", "morning_energy", "hungry", "tired", "exhausted",
        "playful", "lonely", "calm", "zen", "napping", "hyper",
        "someone_arrived", "someone_left", "owner_home", "party_mode",
        "rain_detected", "sunny", "thunderstorm", "deep_night",
        "celebration", "gaming", "stargazing", "meditation",
    ]
    mqtt_client.publish(
        f"{DISCOVERY_PREFIX}/select/{uid_prefix}_mood_override/config",
        json.dumps({
            "name": "Mood Override",
            "unique_id": f"{uid_prefix}_mood_override",
            "object_id": f"{uid_prefix}_mood_override",
            "command_topic": f"{TOPIC_PREFIX}/mood_select",
            "options": mood_options,
            "icon": "mdi:emoticon-cool-outline",
            "device": DEVICE_INFO,
        }),
        retain=True,
    )

    log.info("Published MQTT discovery for %d entities", 5 + 3 + 3 + 1)

def publish_status():
    """Publish pet status for dashboard/ESP32."""
    payload = json.dumps({
        "name": PET_NAME,
        "mood": pet.mood,
        "mood_reason": pet.mood_reason,
        "hunger": round(pet.hunger),
        "boredom": round(pet.boredom),
        "loneliness": round(pet.loneliness),
        "energy": round(pet.energy),
        "happiness": round(pet.happiness),
        "dominant_need": pet.dominant_need(),
        "uptime": round(time.time() - startup_time),
    })
    mqtt_client.publish(f"{TOPIC_PREFIX}/status", payload, retain=True)

def publish_face(face_command: dict, reason: str = ""):
    if "name" in face_command and len(face_command) == 1:
        topic = f"{TOPIC_PREFIX}/mood"
    elif "p" in face_command and "icon" not in face_command and "fx" not in face_command:
        topic = f"{TOPIC_PREFIX}/pad"
    else:
        topic = f"{TOPIC_PREFIX}/face"

    payload = json.dumps(face_command)
    mqtt_client.publish(topic, payload)
    log.info("Published to %s: %s", topic, payload)

    mood_name = face_command.get("name", f"PAD({face_command.get('p')},{face_command.get('a')},{face_command.get('d')})")
    pet.set_mood(mood_name, reason)
    pet.record_face_change()
    pet.save()

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

HAIKU_SYSTEM = """You are a filter for a virtual pet dweller that lives on a small round screen.
Your job is to decide if a Home Assistant event is interesting enough to change
the pet's facial expression.

Rules:
- Say YES to events that affect the home's mood or vibe (someone arriving/leaving,
  weather changes, alarms, unusual sensor readings, time-of-day transitions)
- Say YES to events that are emotionally significant (doors locking at night,
  energy spikes, temperature extremes, motion in unusual places)
- Say NO to routine/boring events (lights toggling, minor sensor fluctuations,
  repetitive automations, state changes with no emotional significance)
- Say NO if the same type of event happened recently (avoid repetition)
- When in doubt, say NO — the pet should change expression ~5-20 times per day,
  not every minute

Respond ONLY with JSON, no other text:
{"express": true, "reason": "brief reason"} or {"express": false}"""

def brain_system_prompt() -> str:
    return f"""You are the brain of a virtual pet named {PET_NAME}. {PET_NAME} is {PERSONALITY}.
{PET_NAME} lives on a small round screen with two expressive cartoon eyes and reacts to
what's happening in the home.

You control the face with these parameters:

OPTION 1 — Preset mood name (simplest):
{{"name": "<mood_name>"}}

Available moods:
- Basic: happy, sad, angry, scared, surprised, content, excited, bored, curious, love,
  disgusted, jealous, proud, guilty, hopeful, nervous, peaceful, mischievous, confused, determined
- Home: cozy_evening, morning_energy, too_hot, too_cold, perfect_temp, door_unlocked,
  door_locked, alarm_triggered, music_playing, cooking_time, battery_low, internet_down,
  smoke_detected, package_here, mail_arrived
- Needs: hungry, tired, exhausted, playful, lonely, calm, zen, napping, hyper
- Events: doorbell, someone_arrived, someone_left, owner_home, owner_away, party_mode,
  rain_detected, storm_warning, sunny, thunderstorm, motion_detected, water_leak
- Time: dawn, morning_coffee, noon, afternoon_slump, golden_hour, movie_night, midnight, deep_night
- Special: christmas, halloween, birthday, fireworks, meditation, gaming, stargazing, celebration

OPTION 2 — Raw PAD values:
{{"p": <-100 to 100>, "a": <-100 to 100>, "d": <-100 to 100>}}
P = Pleasure, A = Arousal, D = Dominance

OPTION 3 — Full parametric:
{{"p": 80, "a": 50, "d": 50, "hue": 330, "icon": "heart", "fx": "pupil_replace", "color": "F800"}}
hue: -1=auto, 0-360 | icon: heart,star,note,question,cloud,drop,snow,warn,mug,bell,box,bolt,zzz,party
fx: pupil_replace,float_above,rain_down,orbit,eye_sparkle,bottom_status,bg_fill,side_peek,pulse_center,tear_drop

Guidelines:
- {PET_NAME}'s needs affect their expression — a hungry pet looks sadder, a bored pet looks restless
- Match the face to the HOME's emotional state AND the pet's internal state
- Consider time of day — late night should be sleepy
- Consider accumulation — multiple negative events build frustration
- If needs are critical (>80), the face should reflect that regardless of events
- Be creative with full parametric mode for unique moments
- Prefer preset mood names when one fits; use PAD for nuance

Respond ONLY with the JSON face command, no other text."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def should_watch(entity_id: str) -> bool:
    # Ignore our own MQTT Discovery entities
    if "facade" in entity_id or "dweller" in entity_id:
        return False
    # Check web UI entity config (takes priority)
    web_cfg = load_entity_config()
    if entity_id in web_cfg.get("ignored", []):
        return False
    if entity_id in web_cfg.get("watched", []):
        return True
    # Check add-on options
    if entity_id in IGNORED_ENTITIES:
        return False
    if entity_id in WATCHED_ENTITIES:
        return True
    domain = entity_id.split(".")[0]
    return domain in WATCHED_DOMAINS

def parse_json_response(text: str) -> dict:
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[^}]+\}", text)
        if match:
            return json.loads(match.group())
        return {}

def install_lovelace_card():
    """Copy the dashboard card to /config/www/ and register as a Lovelace resource."""
    import shutil

    src = "/dweller-card.js"
    # homeassistant_config map mounts HA config at /homeassistant
    dst_dir = "/homeassistant/www"
    dst = f"{dst_dir}/dweller-card.js"
    resource_url = "/local/dweller-card.js"

    # Copy JS file
    try:
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy2(src, dst)
        log.info("Installed dweller-card.js to %s", dst)
    except Exception as e:
        log.error("Failed to copy dashboard card: %s", e)
        return

    # Register as Lovelace resource if not already registered
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    try:
        resp = requests.get(f"{HA_REST_URL}/lovelace/resources", headers=headers, timeout=10)
        if resp.status_code == 200:
            resources = resp.json()
            already = any(r.get("url") == resource_url for r in resources)
            if not already:
                requests.post(
                    f"{HA_REST_URL}/lovelace/resources",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"url": resource_url, "res_type": "module"},
                    timeout=10,
                )
                log.info("Registered Lovelace resource: %s", resource_url)
            else:
                log.debug("Lovelace resource already registered")
        else:
            log.warning("Could not check Lovelace resources (HTTP %d) — card may need manual registration", resp.status_code)
    except Exception as e:
        log.warning("Could not register Lovelace resource: %s — card may need manual registration", e)


def get_ha_states() -> list[dict]:
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    try:
        resp = requests.get(f"{HA_REST_URL}/states", headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error("Failed to fetch HA states: %s", e)
        return []

def build_context(event: dict, states: list[dict]) -> str:
    now = datetime.now()
    people = [
        s.get("attributes", {}).get("friendly_name", s["entity_id"])
        for s in states
        if s["entity_id"].startswith("person.") and s["state"] == "home"
    ]
    doors = [
        f"{s.get('attributes', {}).get('friendly_name', s['entity_id'])}: {s['state']}"
        for s in states
        if ("door" in s["entity_id"] or "lock" in s["entity_id"])
        and (s["entity_id"].startswith("binary_sensor.") or s["entity_id"].startswith("lock."))
    ][:5]
    weather = next(
        (s["state"] for s in states if s["entity_id"].startswith("weather.")), "unknown"
    )
    recent_str = "\n".join(
        f"- {e['name']}: {e['from']} -> {e['to']} at {e['time']}"
        for e in pet.recent_events
    ) or "(none)"

    return f"""TRIGGERING EVENT:
{event['name']} ({event['entity_id']}) changed from "{event['from']}" to "{event['to']}"
Reason for expression: {event['reason']}

CURRENT CONTEXT:
Time: {now.strftime('%-I:%M %p')}
Day: {now.strftime('%A, %B %-d %Y')}

{PET_NAME}'s needs:
{pet.needs_summary()}
Dominant need: {pet.dominant_need() or 'none — feeling good'}

Recent events:
{recent_str}

Sensor snapshot:
- Weather: {weather}
- People home: {', '.join(people) or 'nobody'}
- Doors: {', '.join(doors) or 'unknown'}

{PET_NAME}'s current mood: {pet.mood} (since {int((time.time() - pet.mood_set_at) / 60)} min ago)

What face should {PET_NAME} show?"""

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

last_trigger_time = 0.0

def handle_event(entity_id: str, old_state: str, new_state: str, friendly_name: str):
    global last_trigger_time

    now = time.time()
    if now - last_trigger_time < DEBOUNCE_SECONDS:
        log.debug("Debounced %s", entity_id)
        return
    if is_quiet_hours():
        log.debug("Quiet hours — skipping %s", entity_id)
        return
    if not pet.can_change_face():
        log.info("Rate limit hit (%d/hr) — skipping %s", MAX_CHANGES_PER_HOUR, entity_id)
        return
    last_trigger_time = now

    timestamp = datetime.now().isoformat()

    # --- Tier 1: Haiku filter ---
    log.info("Haiku filter: %s %s -> %s", friendly_name, old_state, new_state)
    try:
        haiku_resp = ai_client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=100,
            system=HAIKU_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f'Event: {entity_id} changed from "{old_state}" to "{new_state}"\n'
                    f"Entity name: {friendly_name}\n"
                    f"Time: {timestamp}\n"
                    f"Pet needs: {pet.needs_summary()}"
                ),
            }],
        )
        haiku_result = parse_json_response(haiku_resp.content[0].text)
    except Exception as e:
        log.error("Haiku API error: %s", e)
        return

    if not haiku_result.get("express"):
        log.info("Haiku says skip: %s", entity_id)
        return

    reason = haiku_result.get("reason", "")
    log.info("Haiku says express: %s — %s", entity_id, reason)

    event = {
        "entity_id": entity_id,
        "from": old_state,
        "to": new_state,
        "name": friendly_name,
        "time": timestamp,
        "reason": reason,
    }
    pet.recent_events.append(event)

    # --- Gather context ---
    states = get_ha_states()
    context_prompt = build_context(event, states)

    # --- Tier 2: Brain ---
    log.info("Brain thinking about %s...", entity_id)
    try:
        brain_resp = ai_client.messages.create(
            model=BRAIN_MODEL,
            max_tokens=300,
            system=brain_system_prompt(),
            messages=[{"role": "user", "content": context_prompt}],
        )
        face_command = parse_json_response(brain_resp.content[0].text)
    except Exception as e:
        log.error("Brain API error: %s", e)
        return

    if not face_command:
        log.warning("Brain returned empty response for %s", entity_id)
        return

    publish_face(face_command, reason=reason)

# ---------------------------------------------------------------------------
# Needs decay + idle mood thread
# ---------------------------------------------------------------------------

def needs_loop():
    """Background loop: decay needs, publish status, trigger idle moods."""
    while True:
        time.sleep(60)
        pet.decay_tick()
        publish_status()

        # If a need is critical and no recent face change, express it
        dominant = pet.dominant_need()
        if dominant and pet.can_change_face() and not is_quiet_hours():
            mins_since_mood = (time.time() - pet.mood_set_at) / 60
            if mins_since_mood > 30:
                need_moods = {
                    "hungry": "hungry",
                    "bored": "bored",
                    "lonely": "lonely",
                    "exhausted": "exhausted",
                }
                mood = need_moods.get(dominant, "sad")
                log.info("Idle need expression: %s (%.0f min since last change)", dominant, mins_since_mood)
                publish_face({"name": mood}, reason=f"feeling {dominant}")

        pet.save()

# ---------------------------------------------------------------------------
# Websocket event listener
# ---------------------------------------------------------------------------

startup_time = time.time()

def run():
    import websocket as ws_lib

    if not SUPERVISOR_TOKEN:
        log.error("SUPERVISOR_TOKEN is empty — homeassistant_api may not be set in config.yaml")
        return

    log.info("Facade starting — %s is waking up", PET_NAME)

    # Start config web UI
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    # Wait for HA Core to be ready before connecting
    wait_for_ha()

    install_lovelace_card()
    connect_mqtt()
    publish_discovery()
    publish_status()

    # Start needs decay thread
    decay_thread = threading.Thread(target=needs_loop, daemon=True)
    decay_thread.start()

    # Connect to HA event bus
    connect_ha_websocket()


def wait_for_ha():
    """Block until HA Core API is reachable."""
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    while True:
        try:
            resp = requests.get(f"{HA_REST_URL}/", headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                log.info("HA Core is ready (version %s)", data.get("version", "?"))
                return
            log.info("HA Core not ready (HTTP %d) — waiting 10s", resp.status_code)
        except Exception as e:
            log.info("HA Core not reachable (%s) — waiting 10s", e)
        time.sleep(10)


def connect_ha_websocket():
    """Connect to HA websocket and subscribe to state_changed events."""
    import websocket as ws_lib

    msg_id = 1
    backoff = 5

    def on_open(ws):
        nonlocal msg_id
        log.info("WS connected to Home Assistant")

    def on_message(ws, message):
        nonlocal msg_id, backoff
        data = json.loads(message)
        msg_type = data.get("type", "")

        if msg_type == "auth_required":
            ws.send(json.dumps({"type": "auth", "access_token": SUPERVISOR_TOKEN}))
            return

        if msg_type == "auth_invalid":
            log.error("Auth rejected: %s", data.get("message", "unknown"))
            ws.close()
            return

        if msg_type == "auth_ok":
            backoff = 5  # reset backoff on successful auth
            log.info("Authenticated with HA (version %s)", data.get("ha_version", "?"))
            ws.send(json.dumps({
                "id": msg_id,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }))
            msg_id += 1
            return

        if msg_type == "event":
            event_data = data.get("event", {}).get("data", {})
            entity_id = event_data.get("entity_id", "")
            old = event_data.get("old_state", {})
            new = event_data.get("new_state", {})

            if not old or not new:
                return
            if old.get("state") == new.get("state"):
                return
            if not should_watch(entity_id):
                return

            friendly_name = new.get("attributes", {}).get("friendly_name", entity_id)

            # Apply event-based need modifiers
            modifiers = match_need_modifiers(entity_id, old["state"], new["state"])
            if modifiers:
                deltas, reasons = aggregate_needs(modifiers)
                for need, delta in deltas.items():
                    current = getattr(pet, need, None)
                    if current is not None:
                        setattr(pet, need, min(100, max(0, current + delta)))
                if deltas:
                    log.info("Needs modified by %s: %s (%s)", entity_id,
                             {k: f"{'+' if v > 0 else ''}{v}" for k, v in deltas.items()},
                             "; ".join(reasons))
                    pet.save()
                    publish_status()

            handle_event(entity_id, old["state"], new["state"], friendly_name)

    def on_error(ws, error):
        log.error("WS error: %s", error)

    def on_close(ws, close_status_code, close_msg):
        nonlocal backoff
        log.warning("WS closed (code=%s) — reconnecting in %ds", close_status_code, backoff)
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)  # exponential backoff, max 60s

    while True:
        try:
            wsapp = ws_lib.WebSocketApp(
                HA_WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )
            wsapp.run_forever()
        except Exception as e:
            log.error("WS connection failed: %s — retrying in %ds", e, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    run()
