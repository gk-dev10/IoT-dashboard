/**
 * Smart Posture T-Shirt v2 — Wearable Mirror Component.
 * Displays physical actuator feedback in real time (LEDs, vibration motor, buzzer).
 */

export class WearableMirrorComponent {
  constructor(container) {
    this.container = container;
    this.renderInitial();
  }

  renderInitial() {
    this.container.innerHTML = `
      <div class="mirror-panel-card">
        <div class="panel-header">
          <div class="panel-title-group">
            <span class="card-title">Wearable Hardware Mirror</span>
            <span class="panel-subtitle">Real-time shirt status & physical actuators</span>
          </div>
          <span id="mirror-device-badge" class="badge badge-device">ESP32</span>
        </div>

        <div class="mirror-actuators-grid">
          <!-- 1. RGB LEDs Subsystem -->
          <div class="actuator-block">
            <span class="actuator-label">Status LEDs</span>
            <div class="led-array">
              <!-- Green LED -->
              <div class="led-wrapper">
                <div id="led-green-bulb" class="led-bulb led-green"></div>
                <span class="led-name">OK</span>
              </div>
              <!-- Yellow LED -->
              <div class="led-wrapper">
                <div id="led-yellow-bulb" class="led-bulb led-yellow"></div>
                <span class="led-name">WARN</span>
              </div>
              <!-- Red LED -->
              <div class="led-wrapper">
                <div id="led-red-bulb" class="led-bulb led-red"></div>
                <span class="led-name">ALERT</span>
              </div>
            </div>
          </div>

          <!-- 2. Vibration Motor Subsystem -->
          <div class="actuator-block">
            <span class="actuator-label">Vibration Motor</span>
            <div class="actuator-visual" id="vibration-container">
              <div id="vibration-icon" class="actuator-icon motor-icon">
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2">
                  <!-- Motor central cylinder -->
                  <rect x="7" y="6" width="10" height="12" rx="2" />
                  <line x1="12" y1="2" x2="12" y2="6" />
                  <!-- Haptic wave brackets -->
                  <path class="haptic-wave wave-left" d="M 4 8 C 2 10 2 14 4 16" />
                  <path class="haptic-wave wave-right" d="M 20 8 C 22 10 22 14 20 16" />
                </svg>
              </div>
              <span id="vibration-state-lbl" class="actuator-state-text">IDLE</span>
            </div>
          </div>

          <!-- 3. Piezo Buzzer Subsystem -->
          <div class="actuator-block">
            <span class="actuator-label">Piezo Buzzer</span>
            <div class="actuator-visual" id="buzzer-container">
              <div id="buzzer-icon" class="actuator-icon buzzer-icon">
                <svg viewBox="0 0 24 24" width="32" height="32" fill="none" stroke="currentColor" stroke-width="2">
                  <!-- Speaker cone -->
                  <path d="M 11 5 L 6 9 L 2 9 L 2 15 L 6 15 L 11 19 Z" fill="currentColor" opacity="0.3" stroke="currentColor" />
                  <!-- Sound wave arcs -->
                  <path class="sound-wave wave-1" d="M 15 9 C 16.5 10.5 16.5 13.5 15 15" />
                  <path class="sound-wave wave-2" d="M 18 6 C 21 9 21 15 18 18" />
                </svg>
              </div>
              <span id="buzzer-state-lbl" class="actuator-state-text">IDLE</span>
            </div>
          </div>
        </div>
      </div>
    `;

    this.ledGreen = document.getElementById("led-green-bulb");
    this.ledYellow = document.getElementById("led-yellow-bulb");
    this.ledRed = document.getElementById("led-red-bulb");
    this.vibContainer = document.getElementById("vibration-container");
    this.vibStateLbl = document.getElementById("vibration-state-lbl");
    this.buzContainer = document.getElementById("buzzer-container");
    this.buzStateLbl = document.getElementById("buzzer-state-lbl");
    this.devBadge = document.getElementById("mirror-device-badge");
  }

  update(telemetry, online) {
    if (!telemetry || !online) {
      this.ledGreen.classList.remove("active");
      this.ledYellow.classList.remove("active");
      this.ledRed.classList.remove("active");
      this.vibContainer.classList.remove("active");
      this.vibStateLbl.textContent = "OFFLINE";
      this.buzContainer.classList.remove("active");
      this.buzStateLbl.textContent = "OFFLINE";
      this.devBadge.textContent = "DISCONNECTED";
      this.devBadge.className = "badge badge-neutral";
      return;
    }

    this.devBadge.textContent = `${telemetry.device_id || "vest-01"} · ${telemetry.fw || "v2.0"}`;
    this.devBadge.className = "badge badge-device";

    // 1. LEDs
    if (telemetry.led_green) this.ledGreen.classList.add("active");
    else this.ledGreen.classList.remove("active");

    if (telemetry.led_yellow) this.ledYellow.classList.add("active");
    else this.ledYellow.classList.remove("active");

    if (telemetry.led_red) this.ledRed.classList.add("active");
    else this.ledRed.classList.remove("active");

    // 2. Vibration
    if (telemetry.vibration_active) {
      this.vibContainer.classList.add("active");
      this.vibStateLbl.textContent = "PULSING";
      this.vibStateLbl.style.color = "#f5c542";
    } else {
      this.vibContainer.classList.remove("active");
      this.vibStateLbl.textContent = "IDLE";
      this.vibStateLbl.style.color = "var(--text-muted)";
    }

    // 3. Buzzer
    if (telemetry.buzzer_active) {
      this.buzContainer.classList.add("active");
      this.buzStateLbl.textContent = "ALARMING";
      this.buzStateLbl.style.color = "#ff4d5e";
    } else {
      this.buzContainer.classList.remove("active");
      this.buzStateLbl.textContent = "IDLE";
      this.buzStateLbl.style.color = "var(--text-muted)";
    }
  }
}
