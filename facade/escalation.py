"""AI escalation — budget-capped Opus fallback for unmatched events."""

import json
import logging
import os
import time
from collections import deque
from datetime import datetime

log = logging.getLogger("facade.escalation")

UNMATCHED_PATH = "/data/unmatched_events.jsonl"


class Escalation:
    def __init__(self, enabled: bool = True, budget_per_day: int = 10,
                 model: str = "claude-opus-4-20250514", ai_client=None):
        self.enabled = enabled
        self.budget_per_day = budget_per_day
        self.model = model
        self.ai_client = ai_client
        self.calls_today: list[float] = []
        self.seen_patterns: set[str] = set()  # dedup within 24h
        self._last_pattern_reset = time.time()

    def log_unmatched(self, entity_id: str, from_state: str, to_state: str,
                      friendly_name: str):
        """Always log unmatched events, regardless of escalation setting."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "entity_id": entity_id,
            "friendly_name": friendly_name,
            "from_state": from_state,
            "to_state": to_state,
        }
        try:
            with open(UNMATCHED_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.error("Failed to log unmatched event: %s", e)

    def should_escalate(self, entity_id: str, from_state: str, to_state: str) -> bool:
        """Check if this event should be escalated to AI."""
        if not self.enabled or not self.ai_client:
            return False

        # Reset daily counters
        now = time.time()
        cutoff = now - 86400
        self.calls_today = [t for t in self.calls_today if t > cutoff]

        # Budget check
        if len(self.calls_today) >= self.budget_per_day:
            return False

        # Reset seen patterns every 24h
        if now - self._last_pattern_reset > 86400:
            self.seen_patterns.clear()
            self._last_pattern_reset = now

        # Dedup — don't escalate the same entity+transition twice in 24h
        pattern = f"{entity_id}:{from_state}:{to_state}"
        if pattern in self.seen_patterns:
            return False

        return True

    def escalate(self, entity_id: str, from_state: str, to_state: str,
                 friendly_name: str, pet_needs: str = "",
                 available_moods: str = "") -> tuple[dict | None, dict]:
        """Call Opus for a novel event. Returns (face_command, need_deltas)."""
        if not self.ai_client:
            return None, {}

        pattern = f"{entity_id}:{from_state}:{to_state}"
        self.seen_patterns.add(pattern)
        self.calls_today.append(time.time())

        log.info("Escalating to %s: %s %s -> %s (%d/%d budget)",
                 self.model, entity_id, from_state, to_state,
                 len(self.calls_today), self.budget_per_day)

        prompt = f"""A smart home event just occurred that doesn't match any existing rules.

Entity: {entity_id} ({friendly_name})
Changed from: "{from_state}" to: "{to_state}"
Time: {datetime.now().strftime('%-I:%M %p, %A')}
Pet needs: {pet_needs}

Respond with a JSON object containing:
1. "face" — a face command (either {{"name": "mood_preset"}} or {{"p": N, "a": N, "d": N}})
2. "needs" — need modifiers (hunger/boredom/loneliness/energy/happiness deltas, -30 to +30 range)
3. "description" — a short description for this rule (for logging)
4. "interesting" — boolean, whether this type of event is generally worth reacting to

Available mood presets: happy, sad, angry, scared, surprised, content, excited, bored, curious, love, peaceful, mischievous, confused, cozy_evening, morning_energy, too_hot, too_cold, perfect_temp, door_unlocked, door_locked, alarm_triggered, music_playing, hungry, tired, exhausted, playful, lonely, calm, zen, napping, hyper, doorbell, someone_arrived, someone_left, owner_home, owner_away, party_mode, rain_detected, storm_warning, sunny, thunderstorm, deep_night, celebration, gaming, stargazing, meditation

Respond ONLY with JSON, no other text."""

        try:
            resp = self.ai_client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(text)

            face = result.get("face")
            needs = result.get("needs", {})
            desc = result.get("description", "")
            interesting = result.get("interesting", True)

            log.info("Escalation result: face=%s needs=%s interesting=%s desc=%s",
                     face, needs, interesting, desc)

            # Log the escalation result alongside the event
            self.log_unmatched(entity_id, from_state, to_state, friendly_name)
            try:
                with open(UNMATCHED_PATH, "a") as f:
                    f.write(json.dumps({
                        "timestamp": datetime.now().isoformat(),
                        "type": "escalation_result",
                        "entity_id": entity_id,
                        "from_state": from_state,
                        "to_state": to_state,
                        "face": face,
                        "needs": needs,
                        "description": desc,
                        "interesting": interesting,
                        "model": self.model,
                    }) + "\n")
            except Exception:
                pass

            if not interesting:
                return None, {}

            return face or {}, needs

        except Exception as e:
            log.error("Escalation API error: %s", e)
            return None, {}

    def get_unmatched_events(self, limit: int = 50) -> list[dict]:
        """Read recent unmatched events for the web UI."""
        if not os.path.exists(UNMATCHED_PATH):
            return []
        try:
            with open(UNMATCHED_PATH) as f:
                lines = f.readlines()
            events = [json.loads(line) for line in lines[-limit:]]
            events.reverse()
            return events
        except Exception:
            return []

    def get_budget_status(self) -> dict:
        """Return current escalation budget status."""
        now = time.time()
        cutoff = now - 86400
        self.calls_today = [t for t in self.calls_today if t > cutoff]
        return {
            "enabled": self.enabled,
            "budget": self.budget_per_day,
            "used": len(self.calls_today),
            "remaining": max(0, self.budget_per_day - len(self.calls_today)),
            "model": self.model,
        }
