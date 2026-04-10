"""Data export — fetches HA entity metadata and state history for batch learning."""

import json
import logging
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import requests

log = logging.getLogger("facade.export")

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_REST_URL = "http://supervisor/core/api"
EXPORT_PATH = "/data/ha_export.json"


def export_ha_data(watched_domains: set | None = None, days: int = 30) -> str:
    """Export entity metadata + state history summary to a JSON file.

    Returns the path to the export file.
    """
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}

    log.info("Starting HA data export (%d days)...", days)

    # --- Phase 1: Entity metadata ---
    log.info("Fetching entity states...")
    try:
        resp = requests.get(f"{HA_REST_URL}/states", headers=headers, timeout=30)
        resp.raise_for_status()
        all_states = resp.json()
    except Exception as e:
        log.error("Failed to fetch states: %s", e)
        return ""

    # Filter to watched domains
    entities = []
    for s in all_states:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        if watched_domains and domain not in watched_domains:
            continue
        # Skip our own entities
        if "facade" in eid or "dweller" in eid:
            continue
        entities.append({
            "entity_id": eid,
            "friendly_name": s.get("attributes", {}).get("friendly_name", eid),
            "domain": domain,
            "device_class": s.get("attributes", {}).get("device_class"),
            "unit": s.get("attributes", {}).get("unit_of_measurement"),
            "current_state": s.get("state"),
        })

    log.info("Found %d entities across watched domains", len(entities))

    # --- Phase 2: State history ---
    start_time = (datetime.now() - timedelta(days=days)).isoformat()
    entity_data = []
    batch_size = 10
    entity_ids = [e["entity_id"] for e in entities]

    for i in range(0, len(entity_ids), batch_size):
        batch = entity_ids[i:i + batch_size]
        log.info("Fetching history batch %d/%d (%d entities)...",
                 i // batch_size + 1, (len(entity_ids) + batch_size - 1) // batch_size, len(batch))

        for eid in batch:
            try:
                resp = requests.get(
                    f"{HA_REST_URL}/history/period/{start_time}",
                    params={
                        "filter_entity_id": eid,
                        "minimal_response": "",
                        "significant_changes_only": "",
                        "no_attributes": "",
                    },
                    headers=headers,
                    timeout=30,
                )
                if resp.status_code != 200:
                    continue

                history = resp.json()
                if not history or not history[0]:
                    continue

                states = history[0]
                transitions = []
                for j in range(1, len(states)):
                    old_s = states[j - 1].get("state", "")
                    new_s = states[j].get("state", "")
                    if old_s != new_s:
                        transitions.append((old_s, new_s))

                # Summarize
                transition_counts = Counter(transitions)
                common = [
                    {"from": f, "to": t, "count": c}
                    for (f, t), c in transition_counts.most_common(10)
                ]

                entity_meta = next((e for e in entities if e["entity_id"] == eid), {})
                entity_data.append({
                    **entity_meta,
                    "total_changes": len(transitions),
                    "daily_change_count": round(len(transitions) / max(days, 1), 1),
                    "common_transitions": common,
                    "unique_states": list(set(s.get("state", "") for s in states)),
                })

            except Exception as e:
                log.warning("Failed to fetch history for %s: %s", eid, e)

        # Rate limit between batches
        if i + batch_size < len(entity_ids):
            time.sleep(1)

    # --- Phase 3: Statistics for entities with long-term data ---
    # (sensors with state_class get statistics beyond recorder retention)
    stat_entities = [e["entity_id"] for e in entities
                     if e.get("domain") == "sensor" and e.get("unit")]
    if stat_entities:
        log.info("Fetching statistics for %d sensor entities...", len(stat_entities))
        try:
            resp = requests.post(
                f"{HA_REST_URL}/history/statistics",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "statistic_ids": stat_entities[:50],  # cap at 50
                    "period": "day",
                    "start_time": start_time,
                },
                timeout=30,
            )
            # Statistics add context but aren't critical — don't fail on error
        except Exception:
            pass

    # --- Build export document ---
    # Sort by activity level
    entity_data.sort(key=lambda e: e.get("daily_change_count", 0), reverse=True)

    busiest = [e["entity_id"] for e in entity_data[:10] if e.get("daily_change_count", 0) > 10]
    quietest = [e["entity_id"] for e in entity_data if e.get("daily_change_count", 0) == 0]

    export = {
        "exported_at": datetime.now().isoformat(),
        "export_days": days,
        "entity_count": len(entity_data),
        "statistics": {
            "total_entities": len(entity_data),
            "entities_with_changes": sum(1 for e in entity_data if e.get("total_changes", 0) > 0),
            "avg_changes_per_day": round(
                sum(e.get("daily_change_count", 0) for e in entity_data) / max(len(entity_data), 1), 1
            ),
            "busiest_entities": busiest,
            "quietest_entities": quietest[:10],
        },
        "entities": entity_data,
    }

    try:
        with open(EXPORT_PATH, "w") as f:
            json.dump(export, f, indent=2)
        log.info("Export complete: %d entities written to %s", len(entity_data), EXPORT_PATH)
    except Exception as e:
        log.error("Failed to write export: %s", e)
        return ""

    return EXPORT_PATH
