import { fmtNum } from "../format.js";

/**
 * Smart Posture T-Shirt v2 — Sensor Diagnostics & Health Strip Component.
 */

export class SensorHealthComponent {
  constructor(container) {
    this.container = container;
    this.renderInitial();
  }

  renderInitial() {
    this.container.innerHTML = `
      <div class="health-strip-card">
        <div class="card-title">Sensor Health & Kinematics Diagnostic</div>
        <div class="sensor-chips-grid">
          <!-- MPU6050 IMU -->
          <div class="sensor-chip" id="chip-mpu">
            <span class="chip-name">MPU6050 (Trunk)</span>
            <span class="chip-status badge badge-neutral" id="status-mpu">—</span>
          </div>

          <!-- ADXL345 Thigh -->
          <div class="sensor-chip" id="chip-adxl">
            <span class="chip-name">ADXL345 (Thigh)</span>
            <span class="chip-status badge badge-neutral" id="status-adxl">—</span>
          </div>

          <!-- MAX30102 Pulse -->
          <div class="sensor-chip" id="chip-max">
            <span class="chip-name">MAX3010x (Pulse)</span>
            <span class="chip-status badge badge-neutral" id="status-max">—</span>
          </div>

          <!-- DHT11 Air -->
          <div class="sensor-chip" id="chip-dht">
            <span class="chip-name">DHT11 (Air Env)</span>
            <span class="chip-status badge badge-neutral" id="status-dht">—</span>
          </div>

          <!-- Flex Sensor Strip -->
          <div class="sensor-chip" id="chip-flex">
            <span class="chip-name">Back Flex Sensors</span>
            <span class="chip-status badge badge-neutral" id="status-flex">—</span>
          </div>

          <!-- Kinematics: Pose -->
          <div class="sensor-chip chip-kinematic">
            <span class="chip-name">Posture Pose</span>
            <span class="chip-value" id="val-pose">—</span>
          </div>

          <!-- Kinematics: Motion -->
          <div class="sensor-chip chip-kinematic">
            <span class="chip-name">Kinetic Activity</span>
            <span class="chip-value" id="val-motion">—</span>
          </div>

          <!-- Thigh Tilt Angle -->
          <div class="sensor-chip chip-kinematic">
            <span class="chip-name">Thigh Tilt Angle</span>
            <span class="chip-value" id="val-tilt">—</span>
          </div>
        </div>
      </div>
    `;

    this.sMpu = document.getElementById("status-mpu");
    this.sAdxl = document.getElementById("status-adxl");
    this.sMax = document.getElementById("status-max");
    this.sDht = document.getElementById("status-dht");
    this.sFlex = document.getElementById("status-flex");

    this.vPose = document.getElementById("val-pose");
    this.vMotion = document.getElementById("val-motion");
    this.vTilt = document.getElementById("val-tilt");
  }

  update(telemetry, online) {
    if (!telemetry || !online) {
      this.sMpu.textContent = "—";
      this.sMpu.className = "chip-status badge badge-neutral";
      this.sAdxl.textContent = "—";
      this.sAdxl.className = "chip-status badge badge-neutral";
      this.sMax.textContent = "—";
      this.sMax.className = "chip-status badge badge-neutral";
      this.sDht.textContent = "—";
      this.sDht.className = "chip-status badge badge-neutral";
      this.sFlex.textContent = "—";
      this.sFlex.className = "chip-status badge badge-neutral";

      this.vPose.textContent = "—";
      this.vMotion.textContent = "—";
      this.vTilt.textContent = "—";
      return;
    }

    const setStatus = (elem, isOk) => {
      if (isOk) {
        elem.textContent = "OK";
        elem.className = "chip-status badge badge-ok";
      } else {
        elem.textContent = "FAULT";
        elem.className = "chip-status badge badge-alert";
      }
    };

    // Sensor checks
    setStatus(this.sMpu, telemetry.mpu_ok);
    setStatus(this.sAdxl, telemetry.adxl_ok);
    setStatus(this.sMax, telemetry.max_ok);
    // DHT11 doesn't have a separate boolean flag in protocol, check if temperature is not null
    setStatus(this.sDht, telemetry.temperature_c !== null);

    // Flex status
    if (telemetry.flex_enabled === false || telemetry.flex_enabled === 0) {
      this.sFlex.textContent = "Not fitted";
      this.sFlex.className = "chip-status badge badge-neutral";
    } else {
      setStatus(this.sFlex, telemetry.flex_upper !== null || telemetry.flex_lower !== null);
    }

    // Kinematics
    this.vPose.textContent = telemetry.is_standing ? "Standing" : "Sitting / Lying";
    this.vMotion.textContent = telemetry.moving ? "Active (Moving)" : "Still";
    this.vTilt.textContent =
      fmtNum(telemetry.adxl_tilt_deg) === "—" ? "—" : `${fmtNum(telemetry.adxl_tilt_deg)}°`;
  }
}
