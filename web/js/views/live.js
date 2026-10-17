/**
 * Smart Posture T-Shirt v2 — Live View Controller.
 * Manages view lifecycle, component instantiation, and reactive DOM binding.
 */

import { api } from "../api.js";
import { store } from "../store.js";
import { BodyFigureComponent } from "../components/body_figure.js";
import { BendTimerComponent } from "../components/bend_timer.js";
import { WearableMirrorComponent } from "../components/wearable_mirror.js";
import { ChartsComponent } from "../components/charts.js";
import { SensorHealthComponent } from "../components/sensor_health.js";
import { ControlsComponent } from "../components/controls.js";
import { EpisodesTableComponent } from "../components/episodes_table.js";

export class LiveView {
  constructor(container) {
    this.container = container;
    this.unsubscribe = null;
    this.prevEpisodeCount = 0;
  }

  mount() {
    this.container.innerHTML = `
      <!-- Empty DB / Waiting Banner -->
      <div id="waiting-screen" class="waiting-banner" style="display: none;">
        <div class="waiting-icon">📡</div>
        <h2>Waiting for Posture T-Shirt Telemetry…</h2>
        <p>Ensure the ESP32 is powered on and connected to Wi-Fi. It will start sending sensor data to <code>/api/data</code>.</p>
      </div>

      <!-- Top Status Banner -->
      <header class="live-header">
        <div class="brand-group">
          <div class="logo-mark">🧍</div>
          <div>
            <h1 class="product-title">Smart Posture T-Shirt</h1>
            <div class="brand-caption">Live Wearable Bio-Feedback Monitor</div>
          </div>
        </div>

        <div class="system-status-pills">
          <!-- Connection Pill -->
          <div id="pill-connection" class="status-pill pill-offline">
            <span class="pulsing-dot"></span>
            <span id="lbl-connection-text">CONNECTING…</span>
          </div>

          <!-- Muted Badge -->
          <span id="badge-muted" class="badge badge-warning" style="display: none;">MUTED</span>

          <!-- Not Calibrated Badge -->
          <span id="badge-unarmed" class="badge badge-neutral" style="display: none;">NOT CALIBRATED</span>

          <!-- Wi-Fi RSSI -->
          <div class="meta-pill" title="Wi-Fi Signal Strength">
            <span class="meta-icon">📶</span>
            <span id="lbl-wifi-rssi">— dBm</span>
          </div>

          <!-- Uptime -->
          <div class="meta-pill" title="Wearable Uptime">
            <span class="meta-icon">⏱️</span>
            <span id="lbl-uptime">—</span>
          </div>
        </div>
      </header>

      <!-- Main Live Grid Content -->
      <div id="live-content-wrapper" class="live-grid-container">
        <!-- 1. Hero Row -->
        <section class="grid-row hero-row">
          <!-- Posture State Hero Card -->
          <div id="card-state-hero" class="state-hero-card state-card-upright">
            <div class="state-icon-wrap">
              <span id="hero-state-icon" class="hero-icon">✓</span>
            </div>
            <div class="state-text-wrap">
              <span class="state-overline">Current Posture</span>
              <h2 id="hero-state-title" class="state-big-title">Good Posture</h2>
              <p id="hero-state-sub" class="state-description">Spine aligned within healthy ergonomics.</p>
            </div>
          </div>

          <!-- Bend Duration Timer Ring -->
          <div id="container-bend-timer" class="hero-item-wrap"></div>

          <!-- Side-View SVG Silhouette -->
          <div id="container-body-figure" class="hero-item-wrap"></div>
        </section>

        <!-- 2. Wearable Hardware Mirror Panel -->
        <section class="grid-row">
          <div id="container-wearable-mirror" class="full-width-wrap"></div>
        </section>

        <!-- 3. Charts & Sparklines Row -->
        <section class="grid-row charts-row">
          <div id="container-pitch-chart" class="chart-col-main"></div>
          <div class="chart-col-side">
            <div id="container-hr-card"></div>
            <div id="container-env-card"></div>
          </div>
        </section>

        <!-- 4. Sensor Diagnostics Health Strip -->
        <section class="grid-row">
          <div id="container-sensor-health" class="full-width-wrap"></div>
        </section>

        <!-- 5. Interactive Control & Calibration Panel -->
        <section class="grid-row">
          <div id="container-controls" class="full-width-wrap"></div>
        </section>

        <!-- 6. Recent Stoop Episodes Table -->
        <section class="grid-row">
          <div id="container-episodes" class="full-width-wrap"></div>
        </section>
      </div>
    `;

    // Cache elements
    this.waitingScreen = document.getElementById("waiting-screen");
    this.contentWrapper = document.getElementById("live-content-wrapper");
    this.pillConnection = document.getElementById("pill-connection");
    this.lblConnText = document.getElementById("lbl-connection-text");
    this.badgeMuted = document.getElementById("badge-muted");
    this.badgeUnarmed = document.getElementById("badge-unarmed");
    this.lblWifiRssi = document.getElementById("lbl-wifi-rssi");
    this.lblUptime = document.getElementById("lbl-uptime");

    this.cardStateHero = document.getElementById("card-state-hero");
    this.heroIcon = document.getElementById("hero-state-icon");
    this.heroTitle = document.getElementById("hero-state-title");
    this.heroSub = document.getElementById("hero-state-sub");

    // Instantiate sub-components
    this.bendTimerComp = new BendTimerComponent(document.getElementById("container-bend-timer"));
    this.bodyFigureComp = new BodyFigureComponent(document.getElementById("container-body-figure"));
    this.wearableMirrorComp = new WearableMirrorComponent(
      document.getElementById("container-wearable-mirror")
    );
    this.chartsComp = new ChartsComponent(
      document.getElementById("container-pitch-chart"),
      document.getElementById("container-hr-card"),
      document.getElementById("container-env-card")
    );
    this.sensorHealthComp = new SensorHealthComponent(
      document.getElementById("container-sensor-health")
    );
    this.controlsComp = new ControlsComponent(document.getElementById("container-controls"));
    this.episodesComp = new EpisodesTableComponent(document.getElementById("container-episodes"));

    // Subscribe to store updates
    this.unsubscribe = store.subscribe((state) => this.render(state));

    // Fetch initial episodes
    this.refreshEpisodes();
  }

  async refreshEpisodes() {
    const episodes = await api.fetchEpisodes(5);
    store.setEpisodes(episodes);
  }

  render(state) {
    const { online, seconds_since_last, telemetry, commands, history, episodes } = state;

    // 1. Check for empty database (waiting for first telemetry)
    if (!telemetry) {
      this.waitingScreen.style.display = "block";
      this.contentWrapper.style.opacity = "0.4";
      this.contentWrapper.style.pointerEvents = "none";
      this.pillConnection.className = "status-pill pill-offline";
      this.lblConnText.textContent = "WAITING FOR VEST…";
      return;
    } else {
      this.waitingScreen.style.display = "none";
      this.contentWrapper.style.opacity = "1";
      this.contentWrapper.style.pointerEvents = "auto";
    }

    // 2. Connection Pill
    if (online) {
      this.pillConnection.className = "status-pill pill-online";
      this.lblConnText.textContent = "LIVE";
    } else {
      this.pillConnection.className = "status-pill pill-offline";
      const secStr = seconds_since_last !== null ? `${Math.round(seconds_since_last)} s ago` : "offline";
      this.lblConnText.textContent = `OFFLINE — last seen ${secStr}`;
    }

    // 3. Badges
    this.badgeMuted.style.display = telemetry.muted ? "inline-block" : "none";
    this.badgeUnarmed.style.display = !telemetry.armed ? "inline-block" : "none";

    // 4. Meta readouts
    this.lblWifiRssi.textContent =
      telemetry.wifi_rssi !== null ? `${telemetry.wifi_rssi} dBm` : "— dBm";

    if (telemetry.uptime_s !== null) {
      const upSec = telemetry.uptime_s;
      const m = Math.floor(upSec / 60);
      const s = upSec % 60;
      this.lblUptime.textContent = `${m}m ${s}s`;
    } else {
      this.lblUptime.textContent = "—";
    }

    // 5. Posture State Hero Card
    this.updateStateHero(telemetry, online);

    // 6. Sub-components updates
    this.bendTimerComp.update(telemetry, online);
    this.bodyFigureComp.update(telemetry, online);
    this.wearableMirrorComp.update(telemetry, online);
    this.chartsComp.update(history, telemetry, online);
    this.sensorHealthComp.update(telemetry, online);
    this.controlsComp.update(telemetry, online, commands);
    this.episodesComp.update(episodes);

    // If bend episode closed or state shifted to UPRIGHT from bend, trigger refresh
    if (episodes && episodes.length !== this.prevEpisodeCount) {
      this.prevEpisodeCount = episodes.length;
    }
  }

  updateStateHero(telemetry, online) {
    if (!online) {
      this.cardStateHero.className = "state-hero-card state-card-offline";
      this.heroIcon.textContent = "✕";
      this.heroTitle.textContent = "Wearable Offline";
      this.heroSub.textContent = "No data received within the last 5 seconds.";
      return;
    }

    const state = (telemetry.state || "UPRIGHT").toUpperCase();

    if (state === "ALERT") {
      this.cardStateHero.className = "state-hero-card state-card-alert pulse-strong";
      this.heroIcon.textContent = "⚠️";
      this.heroTitle.textContent = "ALERT — Straighten Up";
      this.heroSub.textContent = `Stoop persisted for > ${telemetry.buzzer_delay_s || 15}s. Buzzer & motor active.`;
    } else if (state === "WARNING") {
      this.cardStateHero.className = "state-hero-card state-card-warning pulse-subtle";
      this.heroIcon.textContent = "⚡";
      this.heroTitle.textContent = "Early Warning";
      this.heroSub.textContent = `Forward bend detected for > ${telemetry.vibrate_delay_s || 5}s. Vibration active.`;
    } else if (state === "CALIBRATING") {
      this.cardStateHero.className = "state-hero-card state-card-calibrating";
      this.heroIcon.textContent = "⏳";
      this.heroTitle.textContent = "Calibrating…";
      this.heroSub.textContent = "Please stand upright and keep completely still.";
    } else if (state === "UNCALIBRATED") {
      this.cardStateHero.className = "state-hero-card state-card-neutral";
      this.heroIcon.textContent = "ℹ️";
      this.heroTitle.textContent = "Needs Calibration";
      this.heroSub.textContent = "Vest must be calibrated in an upright stance before monitoring.";
    } else if (state === "FAULT") {
      this.cardStateHero.className = "state-hero-card state-card-alert";
      this.heroIcon.textContent = "⚙️";
      this.heroTitle.textContent = "Sensor Fault";
      this.heroSub.textContent = "Hardware self-test failed. Inspect physical sensor wiring.";
    } else {
      // UPRIGHT
      this.cardStateHero.className = "state-hero-card state-card-upright";
      this.heroIcon.textContent = "✓";
      this.heroTitle.textContent = "Good Posture";
      this.heroSub.textContent = "Spine aligned within healthy ergonomics.";
    }
  }

  unmount() {
    if (this.unsubscribe) {
      this.unsubscribe();
      this.unsubscribe = null;
    }
  }
}
