import { fmtNum, numOr } from "../format.js";

/**
 * Smart Posture T-Shirt v2 — Circular Bend Duration Timer Ring Component.
 * Visualizes continuous stooping duration with tactile threshold markers.
 */

export class BendTimerComponent {
  constructor(container) {
    this.container = container;
    this.radius = 70;
    this.circumference = 2 * Math.PI * this.radius;
    this.renderInitial();
  }

  renderInitial() {
    this.container.innerHTML = `
      <div class="bend-timer-card">
        <div class="card-title">Bend Duration Timer</div>
        <div class="timer-gauge-wrapper">
          <svg viewBox="0 0 180 180" class="timer-svg" aria-label="Bend timer gauge">
            <!-- Background track -->
            <circle cx="90" cy="90" r="${this.radius}" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="12" />

            <!-- Progress track -->
            <circle id="timer-progress" cx="90" cy="90" r="${this.radius}" fill="none"
                    stroke="#2ecc71" stroke-width="12" stroke-linecap="round"
                    stroke-dasharray="${this.circumference}" stroke-dashoffset="${this.circumference}"
                    transform="rotate(-90 90 90)" class="timer-progress-ring" />

            <!-- Marker tick 1: Vibration delay -->
            <line id="marker-vibrate" x1="90" y1="12" x2="90" y2="26" stroke="#f5c542" stroke-width="3" stroke-linecap="round" transform="rotate(0 90 90)" />

            <!-- Marker tick 2: Buzzer delay -->
            <line id="marker-buzzer" x1="90" y1="12" x2="90" y2="26" stroke="#ff4d5e" stroke-width="3" stroke-linecap="round" transform="rotate(359 90 90)" />
          </svg>

          <!-- Center numeric readout -->
          <div class="timer-center-content">
            <span id="timer-seconds" class="timer-digits">0.0</span>
            <span class="timer-unit">SEC</span>
            <span id="timer-status-badge" class="timer-stage-badge">UPRIGHT</span>
          </div>
        </div>

        <div class="timer-legend">
          <div class="legend-item"><span class="dot dot-vib"></span> Vib: <strong id="lbl-vib-thresh">5s</strong></div>
          <div class="legend-item"><span class="dot dot-buz"></span> Buz: <strong id="lbl-buz-thresh">15s</strong></div>
        </div>
      </div>
    `;

    this.progressRing = document.getElementById("timer-progress");
    this.secondsDisplay = document.getElementById("timer-seconds");
    this.statusBadge = document.getElementById("timer-status-badge");
    this.markerVibrate = document.getElementById("marker-vibrate");
    this.markerBuzzer = document.getElementById("marker-buzzer");
    this.lblVib = document.getElementById("lbl-vib-thresh");
    this.lblBuz = document.getElementById("lbl-buz-thresh");
  }

  update(telemetry, online) {
    if (!telemetry || !online) {
      this.progressRing.style.strokeDashoffset = this.circumference;
      this.progressRing.setAttribute("stroke", "rgba(255,255,255,0.1)");
      this.secondsDisplay.textContent = "0.0";
      this.statusBadge.textContent = "OFFLINE";
      this.statusBadge.className = "timer-stage-badge badge-neutral";
      return;
    }

    const vibDelay = numOr(telemetry.vibrate_delay_s, 5.0);
    const buzDelay = Math.max(0.001, numOr(telemetry.buzzer_delay_s, 15.0));
    const durationMs = numOr(telemetry.bend_duration_ms);
    const durationS = durationMs / 1000.0;
    const state = (telemetry.state || "UPRIGHT").toUpperCase();

    // Update threshold label texts
    this.lblVib.textContent = `${vibDelay}s`;
    this.lblBuz.textContent = `${buzDelay}s`;

    // Position marker ticks around the 360 ring
    const vibAngle = Math.min(360, (vibDelay / buzDelay) * 360);
    this.markerVibrate.setAttribute("transform", `rotate(${vibAngle} 90 90)`);
    this.markerBuzzer.setAttribute("transform", `rotate(360 90 90)`);

    // Center display
    this.secondsDisplay.textContent = fmtNum(durationS);

    // Compute progress fraction relative to buzzer delay (full ring = buzzer delay)
    const fraction = Math.min(1.0, durationS / buzDelay);
    const offset = this.circumference * (1.0 - fraction);
    this.progressRing.style.strokeDashoffset = offset;

    // Ring and badge color based on duration and state
    if (state === "ALERT" || durationS >= buzDelay) {
      this.progressRing.setAttribute("stroke", "#ff4d5e"); // Red alert
      this.statusBadge.textContent = "TIER 2 ALERT";
      this.statusBadge.className = "timer-stage-badge badge-alert";
    } else if (state === "WARNING" || durationS >= vibDelay) {
      this.progressRing.setAttribute("stroke", "#f5c542"); // Yellow warning
      this.statusBadge.textContent = "TIER 1 WARNING";
      this.statusBadge.className = "timer-stage-badge badge-warning";
    } else if (durationS > 0) {
      this.progressRing.setAttribute("stroke", "#3498db"); // Blue early bending
      this.statusBadge.textContent = "BENDING";
      this.statusBadge.className = "timer-stage-badge badge-info";
    } else {
      this.progressRing.setAttribute("stroke", "rgba(255,255,255,0.08)");
      this.statusBadge.textContent = "UPRIGHT";
      this.statusBadge.className = "timer-stage-badge badge-ok";
    }
  }
}
