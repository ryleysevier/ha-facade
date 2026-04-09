/**
 * Dweller Card — custom Lovelace card for the Facade add-on.
 * Shows pet needs, mood, and interaction buttons.
 *
 * Installation:
 *   1. Copy this file to /config/www/dweller-card.js
 *   2. Add as a resource: Settings → Dashboards → ⋮ → Resources → /local/dweller-card.js (Module)
 *   3. Add the card to a dashboard with type: custom:dweller-card
 *
 * Config:
 *   type: custom:dweller-card
 *   name: Buddy          # optional, defaults to "Dweller"
 *   entity_prefix: dweller  # optional, matches MQTT discovery unique_id prefix
 */

class DwellerCard extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;

    const prefix = this._config.entity_prefix || "dweller";
    const name = this._config.name || hass.states[`sensor.${prefix}_mood`]?.attributes?.friendly_name?.replace(" Mood", "") || "Dweller";

    const mood = hass.states[`sensor.${prefix}_mood`]?.state || "unknown";
    const moodReason = hass.states[`sensor.${prefix}_mood_reason`]?.state || "";
    const hunger = Number(hass.states[`sensor.${prefix}_hunger`]?.state || 0);
    const boredom = Number(hass.states[`sensor.${prefix}_boredom`]?.state || 0);
    const loneliness = Number(hass.states[`sensor.${prefix}_loneliness`]?.state || 0);
    const energy = Number(hass.states[`sensor.${prefix}_energy`]?.state || 0);
    const happiness = Number(hass.states[`sensor.${prefix}_happiness`]?.state || 0);
    const dominantNeed = hass.states[`sensor.${prefix}_dominant_need`]?.state || "none";

    const moodEmoji = this._moodEmoji(mood);

    this.innerHTML = `
      <ha-card>
        <style>
          .dweller-container {
            padding: 16px;
          }
          .dweller-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 12px;
          }
          .dweller-name {
            font-size: 1.4em;
            font-weight: 500;
          }
          .dweller-mood-emoji {
            font-size: 2em;
          }
          .dweller-mood {
            text-align: center;
            margin-bottom: 16px;
          }
          .dweller-mood-name {
            font-size: 1.1em;
            font-weight: 500;
            text-transform: capitalize;
          }
          .dweller-mood-reason {
            font-size: 0.85em;
            color: var(--secondary-text-color);
            font-style: italic;
            margin-top: 2px;
          }
          .dweller-needs {
            margin-bottom: 16px;
          }
          .dweller-need-row {
            display: flex;
            align-items: center;
            margin-bottom: 6px;
            gap: 8px;
          }
          .dweller-need-label {
            width: 80px;
            font-size: 0.85em;
            color: var(--secondary-text-color);
          }
          .dweller-need-bar {
            flex: 1;
            height: 8px;
            border-radius: 4px;
            background: var(--divider-color);
            overflow: hidden;
          }
          .dweller-need-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.5s ease, background-color 0.5s ease;
          }
          .dweller-need-value {
            width: 35px;
            text-align: right;
            font-size: 0.8em;
            color: var(--secondary-text-color);
          }
          .dweller-buttons {
            display: flex;
            gap: 8px;
            justify-content: center;
          }
          .dweller-btn {
            flex: 1;
            padding: 10px 0;
            border: none;
            border-radius: 8px;
            background: var(--primary-color);
            color: var(--text-primary-color);
            font-size: 0.9em;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            transition: opacity 0.2s;
          }
          .dweller-btn:active {
            opacity: 0.7;
          }
          .dweller-alert {
            text-align: center;
            padding: 6px;
            margin-bottom: 12px;
            border-radius: 6px;
            font-size: 0.85em;
            background: var(--warning-color, #ff9800);
            color: #fff;
          }
        </style>
        <div class="dweller-container">
          <div class="dweller-header">
            <span class="dweller-name">${name}</span>
            <span class="dweller-mood-emoji">${moodEmoji}</span>
          </div>

          <div class="dweller-mood">
            <div class="dweller-mood-name">${mood.replace(/_/g, " ")}</div>
            ${moodReason ? `<div class="dweller-mood-reason">${moodReason}</div>` : ""}
          </div>

          ${dominantNeed !== "none" && dominantNeed !== "None" && dominantNeed !== ""
            ? `<div class="dweller-alert">⚠ ${name} is feeling ${dominantNeed}!</div>`
            : ""}

          <div class="dweller-needs">
            ${this._needBar("Hunger", hunger, true)}
            ${this._needBar("Boredom", boredom, true)}
            ${this._needBar("Loneliness", loneliness, true)}
            ${this._needBar("Energy", energy, false)}
            ${this._needBar("Happiness", happiness, false)}
          </div>

          <div class="dweller-buttons">
            <button class="dweller-btn" id="btn-feed">🍖 Feed</button>
            <button class="dweller-btn" id="btn-pet">💜 Pet</button>
            <button class="dweller-btn" id="btn-play">🎮 Play</button>
          </div>
        </div>
      </ha-card>
    `;

    this.querySelector("#btn-feed").addEventListener("click", () => this._press("feed"));
    this.querySelector("#btn-pet").addEventListener("click", () => this._press("pet"));
    this.querySelector("#btn-play").addEventListener("click", () => this._press("play"));
  }

  _press(action) {
    const prefix = this._config.entity_prefix || "dweller";
    this._hass.callService("button", "press", {
      entity_id: `button.${action}_${this._config.name?.toLowerCase() || prefix}`,
    });
  }

  _needBar(label, value, inverse) {
    // inverse: high = bad (hunger, boredom, loneliness), low = bad (energy, happiness)
    const displayValue = Math.round(value);
    let color;
    if (inverse) {
      color = value > 70 ? "var(--error-color, #db4437)" : value > 40 ? "var(--warning-color, #ff9800)" : "var(--success-color, #43a047)";
    } else {
      color = value < 30 ? "var(--error-color, #db4437)" : value < 60 ? "var(--warning-color, #ff9800)" : "var(--success-color, #43a047)";
    }
    return `
      <div class="dweller-need-row">
        <span class="dweller-need-label">${label}</span>
        <div class="dweller-need-bar">
          <div class="dweller-need-fill" style="width: ${displayValue}%; background: ${color};"></div>
        </div>
        <span class="dweller-need-value">${displayValue}%</span>
      </div>
    `;
  }

  _moodEmoji(mood) {
    const map = {
      happy: "😊", sad: "😢", angry: "😠", scared: "😨", surprised: "😲",
      content: "😌", excited: "🤩", bored: "😑", curious: "🤔", love: "😍",
      disgusted: "🤢", jealous: "😒", proud: "😤", guilty: "😥", hopeful: "🤞",
      nervous: "😬", peaceful: "😇", mischievous: "😏", confused: "😵‍💫", determined: "💪",
      cozy_evening: "🕯️", morning_energy: "☀️", too_hot: "🥵", too_cold: "🥶",
      perfect_temp: "👌", hungry: "🍽️", tired: "😴", exhausted: "🥱",
      playful: "🎾", lonely: "🥺", calm: "🧘", zen: "☮️", napping: "💤", hyper: "⚡",
      doorbell: "🔔", someone_arrived: "👋", someone_left: "🚪", owner_home: "🏠",
      owner_away: "😿", party_mode: "🎉", rain_detected: "🌧️", storm_warning: "⛈️",
      sunny: "☀️", thunderstorm: "🌩️", deep_night: "🌙", celebration: "🥳",
      gaming: "🎮", stargazing: "✨", meditation: "🧘",
      unknown: "❓",
    };
    return map[mood] || "🐾";
  }

  setConfig(config) {
    this._config = config;
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig() {
    return { name: "Buddy", entity_prefix: "dweller" };
  }
}

customElements.define("dweller-card", DwellerCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "dweller-card",
  name: "Dweller Card",
  description: "Shows your Dweller pet's needs, mood, and interaction buttons",
  preview: true,
});
