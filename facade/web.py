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
  <div class="tabs" style="margin-bottom:12px;">
    <button class="tab active">Entities</button>
    <button class="tab" onclick="window.location='./rules'">Rules</button>
  </div>
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


RULES_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Facade — Rules</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #1c1c1c; color: #e0e0e0; padding: 16px; }
  h1 { font-size: 1.4em; margin-bottom: 4px; }
  .subtitle { color: #888; font-size: 0.85em; margin-bottom: 16px; }
  .nav { display: flex; gap: 8px; margin-bottom: 16px; }
  .nav a { padding: 8px 16px; border-radius: 6px; background: #333; color: #aaa; text-decoration: none; font-size: 0.85em; }
  .nav a.active { background: #4a9eff; color: #fff; }
  .section { margin-bottom: 24px; }
  .section h2 { font-size: 1.1em; margin-bottom: 8px; }
  .btn { padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 0.9em; }
  .btn-primary { background: #4a9eff; color: #fff; }
  .btn-secondary { background: #333; color: #e0e0e0; border: 1px solid #444; }
  .btn-row { display: flex; gap: 8px; margin-bottom: 12px; }
  textarea { width: 100%; min-height: 300px; padding: 12px; border-radius: 8px; border: 1px solid #333; background: #2a2a2a; color: #e0e0e0; font-family: monospace; font-size: 0.85em; resize: vertical; }
  .rule-card { padding: 10px 12px; border: 1px solid #333; border-radius: 6px; margin-bottom: 6px; background: #252525; }
  .rule-header { display: flex; justify-content: space-between; align-items: center; }
  .rule-id { font-family: monospace; font-size: 0.8em; color: #4a9eff; }
  .rule-desc { font-size: 0.9em; }
  .rule-meta { font-size: 0.75em; color: #666; margin-top: 4px; }
  .rule-toggle { cursor: pointer; }
  .event-row { padding: 8px; border-bottom: 1px solid #222; font-size: 0.85em; }
  .event-time { color: #666; font-size: 0.75em; }
  .event-entity { font-family: monospace; color: #4a9eff; }
  .status-msg { padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; font-size: 0.85em; }
  .status-ok { background: rgba(67,160,71,0.15); color: #66bb6a; }
  .status-err { background: rgba(219,68,55,0.15); color: #ef5350; }
  .budget { padding: 10px; background: #252525; border-radius: 6px; font-size: 0.85em; margin-bottom: 12px; }
</style>
</head>
<body>
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
    <h1>Facade Rules</h1>
    <button class="btn btn-secondary" onclick="history.back()">← Back</button>
  </div>
  <p class="subtitle">Manage reaction rules, export data, and view unmatched events</p>
  <div class="nav">
    <a href="./" class="">Entities</a>
    <a href="./rules" class="active">Rules</a>
  </div>

  <div class="section">
    <h2>Current Rules</h2>
    <div class="btn-row">
      <button class="btn btn-secondary" onclick="downloadRules()">Download rules.json</button>
      <button class="btn btn-primary" onclick="document.getElementById('import-section').style.display='block'">Import Rules</button>
      <button class="btn btn-secondary" onclick="exportData()">Export HA Data</button>
    </div>
    <div id="rules-list"></div>
  </div>

  <div class="section" id="import-section" style="display:none;">
    <h2>Import reactions.json</h2>
    <p class="subtitle">Paste your generated reactions.json below</p>
    <textarea id="import-json" placeholder='{"version": 1, "rules": [...]}'></textarea>
    <div class="btn-row" style="margin-top:8px;">
      <button class="btn btn-primary" onclick="importRules()">Validate & Import</button>
      <button class="btn btn-secondary" onclick="document.getElementById('import-section').style.display='none'">Cancel</button>
    </div>
    <div id="import-status"></div>
  </div>

  <div class="section">
    <h2>Escalation Budget</h2>
    <div class="budget" id="budget-info">Loading...</div>
  </div>

  <div class="section">
    <h2>Unmatched Events</h2>
    <p class="subtitle">Events that didn't match any rule</p>
    <div id="unmatched-list"></div>
  </div>

<script>
async function loadRules() {
  const resp = await fetch("./api/rules");
  const data = await resp.json();

  // Rules list
  const list = document.getElementById("rules-list");
  list.innerHTML = data.rules.length === 0
    ? '<div class="rule-card">No rules loaded. Import a reactions.json or export HA data and run batch learning.</div>'
    : "";
  for (const r of data.rules) {
    const card = document.createElement("div");
    card.className = "rule-card";
    const face = r.face?.name || (r.face?.p !== undefined ? `PAD(${r.face.p},${r.face.a},${r.face.d})` : "—");
    const needs = r.needs ? Object.entries(r.needs).map(([k,v]) => `${k}:${v>0?"+":""}${v}`).join(" ") : "";
    card.innerHTML = `
      <div class="rule-header">
        <div><span class="rule-desc">${r.description || r.id}</span> <span class="rule-id">${r.id}</span></div>
        <span style="color:${r.enabled !== false ? '#66bb6a' : '#666'}">${r.enabled !== false ? '●' : '○'}</span>
      </div>
      <div class="rule-meta">
        ${r.match.entity_pattern} | ${r.match.from_state||"*"} → ${r.match.to_state||"*"} | face: ${face} | ${needs} | cooldown: ${r.cooldown_seconds||0}s | priority: ${r.priority||0}
      </div>
    `;
    list.appendChild(card);
  }

  // Budget
  document.getElementById("budget-info").innerHTML = `
    Escalation: ${data.budget.enabled ? "enabled" : "disabled"} |
    Model: ${data.budget.model} |
    Used today: ${data.budget.used}/${data.budget.budget} |
    Remaining: ${data.budget.remaining}
  `;

  // Unmatched events
  const ulist = document.getElementById("unmatched-list");
  ulist.innerHTML = data.unmatched.length === 0
    ? '<div class="event-row" style="color:#666">No unmatched events yet</div>'
    : "";
  for (const e of data.unmatched) {
    if (e.type === "escalation_result") continue;
    const row = document.createElement("div");
    row.className = "event-row";
    row.innerHTML = `
      <span class="event-entity">${e.entity_id}</span>
      ${e.from_state} → ${e.to_state}
      <span class="event-time">${e.timestamp || ""}</span>
    `;
    ulist.appendChild(row);
  }
}

function downloadRules() {
  window.open("./api/rules/download", "_blank");
}

async function exportData() {
  const btn = event.target;
  btn.textContent = "Exporting...";
  btn.disabled = true;
  try {
    const resp = await fetch("./api/export", {method: "POST"});
    const data = await resp.json();
    if (data.ok) {
      btn.textContent = "Export complete!";
      setTimeout(() => { btn.textContent = "Export HA Data"; btn.disabled = false; }, 3000);
    } else {
      btn.textContent = "Export failed";
      btn.disabled = false;
    }
  } catch(e) {
    btn.textContent = "Export failed";
    btn.disabled = false;
  }
}

async function importRules() {
  const text = document.getElementById("import-json").value;
  const status = document.getElementById("import-status");
  try {
    JSON.parse(text);  // validate JSON locally first
  } catch(e) {
    status.innerHTML = `<div class="status-msg status-err">Invalid JSON: ${e.message}</div>`;
    return;
  }
  const resp = await fetch("./api/rules/import", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: text,
  });
  const data = await resp.json();
  if (data.ok) {
    status.innerHTML = `<div class="status-msg status-ok">Imported ${data.rule_count} rules! Rules engine reloaded.</div>`;
    document.getElementById("import-section").style.display = "none";
    loadRules();
  } else {
    status.innerHTML = `<div class="status-msg status-err">Import failed: ${data.error}</div>`;
  }
}

loadRules();
</script>
</body>
</html>"""


# Reference to rules_engine — set by run.py after initialization
_rules_engine = None
_escalation = None

def set_engines(rules_engine, escalation_engine):
    global _rules_engine, _escalation
    _rules_engine = rules_engine
    _escalation = escalation_engine


class ConfigHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.endswith("/api/entities"):
            entities = get_ha_entities()
            config = load_entity_config()
            self._json_response({"entities": entities, "config": config})
        elif self.path.endswith("/api/rules"):
            rules = _rules_engine.rules if _rules_engine else []
            budget = _escalation.get_budget_status() if _escalation else {}
            unmatched = _escalation.get_unmatched_events() if _escalation else []
            self._json_response({"rules": rules, "budget": budget, "unmatched": unmatched})
        elif self.path.endswith("/api/rules/download"):
            import os
            path = "/data/reactions.json"
            if os.path.exists(path):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Disposition", "attachment; filename=reactions.json")
                self.end_headers()
                with open(path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self._json_response({"error": "No reactions.json found"}, 404)
        elif self.path.endswith("/rules"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(RULES_PAGE_HTML.encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length) if length else b""

        if self.path.endswith("/api/entities"):
            body = json.loads(body_bytes)
            entity_config["watched"] = body.get("watched", [])
            entity_config["ignored"] = body.get("ignored", [])
            save_entity_config()
            log.info("Entity config updated: %d watched, %d ignored",
                     len(entity_config["watched"]), len(entity_config["ignored"]))
            self._json_response({"ok": True})
        elif self.path.endswith("/api/rules/import"):
            try:
                data = json.loads(body_bytes)
                if "rules" not in data:
                    self._json_response({"ok": False, "error": "Missing 'rules' key"}, 400)
                    return
                data.setdefault("version", 1)
                with open("/data/reactions.json", "w") as f:
                    json.dump(data, f, indent=2)
                if _rules_engine:
                    _rules_engine.reload()
                rule_count = len(data["rules"])
                log.info("Imported %d rules via web UI", rule_count)
                self._json_response({"ok": True, "rule_count": rule_count})
            except Exception as e:
                self._json_response({"ok": False, "error": str(e)}, 400)
        elif self.path.endswith("/api/export"):
            import threading
            from data_export import export_ha_data
            # Run in background to avoid timeout
            threading.Thread(target=lambda: export_ha_data(days=30), daemon=True).start()
            self._json_response({"ok": True, "message": "Export started"})
        else:
            self.send_response(404)
            self.end_headers()

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass  # suppress default HTTP logs


def start_web_server(port=8099):
    """Start the config web UI server (run in a thread)."""
    load_entity_config()
    server = HTTPServer(("0.0.0.0", port), ConfigHandler)
    log.info("Config UI running on port %d", port)
    server.serve_forever()
