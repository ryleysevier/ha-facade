"""Rules engine — matches HA events to face commands and need modifiers.

Loads reactions.json and provides instant, zero-token event matching
with per-rule cooldowns and priority-based conflict resolution.
"""

import fnmatch
import json
import logging
import os
import time
from datetime import datetime

log = logging.getLogger("facade.rules")

REACTIONS_PATH = "/data/reactions.json"
DEFAULT_REACTIONS_PATH = "/reactions_default.json"


class RulesEngine:
    def __init__(self, path: str = REACTIONS_PATH):
        self.rules: list[dict] = []
        self.defaults: dict = {}
        self.cooldowns: dict[str, float] = {}  # rule_id -> last fired timestamp
        self.path = path
        self.load()

    def load(self, path: str | None = None):
        """Load rules from reactions.json, falling back to defaults."""
        path = path or self.path
        if not os.path.exists(path):
            path = DEFAULT_REACTIONS_PATH
        if not os.path.exists(path):
            log.warning("No reactions.json found — rules engine has no rules")
            self.rules = []
            self.defaults = {"escalation_enabled": True, "escalation_budget_per_day": 10, "unmatched_behavior": "ignore"}
            return

        try:
            with open(path) as f:
                data = json.load(f)
            self.rules = data.get("rules", [])
            self.defaults = data.get("defaults", {})
            # Sort by priority descending for fast resolution
            self.rules.sort(key=lambda r: r.get("priority", 0), reverse=True)
            # Build domain index for fast filtering
            self._build_index()
            log.info("Loaded %d rules from %s", len(self.rules), path)
        except Exception as e:
            log.error("Failed to load reactions: %s", e)
            self.rules = []
            self.defaults = {}

    def _build_index(self):
        """Build a domain-based index for fast lookups."""
        self._domain_index: dict[str, list[dict]] = {}
        self._wildcard_rules: list[dict] = []
        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            pattern = rule.get("match", {}).get("entity_pattern", "")
            domain = pattern.split(".")[0] if "." in pattern else ""
            if "*" in domain or not domain:
                self._wildcard_rules.append(rule)
            else:
                self._domain_index.setdefault(domain, []).append(rule)

    def match(self, entity_id: str, from_state: str, to_state: str,
              now: datetime | None = None) -> tuple[dict | None, list[dict], list[str]]:
        """Match an event against all rules.

        Returns:
            (face_command, need_deltas_list, reasons)
            face_command: dict or None (from highest priority match)
            need_deltas_list: list of {need: delta} dicts (from all matches, to be summed)
            reasons: list of description strings
        """
        if now is None:
            now = datetime.now()

        domain = entity_id.split(".")[0] if "." in entity_id else ""
        candidates = self._domain_index.get(domain, []) + self._wildcard_rules

        face_cmd = None
        need_deltas = []
        reasons = []

        for rule in candidates:
            match_cfg = rule.get("match", {})

            # Entity pattern
            pattern = match_cfg.get("entity_pattern", "")
            if not fnmatch.fnmatch(entity_id, pattern):
                continue

            # State matching
            if not _state_matches(match_cfg.get("from_state", "*"), from_state):
                continue
            if not _state_matches(match_cfg.get("to_state", "*"), to_state):
                continue

            # Time window
            time_window = rule.get("time_window")
            if time_window and not _in_time_window(time_window, now):
                continue

            # Cooldown
            rule_id = rule.get("id", pattern)
            cooldown = rule.get("cooldown_seconds", 0)
            if cooldown > 0:
                last_fired = self.cooldowns.get(rule_id, 0)
                if time.time() - last_fired < cooldown:
                    continue

            # Match! Record cooldown
            self.cooldowns[rule_id] = time.time()

            # Face command — only from highest priority (first match, since sorted)
            if face_cmd is None and "face" in rule:
                face_cmd = rule["face"]

            # Need deltas — stack from all matches
            if "needs" in rule:
                need_deltas.append(rule["needs"])

            reasons.append(rule.get("description", rule_id))

        return face_cmd, need_deltas, reasons

    def has_match(self, entity_id: str, from_state: str, to_state: str) -> bool:
        """Quick check if any rule would match (ignores cooldowns)."""
        domain = entity_id.split(".")[0] if "." in entity_id else ""
        candidates = self._domain_index.get(domain, []) + self._wildcard_rules

        for rule in candidates:
            if not rule.get("enabled", True):
                continue
            match_cfg = rule.get("match", {})
            pattern = match_cfg.get("entity_pattern", "")
            if not fnmatch.fnmatch(entity_id, pattern):
                continue
            if not _state_matches(match_cfg.get("from_state", "*"), from_state):
                continue
            if not _state_matches(match_cfg.get("to_state", "*"), to_state):
                continue
            return True
        return False

    def reload(self):
        """Hot-reload rules from disk."""
        self.load()
        log.info("Rules engine reloaded — %d rules active", len(self.rules))


def _state_matches(pattern: str, actual: str) -> bool:
    """Match a state value against a pattern."""
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


def _in_time_window(window: dict, now: datetime) -> bool:
    """Check if current time is within a time window."""
    try:
        after = window.get("after", "00:00")
        before = window.get("before", "23:59")
        # TODO: support "sunset"/"sunrise" by checking sun.sun entity
        now_str = now.strftime("%H:%M")
        if after <= before:
            return after <= now_str <= before
        return now_str >= after or now_str <= before
    except Exception:
        return True


def aggregate_need_deltas(deltas_list: list[dict]) -> dict:
    """Sum need deltas from multiple matched rules."""
    totals = {}
    for deltas in deltas_list:
        for need, delta in deltas.items():
            totals[need] = totals.get(need, 0) + delta
    return totals
