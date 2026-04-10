"""Batch learning — generates reactions.json from HA export data."""

import json
import logging
import os

log = logging.getLogger("facade.learn")

EXPORT_PATH = "/data/ha_export.json"
REACTIONS_PATH = "/data/reactions.json"
UNMATCHED_PATH = "/data/unmatched_events.jsonl"

SYSTEM_PROMPT = """You are designing behavioral rules for a virtual pet that lives in a smart home.
The pet watches Home Assistant state_changed events and reacts with facial expressions and internal need changes.

You will receive a dump of the smart home's entities and their state change history.
Generate a reactions.json file mapping events to face commands and need modifiers.

SCHEMA:
{
  "version": 1,
  "rules": [
    {
      "id": "unique_snake_case_id",
      "description": "Human-readable description",
      "priority": 0-100 (higher wins for face command, all needs stack),
      "enabled": true,
      "match": {
        "entity_pattern": "fnmatch pattern (e.g. person.*, binary_sensor.*door*)",
        "from_state": "state or * or !value or >N or <N",
        "to_state": "state or * or !value or >N or <N"
      },
      "face": {"name": "mood_preset"} OR {"p": N, "a": N, "d": N} OR {"p": N, "a": N, "d": N, "hue": N, "icon": "name", "fx": "name"},
      "needs": {"hunger": delta, "boredom": delta, "loneliness": delta, "energy": delta, "happiness": delta},
      "cooldown_seconds": seconds_between_triggers,
      "time_window": {"after": "HH:MM", "before": "HH:MM"} (optional)
    }
  ],
  "defaults": {
    "escalation_enabled": true,
    "escalation_budget_per_day": 10,
    "unmatched_behavior": "ignore"
  }
}

AVAILABLE MOOD PRESETS:
happy, sad, angry, scared, surprised, content, excited, bored, curious, love,
disgusted, jealous, proud, guilty, hopeful, nervous, peaceful, mischievous, confused, determined,
cozy_evening, morning_energy, too_hot, too_cold, perfect_temp, door_unlocked,
door_locked, alarm_triggered, music_playing, cooking_time, battery_low, internet_down,
smoke_detected, package_here, mail_arrived,
hungry, tired, exhausted, playful, lonely, calm, zen, napping, hyper,
doorbell, someone_arrived, someone_left, owner_home, owner_away, party_mode,
rain_detected, storm_warning, sunny, thunderstorm, motion_detected, water_leak,
dawn, morning_coffee, noon, afternoon_slump, golden_hour, movie_night, midnight, deep_night,
christmas, halloween, birthday, fireworks, meditation, gaming, stargazing, celebration

ICONS: heart, star, note, question, cloud, drop, snow, warn, mug, bell, box, bolt, zzz, party
FX: pupil_replace, float_above, rain_down, orbit, eye_sparkle, bottom_status, bg_fill, side_peek, pulse_center, tear_drop

GUIDELINES:
- High-frequency entities (>50 changes/day) should have long cooldowns or be ignored
- Presence changes (person domain) are always important (priority 70-90)
- Safety events (smoke, leak, alarm) get priority 100 and short cooldowns
- Door/lock events are medium priority (40-60)
- Media/lights are low-medium priority (20-45)
- Weather changes: one reaction per change, long cooldown (1-4 hours)
- Need deltas should be -30 to +30 range, proportional to emotional significance
- Set cooldowns based on how often the event recurs: common events = longer cooldowns
- The pet is curious, empathetic, and slightly dramatic
- Generate 30-80 rules covering the most common patterns in this specific home
- DO NOT generate rules for entities that never change state
"""

USER_PROMPT_TEMPLATE = """Here is the smart home data. Generate a complete reactions.json for this home.

HOME DATA:
{export_data}

{unmatched_section}

Focus on entities that actually change state. Look at daily_change_count and common_transitions
to determine appropriate cooldowns and priorities. Generate rules that match this home's actual
patterns — not generic rules.

Respond with the complete JSON only, no other text."""


def build_learning_prompt(export_path: str = EXPORT_PATH,
                          unmatched_path: str = UNMATCHED_PATH) -> tuple[str, str]:
    """Build the system and user prompts for batch learning.

    Returns (system_prompt, user_prompt).
    """
    # Load export data
    if not os.path.exists(export_path):
        raise FileNotFoundError(f"No export found at {export_path}. Run data export first.")

    with open(export_path) as f:
        export = json.load(f)

    # Trim the export for prompt size — keep summaries, drop raw history
    trimmed = {
        "exported_at": export.get("exported_at"),
        "export_days": export.get("export_days"),
        "statistics": export.get("statistics"),
        "entities": export.get("entities", []),
    }
    export_str = json.dumps(trimmed, indent=2)

    # Include unmatched events if available
    unmatched_section = ""
    if os.path.exists(unmatched_path):
        try:
            with open(unmatched_path) as f:
                lines = f.readlines()[-50:]  # Last 50 unmatched events
            if lines:
                events = [json.loads(l) for l in lines if '"type": "escalation_result"' not in l]
                if events:
                    unmatched_section = (
                        "UNMATCHED EVENTS (events that previous rules missed — generate rules for these):\n"
                        + json.dumps(events[:30], indent=2)
                    )
        except Exception:
            pass

    user_prompt = USER_PROMPT_TEMPLATE.format(
        export_data=export_str,
        unmatched_section=unmatched_section,
    )

    return SYSTEM_PROMPT, user_prompt


def run_batch_learning(ai_client, model: str = "claude-sonnet-4-5-20241022",
                       export_path: str = EXPORT_PATH) -> str:
    """Run the batch learning pass and save reactions.json.

    Returns the path to the generated reactions file.
    """
    system, user = build_learning_prompt(export_path)

    log.info("Running batch learning with %s...", model)
    try:
        resp = ai_client.messages.create(
            model=model,
            max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = resp.content[0].text.strip()
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

        reactions = json.loads(text)

        # Validate basic structure
        if "rules" not in reactions:
            raise ValueError("Generated JSON missing 'rules' key")

        reactions.setdefault("version", 1)
        reactions.setdefault("generated_by", model)
        reactions["generated_at"] = __import__("datetime").datetime.now().isoformat()

        with open(REACTIONS_PATH, "w") as f:
            json.dump(reactions, f, indent=2)

        log.info("Batch learning complete: %d rules generated, saved to %s",
                 len(reactions["rules"]), REACTIONS_PATH)
        return REACTIONS_PATH

    except Exception as e:
        log.error("Batch learning failed: %s", e)
        raise
