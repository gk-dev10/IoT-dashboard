/**
 * Smart Posture T-Shirt v2 — Interactive Side-View Body Figure Component.
 * Visualizes user spine pitch, sitting/standing thigh posture, and motion tag.
 */

export class BodyFigureComponent {
  constructor(container) {
    this.container = container;
    this.renderInitial();
  }

  renderInitial() {
    this.container.innerHTML = `
      <div class="body-figure-card">
        <div class="figure-header">
          <span class="card-title">Side-View Posture</span>
          <span id="figure-moving-tag" class="badge badge-moving" style="display: none;">MOVING</span>
        </div>
        <div class="figure-stage">
          <svg id="posture-svg" viewBox="0 0 240 280" class="figure-svg" aria-label="Body posture silhouette">
            <!-- Floor / Base line -->
            <line x1="20" y1="260" x2="220" y2="260" stroke="rgba(255,255,255,0.15)" stroke-width="2" stroke-linecap="round" />

            <!-- Chair silhouette (shows when sitting) -->
            <g id="chair-group" opacity="0" class="chair-svg">
              <path d="M 60 170 L 115 170 L 115 260 M 60 170 L 60 90 M 115 260 L 105 260"
                    fill="none" stroke="rgba(255,255,255,0.2)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
            </g>

            <!-- Angle guideline / threshold indicator -->
            <g id="threshold-guideline" transform="translate(120, 160)">
              <!-- Vertical reference line -->
              <line x1="0" y1="0" x2="0" y2="-120" stroke="rgba(255,255,255,0.15)" stroke-width="1.5" stroke-dasharray="3,3" />
              <!-- Threshold arc line -->
              <line id="threshold-ray" x1="0" y1="0" x2="41" y2="-112" stroke="rgba(245, 197, 66, 0.4)" stroke-width="1.5" stroke-dasharray="4,4" />
              <text id="threshold-label" x="46" y="-115" fill="rgba(245, 197, 66, 0.7)" font-size="11" font-family="system-ui">20°</text>
            </g>

            <!-- Lower Body: Calf / Foot (fixed anchor) -->
            <g id="lower-leg-group">
              <path d="M 120 205 L 122 258 L 138 258" fill="none" stroke="#4a5d78" stroke-width="14" stroke-linecap="round" stroke-linejoin="round" />
            </g>

            <!-- Thigh (Rotates at knee (120, 205) or hip (120, 160)) -->
            <g id="thigh-group">
              <!-- Standing: (120,160) to (120,205). Sitting: (75, 160) to (120,160) -->
              <path id="thigh-bone" d="M 120 160 L 120 205" fill="none" stroke="#5a7394" stroke-width="16" stroke-linecap="round" />
            </g>

            <!-- Upper Body (Torso, Arms, Head) - Rotates around Hip (120, 160) -->
            <g id="torso-group" class="torso-pivot">
              <!-- Spine / Torso -->
              <path id="torso-spine" d="M 120 160 L 120 85" fill="none" stroke="#2ecc71" stroke-width="18" stroke-linecap="round" />
              <!-- Chest & T-shirt overlay -->
              <path id="torso-chest" d="M 120 150 L 132 120 L 124 85" fill="none" stroke="rgba(255,255,255,0.4)" stroke-width="3" stroke-linecap="round" />
              <!-- Arm -->
              <path id="torso-arm" d="M 120 95 L 135 125 L 132 155" fill="none" stroke="#4a5d78" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" />
              <!-- Neck & Head -->
              <circle id="torso-head" cx="120" cy="55" r="18" fill="#5a7394" stroke="#2ecc71" stroke-width="3" />
              <!-- Eye / gaze direction -->
              <circle id="torso-eye" cx="132" cy="53" r="2.5" fill="#ffffff" />
            </g>

            <!-- Hip joint marker -->
            <circle cx="120" cy="160" r="5" fill="#ffffff" opacity="0.6" />
          </svg>
        </div>
        <div class="figure-footer">
          <div class="figure-readout">
            <span class="readout-label">Trunk Pitch:</span>
            <span id="figure-pitch-val" class="readout-value">—°</span>
          </div>
          <div class="figure-readout">
            <span class="readout-label">Pose:</span>
            <span id="figure-pose-val" class="readout-value">—</span>
          </div>
        </div>
      </div>
    `;

    this.movingTag = document.getElementById("figure-moving-tag");
    this.torsoGroup = document.getElementById("torso-group");
    this.torsoSpine = document.getElementById("torso-spine");
    this.torsoHead = document.getElementById("torso-head");
    this.thighGroup = document.getElementById("thigh-group");
    this.chairGroup = document.getElementById("chair-group");
    this.thresholdRay = document.getElementById("threshold-ray");
    this.thresholdLabel = document.getElementById("threshold-label");
    this.pitchVal = document.getElementById("figure-pitch-val");
    this.poseVal = document.getElementById("figure-pose-val");
  }

  update(telemetry, online) {
    if (!telemetry || !online) {
      // Greyed out / neutral upright
      this.torsoGroup.setAttribute("transform", "rotate(0, 120, 160)");
      this.torsoSpine.setAttribute("stroke", "#5a6e85");
      this.torsoHead.setAttribute("stroke", "#5a6e85");
      this.thighGroup.innerHTML = '<path d="M 120 160 L 120 205" fill="none" stroke="#5a6e85" stroke-width="16" stroke-linecap="round" />';
      this.chairGroup.setAttribute("opacity", "0");
      this.pitchVal.textContent = "—";
      this.poseVal.textContent = online ? "No data" : "Offline";
      this.movingTag.style.display = "none";
      return;
    }

    const pitch = telemetry.imu_pitch_deg;
    const isStanding = Boolean(telemetry.is_standing);
    const moving = Boolean(telemetry.moving);
    const state = (telemetry.state || "UPRIGHT").toUpperCase();
    const bendOn = telemetry.bend_on_deg || 20.0;

    // 1. Moving tag
    this.movingTag.style.display = moving ? "inline-block" : "none";

    // 2. Pose (Standing vs Sitting)
    if (isStanding) {
      this.poseVal.textContent = "Standing";
      this.chairGroup.setAttribute("opacity", "0");
      // Vertical thigh
      this.thighGroup.innerHTML = '<path d="M 120 160 L 120 205" fill="none" stroke="#5a7394" stroke-width="16" stroke-linecap="round" />';
    } else {
      this.poseVal.textContent = "Sitting";
      this.chairGroup.setAttribute("opacity", "1");
      // Horizontal thigh from hip (120, 160) forward to knee (155, 160) with lower leg (155, 160) to (155, 258)
      this.thighGroup.innerHTML = `
        <path d="M 120 160 L 165 160 L 165 258 L 180 258" fill="none" stroke="#5a7394" stroke-width="15" stroke-linecap="round" stroke-linejoin="round" />
      `;
    }

    // 3. Threshold ray indicator
    const rad = (bendOn * Math.PI) / 180.0;
    const rayLength = 120;
    const rx = rayLength * Math.sin(rad);
    const ry = -rayLength * Math.cos(rad);
    this.thresholdRay.setAttribute("x2", rx.toFixed(1));
    this.thresholdRay.setAttribute("y2", ry.toFixed(1));
    this.thresholdLabel.setAttribute("x", (rx + 4).toFixed(1));
    this.thresholdLabel.setAttribute("y", (ry - 3).toFixed(1));
    this.thresholdLabel.textContent = `${bendOn.toFixed(0)}°`;

    // 4. Trunk pitch rotation
    if (pitch === null || pitch === undefined) {
      this.torsoGroup.setAttribute("transform", "rotate(0, 120, 160)");
      this.pitchVal.textContent = "—";
    } else {
      // Clamp pitch to ±50° for reasonable visual bounds
      const clampedPitch = Math.max(-50.0, Math.min(50.0, pitch));
      // In SVG: positive angle rotates clockwise (forward lean)
      this.torsoGroup.setAttribute("transform", `rotate(${clampedPitch.toFixed(1)}, 120, 160)`);
      this.pitchVal.textContent = `${pitch >= 0 ? "+" : ""}${pitch.toFixed(1)}°`;
    }

    // 5. State color feedback
    let color = "#2ecc71"; // green
    if (state === "ALERT") color = "#ff4d5e"; // red
    else if (state === "WARNING") color = "#f5c542"; // yellow
    else if (state === "UNCALIBRATED" || state === "CALIBRATING" || state === "FAULT") color = "#5a6e85";

    this.torsoSpine.setAttribute("stroke", color);
    this.torsoHead.setAttribute("stroke", color);
  }
}
