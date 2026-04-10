"""Ingress web UI for Facade add-on configuration."""

import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

log = logging.getLogger("facade.web")

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_REST_URL = "http://supervisor/core/api"
CONFIG_PATH = "/data/entity_config.json"

# Loaded at startup from run.py, updated via web UI
entity_config = {"watched": [], "ignored": []}


def load_entity_config():
    global entity_config
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                entity_config = json.load(f)
        except Exception:
            pass
    return entity_config


def save_entity_config():
    with open(CONFIG_PATH, "w") as f:
        json.dump(entity_config, f)


def get_ha_entities():
    """Fetch all entities from HA grouped by domain."""
    headers = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    try:
        resp = requests.get(f"{HA_REST_URL}/states", headers=headers, timeout=10)
        resp.raise_for_status()
        states = resp.json()
    except Exception as e:
        log.error("Failed to fetch entities: %s", e)
        return {}

    by_domain = {}
    for s in states:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        name = s.get("attributes", {}).get("friendly_name", eid)
        if domain not in by_domain:
            by_domain[domain] = []
        by_domain[domain].append({"id": eid, "name": name, "state": s.get("state", "")})

    for domain in by_domain:
        by_domain[domain].sort(key=lambda e: e["name"].lower())

    return dict(sorted(by_domain.items()))


INDEX_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Facade — Entity Configuration</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #1c1c1c; color: #e0e0e0; padding: 16px;
  }
  h1 { font-size: 1.4em; margin-bottom: 4px; }
  .subtitle { color: #888; font-size: 0.85em; margin-bottom: 16px; }
  .search {
    width: 100%; padding: 10px 12px; border-radius: 8px; border: 1px solid #333;
    background: #2a2a2a; color: #e0e0e0; font-size: 0.95em; margin-bottom: 12px;
  }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tab {
    padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer;
    font-size: 0.85em; background: #333; color: #aaa;
  }
  .tab.active { background: #4a9eff; color: #fff; }
  .domain-group { margin-bottom: 16px; }
  .domain-header {
    font-size: 0.8em; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
    color: #888; padding: 6px 0; border-bottom: 1px solid #333; margin-bottom: 4px;
    display: flex; justify-content: space-between; align-items: center;
  }
  .domain-actions { display: flex; gap: 4px; }
  .entity-row {
    display: flex; align-items: center; padding: 8px 4px; gap: 10px;
    border-bottom: 1px solid #222;
  }
  .entity-row:hover { background: #252525; }
  .entity-name { flex: 1; font-size: 0.9em; }
  .entity-id { color: #666; font-size: 0.75em; font-family: monospace; }
  .entity-state { color: #888; font-size: 0.8em; min-width: 60px; text-align: right; }
  .toggle-group { display: flex; gap: 4px; }
  .toggle-btn {
    padding: 4px 10px; border-radius: 4px; border: 1px solid #444;
    background: #2a2a2a; color: #888; cursor: pointer; font-size: 0.75em;
  }
  .toggle-btn.watch { border-color: #4a9eff; color: #4a9eff; background: rgba(74,158,255,0.1); }
  .toggle-btn.ignore { border-color: #ff6b6b; color: #ff6b6b; background: rgba(255,107,107,0.1); }
  .save-bar {
    position: fixed; bottom: 0; left: 0; right: 0; padding: 12px 16px;
    background: #2a2a2a; border-top: 1px solid #333; display: none;
    justify-content: space-between; align-items: center;
  }
  .save-bar.dirty { display: flex; }
  .save-btn {
    padding: 10px 24px; border-radius: 8px; border: none; cursor: pointer;
    background: #4a9eff; color: #fff; font-size: 0.95em; font-weight: 500;
  }
  .save-status { color: #888; font-size: 0.85em; }
  .count { font-size: 0.8em; color: #666; }
</style>
</head>
<body>
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
    <h1>Entity Configuration</h1>
    <button onclick="history.back()" style="padding:8px 16px; border-radius:6px; border:1px solid #444; background:#2a2a2a; color:#e0e0e0; cursor:pointer; font-size:0.85em;">← Back to HA</button>
  </div>
  <p class="subtitle">Choose which entities your dweller watches or ignores</p>
  <input class="search" type="text" placeholder="Search entities..." id="search">
  <div class="tabs">
    <button class="tab active" data-filter="all">All</button>
    <button class="tab" data-filter="watched">Watched <span class="count" id="watch-count"></span></button>
    <button class="tab" data-filter="ignored">Ignored <span class="count" id="ignore-count"></span></button>
  </div>
  <div id="entities"></div>
  <div class="save-bar" id="save-bar">
    <span class="save-status" id="save-status">Unsaved changes</span>
    <button class="save-btn" onclick="save()">Save & Restart</button>
  </div>
<script>
let entities = {};
let watched = new Set();
let ignored = new Set();
let dirty = false;
let filter = "all";

async function load() {
  const resp = await fetch("./api/entities");
  const data = await resp.json();
  entities = data.entities;
  watched = new Set(data.config.watched || []);
  ignored = new Set(data.config.ignored || []);
  render();
}

function render() {
  const search = document.getElementById("search").value.toLowerCase();
  const container = document.getElementById("entities");
  container.innerHTML = "";

  let watchCount = 0, ignoreCount = 0;

  for (const [domain, items] of Object.entries(entities)) {
    const filtered = items.filter(e => {
      const matchesSearch = !search ||
        e.name.toLowerCase().includes(search) ||
        e.id.toLowerCase().includes(search);
      const matchesFilter =
        filter === "all" ||
        (filter === "watched" && watched.has(e.id)) ||
        (filter === "ignored" && ignored.has(e.id));
      return matchesSearch && matchesFilter;
    });

    if (filtered.length === 0) continue;

    const allWatched = filtered.every(e => watched.has(e.id));
    const allIgnored = filtered.every(e => ignored.has(e.id));

    const group = document.createElement("div");
    group.className = "domain-group";
    group.innerHTML = `<div class="domain-header">
      <span>${domain} (${filtered.length})</span>
      <span class="domain-actions">
        <button class="toggle-btn ${allWatched ? 'watch' : ''}"
                onclick="toggleDomain('${domain}', 'watch')">
          ${allWatched ? '✓ All' : 'Watch all'}</button>
        <button class="toggle-btn ${allIgnored ? 'ignore' : ''}"
                onclick="toggleDomain('${domain}', 'ignore')">
          ${allIgnored ? '✗ All' : 'Ignore all'}</button>
      </span>
    </div>`;

    for (const e of filtered) {
      const isWatched = watched.has(e.id);
      const isIgnored = ignored.has(e.id);
      if (isWatched) watchCount++;
      if (isIgnored) ignoreCount++;

      const row = document.createElement("div");
      row.className = "entity-row";
      row.innerHTML = `
        <div class="entity-name">${e.name}<br><span class="entity-id">${e.id}</span></div>
        <div class="entity-state">${e.state}</div>
        <div class="toggle-group">
          <button class="toggle-btn ${isWatched ? 'watch' : ''}"
                  onclick="toggle('${e.id}', 'watch')">${isWatched ? '✓ Watch' : 'Watch'}</button>
          <button class="toggle-btn ${isIgnored ? 'ignore' : ''}"
                  onclick="toggle('${e.id}', 'ignore')">${isIgnored ? '✗ Ignore' : 'Ignore'}</button>
        </div>
      `;
      group.appendChild(row);
    }
    container.appendChild(group);
  }

  document.getElementById("watch-count").textContent = `(${watchCount})`;
  document.getElementById("ignore-count").textContent = `(${ignoreCount})`;
  document.getElementById("save-bar").className = dirty ? "save-bar dirty" : "save-bar";
}

function toggle(entityId, mode) {
  if (mode === "watch") {
    ignored.delete(entityId);
    watched.has(entityId) ? watched.delete(entityId) : watched.add(entityId);
  } else {
    watched.delete(entityId);
    ignored.has(entityId) ? ignored.delete(entityId) : ignored.add(entityId);
  }
  dirty = true;
  render();
}

function toggleDomain(domain, mode) {
  const items = entities[domain] || [];
  const allSet = items.every(e =>
    mode === "watch" ? watched.has(e.id) : ignored.has(e.id)
  );
  for (const e of items) {
    if (mode === "watch") {
      ignored.delete(e.id);
      allSet ? watched.delete(e.id) : watched.add(e.id);
    } else {
      watched.delete(e.id);
      allSet ? ignored.delete(e.id) : ignored.add(e.id);
    }
  }
  dirty = true;
  render();
}

async function save() {
  document.getElementById("save-status").textContent = "Saving...";
  const resp = await fetch("./api/entities", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({watched: [...watched], ignored: [...ignored]})
  });
  if (resp.ok) {
    dirty = false;
    document.getElementById("save-status").textContent = "Saved! Restarting...";
    render();
    setTimeout(() => {
      document.getElementById("save-status").textContent = "";
    }, 3000);
  } else {
    document.getElementById("save-status").textContent = "Save failed!";
  }
}

document.getElementById("search").addEventListener("input", render);
document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    filter = tab.dataset.filter;
    render();
  });
});

load();
</script>
</body>
</html>"""


class ConfigHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/api/entities"):
            entities = get_ha_entities()
            config = load_entity_config()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"entities": entities, "config": config}).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode())

    def do_POST(self):
        if self.path.endswith("/api/entities"):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            entity_config["watched"] = body.get("watched", [])
            entity_config["ignored"] = body.get("ignored", [])
            save_entity_config()
            log.info("Entity config updated: %d watched, %d ignored",
                     len(entity_config["watched"]), len(entity_config["ignored"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # suppress default HTTP logs


def start_web_server(port=8099):
    """Start the config web UI server (run in a thread)."""
    load_entity_config()
    server = HTTPServer(("0.0.0.0", port), ConfigHandler)
    log.info("Config UI running on port %d", port)
    server.serve_forever()
