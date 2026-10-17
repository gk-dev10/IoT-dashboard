/**
 * Smart Posture T-Shirt v2 — Live Plotting & Telemetry Charts Component.
 * Powered by vendored Chart.js (offline UMD).
 */

export class ChartsComponent {
  constructor(pitchContainer, hrContainer, envContainer) {
    this.pitchContainer = pitchContainer;
    this.hrContainer = hrContainer;
    this.envContainer = envContainer;

    this.pitchChart = null;
    this.hrChart = null;
    this.envChart = null;

    this.renderInitial();
    this.initCharts();
  }

  renderInitial() {
    // 1. Pitch chart card
    this.pitchContainer.innerHTML = `
      <div class="chart-card pitch-chart-card">
        <div class="chart-header">
          <div>
            <span class="card-title">Live Trunk Pitch Trend (Last 2 Min)</span>
            <div class="chart-subtext">Positive = Leaning Forward · Negative = Leaning Backward</div>
          </div>
          <div class="threshold-pill-group">
            <span class="pill pill-on">Threshold ON: <strong id="chart-bend-on-lbl">20°</strong></span>
            <span class="pill pill-off">Recovery OFF: <strong id="chart-bend-off-lbl">15°</strong></span>
          </div>
        </div>
        <div class="canvas-wrapper">
          <canvas id="pitch-canvas"></canvas>
        </div>
      </div>
    `;

    // 2. Heart rate card
    this.hrContainer.innerHTML = `
      <div class="chart-card mini-metric-card">
        <div class="metric-card-header">
          <span class="card-title">Heart Rate</span>
          <span id="hr-finger-badge" class="badge badge-neutral">No contact</span>
        </div>
        <div class="metric-number-row">
          <span id="hr-val-display" class="metric-big-num">—</span>
          <span class="metric-unit">BPM</span>
        </div>
        <div class="sparkline-wrapper">
          <canvas id="hr-sparkline"></canvas>
        </div>
      </div>
    `;

    // 3. Environmental Air Temp & Humidity card
    this.envContainer.innerHTML = `
      <div class="chart-card mini-metric-card">
        <div class="metric-card-header">
          <span class="card-title">Micro-Climate Air Temp & Humidity</span>
          <span class="badge badge-info">Near-Body Air</span>
        </div>
        <div class="env-split-row">
          <div class="env-col">
            <span class="env-label">Air Temp</span>
            <div class="env-num-wrap">
              <span id="air-temp-display" class="env-big-num">—</span>
              <span class="metric-unit">°C</span>
            </div>
          </div>
          <div class="env-col">
            <span class="env-label">Humidity</span>
            <div class="env-num-wrap">
              <span id="humidity-display" class="env-big-num">—</span>
              <span class="metric-unit">%</span>
            </div>
          </div>
        </div>
        <div class="sparkline-wrapper">
          <canvas id="env-sparkline"></canvas>
        </div>
      </div>
    `;

    this.bendOnLbl = document.getElementById("chart-bend-on-lbl");
    this.bendOffLbl = document.getElementById("chart-bend-off-lbl");
    this.hrValDisplay = document.getElementById("hr-val-display");
    this.hrFingerBadge = document.getElementById("hr-finger-badge");
    this.airTempDisplay = document.getElementById("air-temp-display");
    this.humidityDisplay = document.getElementById("humidity-display");
  }

  initCharts() {
    if (typeof window.Chart === "undefined") {
      console.error("Chart.js is not loaded.");
      return;
    }

    const gridColor = "rgba(255, 255, 255, 0.06)";
    const textColor = "#7e90a6";

    // 1. Pitch chart
    const pitchCtx = document.getElementById("pitch-canvas").getContext("2d");
    this.pitchChart = new window.Chart(pitchCtx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Trunk Pitch (°)",
            data: [],
            borderColor: "#2ecc71",
            backgroundColor: "rgba(46, 204, 113, 0.08)",
            borderWidth: 2.5,
            fill: true,
            tension: 0.25,
            pointRadius: 0,
            pointHitRadius: 6,
          },
          {
            label: "Bend-On Threshold",
            data: [],
            borderColor: "#f5c542",
            borderWidth: 1.5,
            borderDash: [5, 4],
            fill: false,
            pointRadius: 0,
          },
          {
            label: "Bend-Off Recovery",
            data: [],
            borderColor: "rgba(46, 204, 113, 0.5)",
            borderWidth: 1.5,
            borderDash: [3, 3],
            fill: false,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: {
          x: {
            display: false,
          },
          y: {
            grid: { color: gridColor },
            ticks: { color: textColor, font: { family: "system-ui", size: 11 } },
            suggestedMin: -10,
            suggestedMax: 40,
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            mode: "index",
            intersect: false,
            callbacks: {
              label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}°`,
            },
          },
        },
      },
    });

    // 2. HR Sparkline
    const hrCtx = document.getElementById("hr-sparkline").getContext("2d");
    this.hrChart = new window.Chart(hrCtx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            data: [],
            borderColor: "#ff4d5e",
            backgroundColor: "rgba(255, 77, 94, 0.12)",
            borderWidth: 2,
            fill: true,
            tension: 0.3,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: { x: { display: false }, y: { display: false } },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
      },
    });

    // 3. Env Sparkline (dual dataset: temp & humidity)
    const envCtx = document.getElementById("env-sparkline").getContext("2d");
    this.envChart = new window.Chart(envCtx, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Air Temp",
            data: [],
            borderColor: "#3498db",
            borderWidth: 1.8,
            fill: false,
            tension: 0.2,
            pointRadius: 0,
          },
          {
            label: "Humidity",
            data: [],
            borderColor: "#9b59b6",
            borderWidth: 1.8,
            fill: false,
            tension: 0.2,
            pointRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        scales: { x: { display: false }, y: { display: false } },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
      },
    });
  }

  update(history, latestTelemetry, online) {
    if (!latestTelemetry || !online) {
      this.hrValDisplay.textContent = "—";
      this.hrFingerBadge.textContent = "Offline";
      this.hrFingerBadge.className = "badge badge-neutral";
      this.airTempDisplay.textContent = "—";
      this.humidityDisplay.textContent = "—";
      return;
    }

    const bendOn = latestTelemetry.bend_on_deg || 20.0;
    const bendOff = latestTelemetry.bend_off_deg || 15.0;
    this.bendOnLbl.textContent = `${bendOn.toFixed(0)}°`;
    this.bendOffLbl.textContent = `${bendOff.toFixed(0)}°`;

    // 1. Update HR readout
    if (latestTelemetry.finger_present && latestTelemetry.heart_rate_bpm) {
      this.hrValDisplay.textContent = latestTelemetry.heart_rate_bpm;
      this.hrFingerBadge.textContent = "Pulse locked";
      this.hrFingerBadge.className = "badge badge-ok";
    } else {
      this.hrValDisplay.textContent = "—";
      this.hrFingerBadge.textContent = "No signal";
      this.hrFingerBadge.className = "badge badge-neutral";
    }

    // 2. Update Air temp / Humidity readout
    this.airTempDisplay.textContent =
      latestTelemetry.temperature_c !== null ? latestTelemetry.temperature_c.toFixed(1) : "—";
    this.humidityDisplay.textContent =
      latestTelemetry.humidity_pct !== null ? latestTelemetry.humidity_pct.toFixed(0) : "—";

    // 3. Update Chart datasets from rolling history
    if (!this.pitchChart || !Array.isArray(history) || history.length === 0) {
      return;
    }

    const labels = [];
    const pitchData = [];
    const onLine = [];
    const offLine = [];
    const hrData = [];
    const tempData = [];
    const humData = [];

    // History data points
    for (const pt of history) {
      labels.push(pt.ts ? pt.ts.substring(11, 19) : "");
      pitchData.push(pt.imu_pitch_deg !== null ? pt.imu_pitch_deg : null);
      onLine.push(bendOn);
      offLine.push(bendOff);

      hrData.push(pt.heart_rate_bpm !== null ? pt.heart_rate_bpm : null);
      tempData.push(pt.temperature_c !== null ? pt.temperature_c : null);
      humData.push(pt.humidity_pct !== null ? pt.humidity_pct : null);
    }

    // Apply color gradient / change based on current state
    const state = (latestTelemetry.state || "UPRIGHT").toUpperCase();
    if (state === "ALERT") {
      this.pitchChart.data.datasets[0].borderColor = "#ff4d5e";
      this.pitchChart.data.datasets[0].backgroundColor = "rgba(255, 77, 94, 0.1)";
    } else if (state === "WARNING") {
      this.pitchChart.data.datasets[0].borderColor = "#f5c542";
      this.pitchChart.data.datasets[0].backgroundColor = "rgba(245, 197, 66, 0.1)";
    } else {
      this.pitchChart.data.datasets[0].borderColor = "#2ecc71";
      this.pitchChart.data.datasets[0].backgroundColor = "rgba(46, 204, 113, 0.08)";
    }

    this.pitchChart.data.labels = labels;
    this.pitchChart.data.datasets[0].data = pitchData;
    this.pitchChart.data.datasets[1].data = onLine;
    this.pitchChart.data.datasets[2].data = offLine;
    this.pitchChart.update();

    if (this.hrChart) {
      this.hrChart.data.labels = labels;
      this.hrChart.data.datasets[0].data = hrData;
      this.hrChart.update();
    }

    if (this.envChart) {
      this.envChart.data.labels = labels;
      this.envChart.data.datasets[0].data = tempData;
      this.envChart.data.datasets[1].data = humData;
      this.envChart.update();
    }
  }
}
