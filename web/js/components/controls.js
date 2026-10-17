/**
 * Smart Posture T-Shirt v2 — Command & Configuration Control Panel.
 * Sends bi-directional commands to the vest with real-time feedback.
 */

import { api } from "../api.js";

export class ControlsComponent {
  constructor(container) {
    this.container = container;
    this.calibratingTimer = null;
    this.calibratingStartTime = null;
    this.pendingConfigTarget = null;
    this.renderInitial();
    this.attachEvents();
  }

  renderInitial() {
    this.container.innerHTML = `
      <div class="controls-panel-card">
        <div class="panel-header">
          <div>
            <span class="card-title">Vest Remote Control</span>
            <span class="panel-subtitle">Transmit commands & configure posture thresholds</span>
          </div>
          <span id="ctrl-offline-warning" class="offline-pill" style="display: none;">
            Vest offline — queued commands expire in 60s
          </span>
        </div>

        <div class="controls-grid">
          <!-- 1. Posture Calibration -->
          <div class="ctrl-subcard">
            <span class="ctrl-subcard-title">1. Posture Calibration</span>
            <p class="ctrl-instruction">Stand tall and keep still for 2 seconds.</p>
            <div class="ctrl-action-row">
              <button id="btn-calibrate" class="btn btn-primary">
                <span class="btn-icon">🧍</span> Calibrate Vest
              </button>
              <span id="cal-status-text" class="status-indicator">Ready</span>
            </div>
          </div>

          <!-- 2. Alert Muting -->
          <div class="ctrl-subcard">
            <span class="ctrl-subcard-title">2. Alert Silence / Mute</span>
            <p class="ctrl-instruction">Temporarily silence vibration and buzzer audio.</p>
            <div class="btn-group">
              <button id="btn-mute-1m" class="btn btn-secondary">Mute 1 min</button>
              <button id="btn-mute-5m" class="btn btn-secondary">Mute 5 min</button>
              <button id="btn-unmute" class="btn btn-outline">Un-mute</button>
            </div>
            <div class="mute-state-indicator">
              Current state: <strong id="lbl-mute-status">Active (unmuted)</strong>
            </div>
          </div>

          <!-- 3. Hardware Actuator Test -->
          <div class="ctrl-subcard">
            <span class="ctrl-subcard-title">3. Actuator Test</span>
            <p class="ctrl-instruction">Trigger 2-second diagnostic bursts on the vest.</p>
            <div class="btn-group">
              <button id="btn-test-buzzer" class="btn btn-secondary">🔊 Test Buzzer</button>
              <button id="btn-test-vib" class="btn btn-secondary">📳 Test Vibration</button>
              <button id="btn-test-leds" class="btn btn-secondary">💡 Test LEDs</button>
            </div>
          </div>

          <!-- 4. Threshold & Delay Configuration -->
          <div class="ctrl-subcard ctrl-span-all">
            <div class="thresh-header">
              <span class="ctrl-subcard-title">4. Posture Thresholds & Alert Timing</span>
              <div class="thresh-actions">
                <button id="btn-reset-thresh" class="btn btn-text">Reset Defaults (20°, 15°, 5s, 15s)</button>
                <button id="btn-apply-thresh" class="btn btn-success">Apply Changes</button>
              </div>
            </div>

            <div class="sliders-grid">
              <!-- Bend-On Slider -->
              <div class="slider-field">
                <div class="slider-labels">
                  <label for="input-bend-on">Bend-On Threshold (Trigger)</label>
                  <span class="slider-val" id="val-bend-on">20°</span>
                </div>
                <input type="range" id="input-bend-on" min="5" max="60" step="1" value="20" class="range-slider" />
                <span class="field-error" id="err-bend-on"></span>
              </div>

              <!-- Bend-Off Slider -->
              <div class="slider-field">
                <div class="slider-labels">
                  <label for="input-bend-off">Bend-Off Threshold (Recovery)</label>
                  <span class="slider-val" id="val-bend-off">15°</span>
                </div>
                <input type="range" id="input-bend-off" min="2" max="58" step="1" value="15" class="range-slider" />
                <span class="field-error" id="err-bend-off"></span>
              </div>

              <!-- Vibrate Delay Slider -->
              <div class="slider-field">
                <div class="slider-labels">
                  <label for="input-vib-delay">Vibrate Alert Delay</label>
                  <span class="slider-val" id="val-vib-delay">5s</span>
                </div>
                <input type="range" id="input-vib-delay" min="1" max="60" step="1" value="5" class="range-slider" />
                <span class="field-error" id="err-vib-delay"></span>
              </div>

              <!-- Buzzer Delay Slider -->
              <div class="slider-field">
                <div class="slider-labels">
                  <label for="input-buz-delay">Buzzer Alert Delay</label>
                  <span class="slider-val" id="val-buz-delay">15s</span>
                </div>
                <input type="range" id="input-buz-delay" min="2" max="120" step="1" value="15" class="range-slider" />
                <span class="field-error" id="err-buz-delay"></span>
              </div>
            </div>

            <div class="config-status-bar">
              <span id="config-status-msg" class="status-msg"></span>
            </div>
          </div>
        </div>

        <!-- 5. Recent Command Dispatch Audit Log -->
        <div class="command-audit-section">
          <span class="audit-title">Recent Command Dispatch Audit</span>
          <div id="command-audit-list" class="audit-list">
            <span class="audit-empty">No commands dispatched yet.</span>
          </div>
        </div>
      </div>
    `;

    // Elements
    this.btnCalibrate = document.getElementById("btn-calibrate");
    this.calStatusText = document.getElementById("cal-status-text");
    this.btnMute1m = document.getElementById("btn-mute-1m");
    this.btnMute5m = document.getElementById("btn-mute-5m");
    this.btnUnmute = document.getElementById("btn-unmute");
    this.lblMuteStatus = document.getElementById("lbl-mute-status");

    this.btnTestBuzzer = document.getElementById("btn-test-buzzer");
    this.btnTestVib = document.getElementById("btn-test-vib");
    this.btnTestLeds = document.getElementById("btn-test-leds");

    this.inBendOn = document.getElementById("input-bend-on");
    this.inBendOff = document.getElementById("input-bend-off");
    this.inVibDelay = document.getElementById("input-vib-delay");
    this.inBuzDelay = document.getElementById("input-buz-delay");

    this.valBendOn = document.getElementById("val-bend-on");
    this.valBendOff = document.getElementById("val-bend-off");
    this.valVibDelay = document.getElementById("val-vib-delay");
    this.valBuzDelay = document.getElementById("val-buz-delay");

    this.errBendOn = document.getElementById("err-bend-on");
    this.errBendOff = document.getElementById("err-bend-off");
    this.errVibDelay = document.getElementById("err-vib-delay");
    this.errBuzDelay = document.getElementById("err-buz-delay");

    this.btnResetThresh = document.getElementById("btn-reset-thresh");
    this.btnApplyThresh = document.getElementById("btn-apply-thresh");
    this.configStatusMsg = document.getElementById("config-status-msg");
    this.offlineWarning = document.getElementById("ctrl-offline-warning");
    this.auditList = document.getElementById("command-audit-list");
  }

  attachEvents() {
    // 1. Calibrate button
    this.btnCalibrate.addEventListener("click", async () => {
      this.btnCalibrate.disabled = true;
      this.calStatusText.textContent = "Sending command…";
      try {
        await api.sendCommand({ type: "calibrate" });
        this.calStatusText.textContent = "Dispatched. Stand still…";
        this.calibratingStartTime = Date.now();
      } catch (err) {
        this.calStatusText.textContent = `Failed: ${err.message}`;
        this.btnCalibrate.disabled = false;
      }
    });

    // 2. Mute buttons
    this.btnMute1m.addEventListener("click", () => this.sendMute(60));
    this.btnMute5m.addEventListener("click", () => this.sendMute(300));
    this.btnUnmute.addEventListener("click", () => this.sendMute(0));

    // 3. Actuator test buttons
    const triggerTest = async (btn, target) => {
      btn.disabled = true;
      try {
        await api.sendCommand({ type: "test", target });
      } catch (e) {
        console.error("Test command error:", e);
      }
      setTimeout(() => (btn.disabled = false), 2500);
    };

    this.btnTestBuzzer.addEventListener("click", () => triggerTest(this.btnTestBuzzer, "buzzer"));
    this.btnTestVib.addEventListener("click", () => triggerTest(this.btnTestVib, "vibration"));
    this.btnTestLeds.addEventListener("click", () => triggerTest(this.btnTestLeds, "leds"));

    // 4. Sliders live validation
    const onSliderChange = () => {
      this.valBendOn.textContent = `${this.inBendOn.value}°`;
      this.valBendOff.textContent = `${this.inBendOff.value}°`;
      this.valVibDelay.textContent = `${this.inVibDelay.value}s`;
      this.valBuzDelay.textContent = `${this.inBuzDelay.value}s`;
      this.validateThresholds();
    };

    this.inBendOn.addEventListener("input", onSliderChange);
    this.inBendOff.addEventListener("input", onSliderChange);
    this.inVibDelay.addEventListener("input", onSliderChange);
    this.inBuzDelay.addEventListener("input", onSliderChange);

    // Reset defaults
    this.btnResetThresh.addEventListener("click", () => {
      this.inBendOn.value = 20;
      this.inBendOff.value = 15;
      this.inVibDelay.value = 5;
      this.inBuzDelay.value = 15;
      onSliderChange();
    });

    // Apply config
    this.btnApplyThresh.addEventListener("click", async () => {
      if (!this.validateThresholds()) return;

      const bendOn = parseFloat(this.inBendOn.value);
      const bendOff = parseFloat(this.inBendOff.value);
      const vibDelay = parseFloat(this.inVibDelay.value);
      const buzDelay = parseFloat(this.inBuzDelay.value);

      this.btnApplyThresh.disabled = true;
      this.configStatusMsg.textContent = "Sent, waiting for the vest…";
      this.configStatusMsg.className = "status-msg text-pending";

      this.pendingConfigTarget = {
        bend_on_deg: bendOn,
        bend_off_deg: bendOff,
        vibrate_delay_s: vibDelay,
        buzzer_delay_s: buzDelay,
      };

      try {
        await api.sendCommand({
          type: "config",
          bend_on_deg: bendOn,
          bend_off_deg: bendOff,
          vibrate_delay_s: vibDelay,
          buzzer_delay_s: buzDelay,
        });
      } catch (err) {
        this.configStatusMsg.textContent = `Error: ${err.message}`;
        this.configStatusMsg.className = "status-msg text-error";
        this.btnApplyThresh.disabled = false;
      }
    });
  }

  async sendMute(seconds) {
    try {
      await api.sendCommand({ type: "mute", seconds });
    } catch (e) {
      console.error("Mute command error:", e);
    }
  }

  validateThresholds() {
    const bendOn = parseFloat(this.inBendOn.value);
    const bendOff = parseFloat(this.inBendOff.value);
    const vibDelay = parseFloat(this.inVibDelay.value);
    const buzDelay = parseFloat(this.inBuzDelay.value);

    let valid = true;

    // Rule 1: bend_off <= bend_on - 2
    if (bendOff > bendOn - 2) {
      this.errBendOff.textContent = `Must be ≤ ${bendOn - 2}° (bend-on minus 2°)`;
      valid = false;
    } else {
      this.errBendOff.textContent = "";
    }

    // Rule 2: buz_delay > vib_delay
    if (buzDelay <= vibDelay) {
      this.errBuzDelay.textContent = `Must be > ${vibDelay}s (vibrate delay)`;
      valid = false;
    } else {
      this.errBuzDelay.textContent = "";
    }

    this.btnApplyThresh.disabled = !valid;
    return valid;
  }

  update(telemetry, online, commands) {
    // 1. Offline warnings & control disabling
    if (!online) {
      this.offlineWarning.style.display = "inline-block";
    } else {
      this.offlineWarning.style.display = "none";
    }

    if (telemetry) {
      const state = (telemetry.state || "").toUpperCase();

      // Check Calibration state transition
      if (state === "CALIBRATING") {
        this.calStatusText.textContent = "Vest is calibrating… keep still";
        this.calStatusText.style.color = "#f5c542";
        this.btnCalibrate.disabled = true;

        if (this.calibratingStartTime && Date.now() - this.calibratingStartTime > 12000) {
          this.calStatusText.textContent = "Warning: Calibration taking >12s. Check sensor wiring.";
          this.calStatusText.style.color = "#ff4d5e";
          this.btnCalibrate.disabled = false;
        }
      } else {
        if (this.calibratingStartTime) {
          this.calStatusText.textContent = "Calibration complete!";
          this.calStatusText.style.color = "#2ecc71";
          this.calibratingStartTime = null;
          setTimeout(() => (this.calStatusText.textContent = "Ready"), 3000);
        }
        this.btnCalibrate.disabled = false;
      }

      // Check Mute state
      if (telemetry.muted) {
        this.lblMuteStatus.textContent = "MUTED (Alerts silenced)";
        this.lblMuteStatus.style.color = "#f5c542";
      } else {
        this.lblMuteStatus.textContent = "Active (Alerts armed)";
        this.lblMuteStatus.style.color = "#2ecc71";
      }

      // Check Pending Config confirmation
      if (this.pendingConfigTarget) {
        const matches =
          Math.abs((telemetry.bend_on_deg || 0) - this.pendingConfigTarget.bend_on_deg) < 0.1 &&
          Math.abs((telemetry.bend_off_deg || 0) - this.pendingConfigTarget.bend_off_deg) < 0.1 &&
          Math.abs((telemetry.vibrate_delay_s || 0) - this.pendingConfigTarget.vibrate_delay_s) < 0.1 &&
          Math.abs((telemetry.buzzer_delay_s || 0) - this.pendingConfigTarget.buzzer_delay_s) < 0.1;

        if (matches) {
          this.configStatusMsg.textContent = "Applied successfully!";
          this.configStatusMsg.className = "status-msg text-success";
          this.pendingConfigTarget = null;
          this.btnApplyThresh.disabled = false;
          setTimeout(() => {
            if (this.configStatusMsg.textContent === "Applied successfully!") {
              this.configStatusMsg.textContent = "";
            }
          }, 4000);
        }
      }
    }

    // 2. Command audit list
    if (Array.isArray(commands) && commands.length > 0) {
      this.auditList.innerHTML = commands
        .map((cmd) => {
          let badgeClass = "badge-neutral";
          if (cmd.status === "sent") badgeClass = "badge-ok";
          else if (cmd.status === "pending") badgeClass = "badge-warning";
          else if (cmd.status === "expired") badgeClass = "badge-alert";

          const timeStr = cmd.created_ts ? cmd.created_ts.substring(11, 19) : "";
          const typeStr = cmd.type ? cmd.type.toUpperCase() : "CMD";

          return `
            <div class="audit-item">
              <span class="audit-time">${timeStr}</span>
              <span class="audit-type"><strong>${typeStr}</strong></span>
              <span class="badge ${badgeClass}">${cmd.status.toUpperCase()}</span>
            </div>
          `;
        })
        .join("");
    } else {
      this.auditList.innerHTML = `<span class="audit-empty">No commands dispatched yet.</span>`;
    }
  }
}
