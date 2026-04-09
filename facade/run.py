"""Facade — two-tier AI pipeline for tamagotchi face expressions."""

import json
import logging
import os
import time
from collections import deque
from datetime import datetime

import anthropic
import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Config from add-on options
# ---------------------------------------------------------------------------

OPTIONS_PATH = "/data/options.json"

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
BRAIN_MODEL = OPTIONS.get("brain_model", "claude-sonnet-4-6-20250514")
WATCHED_DOMAINS = set(OPTIONS.get("watched_domains", [
    "binary_sensor", "climate", "cover", "light",
    "media_player", "person", "sensor", "sun", "zone",
]))
WATCHED_ENTITIES = set(OPTIONS.get("watched_entities", []))
IGNORED_ENTITIES = set(OPTIONS.get("ignored_entities", []))
LOG_LEVEL = OPTIONS.get("log_level", "info").upper()

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
# HA Websocket API
# ---------------------------------------------------------------------------

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_WS_URL = "ws://supervisor/core/websocket"
HA_REST_URL = "http://supervisor/core/api"

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

last_trigger_time = 0.0
recent_events: deque = deque(maxlen=10)
current_mood = "unknown"
mood_set_at = 0.0

# ---------------------------------------------------------------------------
# Anthropic client
# ---------------------------------------------------------------------------

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="facade-addon")
if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

def connect_mqtt():
    while True:
        try:
            mqtt_client.connect(MQTT_HOST, MQTT_PORT)
            mqtt_client.loop_start()
            log.info("MQTT connected to %s:%s", MQTT_HOST, MQTT_PORT)
            return
        except Exception as e:
            log.warning("MQTT connect failed: %s — retrying in 5s", e)
            time.sleep(5)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

HAIKU_SYSTEM = """You are a filter for a virtual pet tamagotchi that lives on a small round screen.
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

BRAIN_SYSTEM = """You are the brain of a virtual pet tamagotchi displayed on a small round screen
with two expressive cartoon eyes. You decide what face the pet should show based
on what's happening in the home.

You control the face with these parameters:

OPTION 1 — Preset mood name (simplest):
{"name": "<mood_name>"}

Available moods (key ones):
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

OPTION 2 — Raw PAD values (more nuanced):
{"p": <-100 to 100>, "a": <-100 to 100>, "d": <-100 to 100>}
P = Pleasure, A = Arousal, D = Dominance

OPTION 3 — Full parametric (maximum control):
{"p": 80, "a": 50, "d": 50, "hue": 330, "icon": "heart", "fx": "pupil_replace", "color": "F800"}
hue: -1=auto, 0-360 | icon: heart,star,note,question,cloud,drop,snow,warn,mug,bell,box,bolt,zzz,party
fx: pupil_replace,float_above,rain_down,orbit,eye_sparkle,bottom_status,bg_fill,side_peek,pulse_center,tear_drop

Guidelines:
- Match the face to the HOME's emotional state, not just the event
- Consider time of day — late night events should have sleepy undertones
- Consider accumulation — multiple small negative events should build frustration
- Be creative with the full parametric mode for unique moments
- The pet has personality — it's curious, empathetic, and a bit dramatic
- Prefer preset mood names when one fits well; use PAD for nuance
- Add emoji effects for weather, alerts, celebrations, and special moments

Respond ONLY with the JSON face command, no other text."""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def should_watch(entity_id: str) -> bool:
    if entity_id in IGNORED_ENTITIES:
        return False
    if entity_id in WATCHED_ENTITIES:
        return True
    domain = entity_id.split(".")[0]
    return domain in WATCHED_DOMAINS


def parse_json_response(text: str) -> dict:
    text = text.strip()
    text = text.removeprefix("```json").removeprefix("```")
    text = text.removesuffix("```")
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r"\{[^}]+\}", text)
        if match:
            return json.loads(match.group())
        return {}


def get_ha_states(ws) -> list[dict]:
    """Fetch all entity states via the websocket connection."""
    import requests
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
        f"- {e['name']}: {e['from']} → {e['to']} at {e['time']}"
        for e in recent_events
    ) or "(none)"

    return f"""TRIGGERING EVENT:
{event['name']} ({event['entity_id']}) changed from "{event['from']}" to "{event['to']}"
Reason for expression: {event['reason']}

CURRENT CONTEXT:
Time: {now.strftime('%-I:%M %p')}
Day: {now.strftime('%A, %B %-d %Y')}

Recent events:
{recent_str}

Sensor snapshot:
- Weather: {weather}
- People home: {', '.join(people) or 'nobody'}
- Doors: {', '.join(doors) or 'unknown'}

Pet's current mood: {current_mood} (since {int((time.time() - mood_set_at) / 60) if mood_set_at else '?'} minutes ago)

What face should the tamagotchi show?"""


def publish_face(face_command: dict):
    global current_mood, mood_set_at

    if "name" in face_command and len(face_command) == 1:
        topic = "tamagotchi/mood"
    elif "p" in face_command and "icon" not in face_command and "fx" not in face_command:
        topic = "tamagotchi/pad"
    else:
        topic = "tamagotchi/face"

    payload = json.dumps(face_command)
    mqtt_client.publish(topic, payload)
    log.info("Published to %s: %s", topic, payload)

    current_mood = face_command.get("name", f"PAD({face_command.get('p')},{face_command.get('a')},{face_command.get('d')})")
    mood_set_at = time.time()

# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def handle_event(entity_id: str, old_state: str, new_state: str, friendly_name: str):
    global last_trigger_time

    now = time.time()
    if now - last_trigger_time < DEBOUNCE_SECONDS:
        log.debug("Debounced %s", entity_id)
        return
    last_trigger_time = now

    timestamp = datetime.now().isoformat()

    # --- Tier 1: Haiku filter ---
    log.info("Haiku filter: %s %s → %s", friendly_name, old_state, new_state)
    try:
        haiku_resp = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=100,
            system=HAIKU_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f'Event: {entity_id} changed from "{old_state}" to "{new_state}"\n'
                    f"Entity name: {friendly_name}\n"
                    f"Time: {timestamp}"
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
    recent_events.append(event)

    # --- Gather context ---
    states = get_ha_states(None)
    context_prompt = build_context(event, states)

    # --- Tier 2: Brain ---
    log.info("Brain thinking about %s...", entity_id)
    try:
        brain_resp = client.messages.create(
            model=BRAIN_MODEL,
            max_tokens=300,
            system=BRAIN_SYSTEM,
            messages=[{"role": "user", "content": context_prompt}],
        )
        face_command = parse_json_response(brain_resp.content[0].text)
    except Exception as e:
        log.error("Brain API error: %s", e)
        return

    if not face_command:
        log.warning("Brain returned empty response for %s", entity_id)
        return

    # --- Publish ---
    publish_face(face_command)

# ---------------------------------------------------------------------------
# Websocket event listener
# ---------------------------------------------------------------------------

def run():
    import websocket as ws_lib

    log.info("Facade starting up")
    connect_mqtt()

    msg_id = 1

    def on_open(ws):
        nonlocal msg_id
        log.info("WS connected to Home Assistant")

    def on_message(ws, message):
        nonlocal msg_id
        data = json.loads(message)

        if data.get("type") == "auth_required":
            ws.send(json.dumps({"type": "auth", "access_token": SUPERVISOR_TOKEN}))
            return

        if data.get("type") == "auth_ok":
            log.info("Authenticated with HA")
            ws.send(json.dumps({
                "id": msg_id,
                "type": "subscribe_events",
                "event_type": "state_changed",
            }))
            msg_id += 1
            return

        if data.get("type") == "event":
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
            handle_event(entity_id, old["state"], new["state"], friendly_name)

    def on_error(ws, error):
        log.error("WS error: %s", error)

    def on_close(ws, close_status_code, close_msg):
        log.warning("WS closed — reconnecting in 5s")
        time.sleep(5)

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
            log.error("WS connection failed: %s — retrying in 5s", e)
            time.sleep(5)


if __name__ == "__main__":
    run()
