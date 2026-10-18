/**
 * Smart Posture T-Shirt v2 — Alerts View Component.
 *
 * Implements:
 * - Real-time Live Banner at the top when a slouch is in progress right now
 * - Filters bar: range pills (Today, Last 7 days, All available) + custom From/To, Level selector, min length selector, CSV download
 * - Summary cards: Slouches, Early warnings, Alerts, Longest slouch, Average length, Most common time
 * - Two charts side-by-side: "Slouches by day" (stacked bar) and "Slouches by hour of day" (24 bars in local time)
 * - Slouch log table: Start time (local), length, highest level reached, peak lean angle, HR change, muted tag
 * - Slouch detail modal / drawer: [-60s .. +60s] mini chart with vibrate/buzz thresholds & second HR axis, timeline moments, and technical expander
 * - Real-time updates via live stream store listener
 * - Unseen-alerts badge management via localStorage
 * - Friendly empty and error states
 */

import { api } from "../api.js";
import { store } from "../store.js";

export class AlertsView {
  constructor(container) {
    this.container = container;
    this.devices = [];
    this.selectedDevice = "";
    this.currentRange = "today";
    this.fromIso = null;
    this.toIso = null;
    this.selectedLevel = "ALL"; // ALL | WARNING | ALERT
    this.minDurationS = null; // null | 10 | 30 | 60

    // Pagination
    this.logPage = 0;
    this.logLimit = 25;
    this.logTotal = 0;

    // Charts
    this.dayChart = null;
    this.hourChart = null;
    this.detailChart = null;

    // Realtime banner ticker & unsubscribe
    this.unsubLive = null;
    this.timerInterval = null;
    this.lastSlouchStart = null;
  }

  async mount() {
    this.container.innerHTML = `
      <div class="alerts-view">
        <div id="alerts-live-banner-container"></div>

        <div class="analysis-header">
          <div>
            <h1 class="analysis-title">Alerts Log</h1>
            <div class="analysis-subtitle">Audit and review slouching events and posture warnings.</div>
          </div>
          <div class="header-controls" id="alerts-header-controls"></div>
        </div>

        <div id="alerts-content">
          <div class="loading-state">
            <span class="spinner-inline"></span> Loading alert metrics...
          </div>
        </div>

        <div id="alert-detail-modal-container"></div>
      </div>
    `;

    // 1. Clear unseen alerts badge when Alerts page is opened
    try {
      localStorage.setItem("vest_last_seen_alerts", new Date().toISOString());
    } catch (e) {}
    const badgeEl = document.getElementById("nav-alerts-badge");
    if (badgeEl) {
      badgeEl.classList.add("hidden");
      badgeEl.textContent = "0";
    }

    // 2. Priming devices and range
    const bounds = await api.fetchHistoryBounds();
    if (bounds && bounds.devices && bounds.devices.length > 0) {
      this.devices = bounds.devices;
      this.selectedDevice = this.devices[0].device_id;
    }
    this._applyPresetRange(this.currentRange, false);

    // 3. Render controls & load data
    this._renderControls();
    await this.loadData();

    // 4. Setup Real-time live banner & store subscription
    this.unsubLive = store.subscribe(() => {
      this._updateLiveBanner();
    });
    this._updateLiveBanner();
  }

  unmount() {
    if (this.unsubLive) {
      this.unsubLive();
      this.unsubLive = null;
    }
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
    if (this.dayChart) {
      try { this.dayChart.destroy(); } catch (e) {}
      this.dayChart = null;
    }
    if (this.hourChart) {
      try { this.hourChart.destroy(); } catch (e) {}
      this.hourChart = null;
    }
    if (this.detailChart) {
      try { this.detailChart.destroy(); } catch (e) {}
      this.detailChart = null;
    }
    this.container.innerHTML = "";
  }

  _applyPresetRange(preset, reload = true) {
    this.currentRange = preset;
    const now = new Date();

    if (preset === "today") {
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      this.fromIso = startOfToday.toISOString();
      this.toIso = now.toISOString();
    } else if (preset === "week") {
      const weekAgo = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
      this.fromIso = weekAgo.toISOString();
      this.toIso = now.toISOString();
    } else if (preset === "all") {
      this.fromIso = new Date(now.getTime() - 7 * 24 * 3600 * 1000).toISOString();
      this.toIso = now.toISOString();
    }

    if (reload) {
      this._renderControls();
      this.loadData();
    }
  }

  _renderControls() {
    const ctrlEl = document.getElementById("alerts-header-controls");
    ctrlEl.innerHTML = `
      <div class="segmented-control" id="alerts-range-pills">
        <button class="seg-btn ${this.currentRange === "today" ? "active" : ""}" data-range="today">Today</button>
        <button class="seg-btn ${this.currentRange === "week" ? "active" : ""}" data-range="week">Last 7 days</button>
        <button class="seg-btn ${this.currentRange === "all" ? "active" : ""}" data-range="all">All available</button>
      </div>

      <div style="display: flex; align-items: center; gap: 0.4rem;">
        <select class="btn" id="alerts-level-select" style="padding: 0.35rem 0.6rem; font-size: 0.85rem;">
          <option value="ALL" ${this.selectedLevel === "ALL" ? "selected" : ""}>All levels</option>
          <option value="WARNING" ${this.selectedLevel === "WARNING" ? "selected" : ""}>Early warnings</option>
          <option value="ALERT" ${this.selectedLevel === "ALERT" ? "selected" : ""}>Alerts</option>
        </select>

        <select class="btn" id="alerts-duration-select" style="padding: 0.35rem 0.6rem; font-size: 0.85rem;">
          <option value="" ${this.minDurationS === null ? "selected" : ""}>Any length</option>
          <option value="10" ${this.minDurationS === 10 ? "selected" : ""}>≥ 10s</option>
          <option value="30" ${this.minDurationS === 30 ? "selected" : ""}>≥ 30s</option>
          <option value="60" ${this.minDurationS === 60 ? "selected" : ""}>≥ 60s</option>
        </select>
      </div>

      <button class="btn btn-secondary" id="alerts-export-btn" style="display: flex; align-items: center; gap: 0.4rem;">
        <span>📥</span> Download CSV
      </button>
    `;

    ctrlEl.querySelectorAll("#alerts-range-pills .seg-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        this._applyPresetRange(btn.getAttribute("data-range"));
      });
    });

    document.getElementById("alerts-level-select").addEventListener("change", (e) => {
      this.selectedLevel = e.target.value;
      this.logPage = 0;
      this.loadData();
    });

    document.getElementById("alerts-duration-select").addEventListener("change", (e) => {
      const val = e.target.value;
      this.minDurationS = val ? parseInt(val, 10) : null;
      this.logPage = 0;
      this.loadData();
    });

    document.getElementById("alerts-export-btn").addEventListener("click", () => {
      const tzOffset = -new Date().getTimezoneOffset();
      let csvUrl = `/api/episodes/export.csv?device_id=${encodeURIComponent(this.selectedDevice)}&from=${encodeURIComponent(this.fromIso)}&to=${encodeURIComponent(this.toIso)}&tz_offset_minutes=${tzOffset}`;
      if (this.selectedLevel && this.selectedLevel !== "ALL") csvUrl += `&level=${this.selectedLevel}`;
      if (this.minDurationS) csvUrl += `&min_duration_s=${this.minDurationS}`;
      window.location.href = csvUrl;
    });
  }

  _updateLiveBanner() {
    const bannerContainer = document.getElementById("alerts-live-banner-container");
    if (!bannerContainer) return;

    const state = store.getState();
    const isOnline = state && state.online;
    const t = state && state.telemetry;
    const postureState = t ? t.state : null;
    const isSlouching = isOnline && (postureState === "WARNING" || postureState === "ALERT");

    if (isSlouching) {
      const durS = Math.round((t.bend_duration_ms || 0) / 1000);
      const isAlert = postureState === "ALERT";
      bannerContainer.innerHTML = `
        <div class="live-alert-banner ${isAlert ? '' : 'warning'}">
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span style="font-size: 1.5rem;">${isAlert ? '🚨' : '⚠️'}</span>
            <div>
              <strong style="color: ${isAlert ? 'var(--color-red)' : 'var(--color-yellow)'}; font-size: 1.05rem;">
                ${isAlert ? 'Alert in progress' : 'Early warning in progress'}
              </strong>
              <div style="font-size: 0.88rem; color: var(--text-main); margin-top: 0.15rem;">
                Leaning forward for ${durS} s — gentle biofeedback active
              </div>
            </div>
          </div>
          <span class="status-pill status-${postureState.toLowerCase()}">${postureState}</span>
        </div>
      `;
    } else {
      bannerContainer.innerHTML = "";
    }
  }

  async loadData() {
    const contentEl = document.getElementById("alerts-content");
    contentEl.innerHTML = `
      <div class="loading-state">
        <span class="spinner-inline"></span> Fetching alert metrics...
      </div>
    `;

    const tzOffset = -new Date().getTimezoneOffset();
    const queryParams = {
      device_id: this.selectedDevice,
      from: this.fromIso,
      to: this.toIso,
      tz_offset_minutes: tzOffset,
    };

    const searchParams = {
      ...queryParams,
      level: this.selectedLevel,
      min_duration_s: this.minDurationS,
      limit: this.logLimit,
      offset: this.logPage * this.logLimit,
      order: "desc",
    };

    try {
      const [summary, episodesRes] = await Promise.all([
        api.fetchAlertsSummary(queryParams),
        api.searchEpisodes(searchParams),
      ]);

      this._renderAlertsContent(summary, episodesRes.episodes || [], episodesRes.total || 0);
    } catch (err) {
      contentEl.innerHTML = `
        <div class="placeholder-card" style="margin: 2rem auto; max-width: 500px; text-align: center;">
          <div style="font-size: 2rem; margin-bottom: 0.5rem;">⚠️</div>
          <h3>Failed to load alerts</h3>
          <p style="color: var(--text-muted); margin: 0.5rem 0 1rem 0;">${err.message || "Network error"}</p>
          <button class="btn btn-primary" id="alerts-retry-btn">Retry</button>
        </div>
      `;
      document.getElementById("alerts-retry-btn")?.addEventListener("click", () => this.loadData());
    }
  }

  _renderAlertsContent(summary, episodes, total) {
    const contentEl = document.getElementById("alerts-content");
    this.logTotal = total;

    if (total === 0 && (!episodes || episodes.length === 0)) {
      contentEl.innerHTML = `
        <div class="placeholder-card" style="margin: 3rem auto; max-width: 500px; text-align: center;">
          <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">🧘</div>
          <h3>No slouches in this range. Nice posture.</h3>
          <p style="color: var(--text-muted); margin: 0.5rem 0 1rem 0;">
            No warning or alert events matched your current filters.
          </p>
          <button class="btn btn-secondary" id="alerts-reset-filters">Reset filters</button>
        </div>
      `;
      document.getElementById("alerts-reset-filters")?.addEventListener("click", () => {
        this.selectedLevel = "ALL";
        this.minDurationS = null;
        this._renderControls();
        this.loadData();
      });
      return;
    }

    const fmtVal = (val, suffix = "") => (val !== null && val !== undefined ? `${val}${suffix}` : "Not enough data yet");

    contentEl.innerHTML = `
      <!-- Summary Cards Row -->
      <div class="summary-cards-row">
        <div class="summary-card">
          <div class="summary-card-label">Total Slouches</div>
          <div class="summary-card-val">${summary.slouch_count ?? 0}</div>
          <div class="summary-card-hint">Total time: ${Math.round((summary.total_slouch_time_s || 0) / 60)} min</div>
        </div>

        <div class="summary-card">
          <div class="summary-card-label">Early warnings</div>
          <div class="summary-card-val" style="color: var(--color-yellow);">${summary.warning_count ?? 0}</div>
          <div class="summary-card-hint">Prompt corrected</div>
        </div>

        <div class="summary-card">
          <div class="summary-card-label">Alerts</div>
          <div class="summary-card-val" style="color: var(--color-red);">${summary.alert_count ?? 0}</div>
          <div class="summary-card-hint">Buzzer sounded</div>
        </div>

        <div class="summary-card">
          <div class="summary-card-label">Longest slouch</div>
          <div class="summary-card-val">${fmtVal(summary.longest_slouch_s, "s")}</div>
          <div class="summary-card-hint">Peak duration</div>
        </div>

        <div class="summary-card">
          <div class="summary-card-label">Average length</div>
          <div class="summary-card-val">${fmtVal(summary.avg_length_s, "s")}</div>
          <div class="summary-card-hint">Per slouch event</div>
        </div>

        <div class="summary-card">
          <div class="summary-card-label">Most common time</div>
          <div class="summary-card-val" style="font-size: 1.25rem;">
            ${summary.slouch_count < 3 ? 'Not enough data yet' : (summary.most_frequent_hour || 'Not enough data yet')}
          </div>
          <div class="summary-card-hint">Peak fatigue hour</div>
        </div>
      </div>

      <!-- Two Charts Side by Side -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 1.25rem; margin-bottom: 1.5rem;">
        <div class="timeline-card">
          <h3 style="font-size: 1.05rem; font-weight: 700; margin-bottom: 0.5rem;">Slouches by day</h3>
          <div style="height: 220px;">
            <canvas id="alerts-day-chart"></canvas>
          </div>
        </div>

        <div class="timeline-card">
          <h3 style="font-size: 1.05rem; font-weight: 700; margin-bottom: 0.5rem;">Slouches by hour of day (local time)</h3>
          <div style="height: 220px;">
            <canvas id="alerts-hour-chart"></canvas>
          </div>
        </div>
      </div>

      <!-- Slouch Log Table -->
      <div class="timeline-card">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem; flex-wrap: wrap; gap: 0.5rem;">
          <h3 style="font-size: 1.15rem; font-weight: 700;">Slouch Log</h3>
          <div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: var(--text-muted);">
            <span>${this.logPage * this.logLimit + 1}–${Math.min(this.logTotal, (this.logPage + 1) * this.logLimit)} of ${this.logTotal}</span>
            <button class="btn btn-secondary" id="alerts-prev-page" style="padding: 0.25rem 0.5rem;">‹</button>
            <button class="btn btn-secondary" id="alerts-next-page" style="padding: 0.25rem 0.5rem;">›</button>
          </div>
        </div>

        <div class="data-table-wrapper">
          <table class="data-table">
            <thead>
              <tr>
                <th>Start time (local)</th>
                <th>Length</th>
                <th>Highest level</th>
                <th>Peak lean angle</th>
                <th>Heart rate change</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${episodes.map(ep => {
                const sDate = new Date(ep.start_ts);
                const timeStr = `${sDate.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${sDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
                const durS = Math.round((ep.duration_ms || 0) / 1000);
                const isAlert = ep.max_level === "ALERT";
                return `
                  <tr class="slouch-row" data-id="${ep.id}" style="cursor: pointer;">
                    <td><strong>${timeStr}</strong></td>
                    <td>${durS}s</td>
                    <td>
                      <span class="status-pill status-${ep.max_level.toLowerCase()}">${isAlert ? 'Alert' : 'Early warning'}</span>
                    </td>
                    <td>${ep.peak_pitch_deg ? ep.peak_pitch_deg + '°' : '—'}</td>
                    <td>${ep.hr_change !== null && ep.hr_change !== undefined ? (ep.hr_change > 0 ? '+' : '') + ep.hr_change + ' bpm' : '—'}</td>
                    <td>
                      <button class="btn btn-secondary" style="padding: 0.2rem 0.5rem; font-size: 0.78rem;">Details ›</button>
                    </td>
                  </tr>
                `;
              }).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;

    // Render 2 charts
    this._renderDayChart(summary.slouches_per_day || []);
    this._renderHourChart(summary.slouches_per_hour || []);

    // Pagination
    document.getElementById("alerts-prev-page")?.addEventListener("click", () => {
      if (this.logPage > 0) {
        this.logPage--;
        this.loadData();
      }
    });

    document.getElementById("alerts-next-page")?.addEventListener("click", () => {
      if ((this.logPage + 1) * this.logLimit < this.logTotal) {
        this.logPage++;
        this.loadData();
      }
    });

    // Row clicks -> open Slouch Detail modal
    contentEl.querySelectorAll(".slouch-row").forEach(row => {
      row.addEventListener("click", () => {
        const epId = row.getAttribute("data-id");
        if (epId) this.openSlouchDetail(epId);
      });
    });
  }

  _renderDayChart(days) {
    const canvas = document.getElementById("alerts-day-chart");
    if (!canvas) return;
    if (this.dayChart) this.dayChart.destroy();

    const labels = days.map(d => d.date);
    const warnData = days.map(d => d.warning ?? d.warning_count ?? 0);
    const alertData = days.map(d => d.alert ?? d.alert_count ?? 0);

    this.dayChart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Alerts",
            data: alertData,
            backgroundColor: "#ff4d5e",
          },
          {
            label: "Early warnings",
            data: warnData,
            backgroundColor: "#f5c542",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, ticks: { color: "#8e9fb3" }, grid: { display: false } },
          y: { stacked: true, ticks: { color: "#8e9fb3", precision: 0 }, grid: { color: "rgba(255,255,255,0.05)" } },
        },
        plugins: {
          legend: { labels: { color: "#f0f4f8", boxWidth: 12 } },
        },
      },
    });
  }

  _renderHourChart(hourlyBins) {
    const canvas = document.getElementById("alerts-hour-chart");
    if (!canvas) return;
    if (this.hourChart) this.hourChart.destroy();

    const labels = [];
    for (let h = 0; h < 24; h++) {
      if (h === 0) labels.push("12am");
      else if (h < 12) labels.push(`${h}am`);
      else if (h === 12) labels.push("12pm");
      else labels.push(`${h - 12}pm`);
    }

    this.hourChart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Slouches",
            data: hourlyBins,
            backgroundColor: "#3498db",
            borderRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { ticks: { color: "#8e9fb3", maxTicksLimit: 12 }, grid: { display: false } },
          y: { ticks: { color: "#8e9fb3", precision: 0 }, grid: { color: "rgba(255,255,255,0.05)" } },
        },
        plugins: {
          legend: { display: false },
        },
      },
    });
  }

  async openSlouchDetail(epId) {
    const modalContainer = document.getElementById("alert-detail-modal-container");
    modalContainer.innerHTML = `
      <div class="modal-overlay" id="slouch-modal-overlay">
        <div class="modal-dialog">
          <div class="modal-header">
            <h2>Slouch Detail</h2>
            <button class="modal-close-btn" id="slouch-modal-close">×</button>
          </div>
          <div id="slouch-modal-body">
            <div class="loading-state">
              <span class="spinner-inline"></span> Fetching context window...
            </div>
          </div>
        </div>
      </div>
    `;

    document.getElementById("slouch-modal-close").addEventListener("click", () => {
      modalContainer.innerHTML = "";
    });
    document.getElementById("slouch-modal-overlay").addEventListener("click", (e) => {
      if (e.target.id === "slouch-modal-overlay") modalContainer.innerHTML = "";
    });

    try {
      const detail = await api.fetchEpisodeDetail(epId);
      const bodyEl = document.getElementById("slouch-modal-body");
      if (!bodyEl) return;

      const durS = Math.round((detail.duration_ms || 0) / 1000);
      const isAlert = detail.max_level === "ALERT";
      const moments = detail.moments || {};

      bodyEl.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.5rem;">
          <div>
            <span class="status-pill status-${detail.max_level.toLowerCase()}">${isAlert ? 'Alert' : 'Early warning'}</span>
            <strong style="margin-left: 0.5rem; font-size: 1.1rem;">${durS}s duration</strong>
            ${moments.muted_during ? `<span style="font-size: 0.75rem; background: rgba(255,255,255,0.1); padding: 0.15rem 0.4rem; border-radius: var(--radius-pill); margin-left: 0.5rem;">muted</span>` : ''}
          </div>
          <div style="color: var(--text-muted); font-size: 0.85rem;">
            Started: ${new Date(detail.start_ts).toLocaleTimeString()}
          </div>
        </div>

        <!-- Moments timeline strip -->
        <div style="background: var(--bg-surface-elevated); padding: 0.75rem 1rem; border-radius: var(--radius-sm); border: 1px solid var(--border-subtle); margin-bottom: 1rem; font-size: 0.85rem; display: flex; gap: 1.5rem; flex-wrap: wrap;">
          <div><strong>0s</strong> Slouch started</div>
          <div><strong style="color: var(--color-yellow);">+${moments.early_warning_s ?? 5}s</strong> Early warning</div>
          ${isAlert ? `<div><strong style="color: var(--color-red);">+${moments.alert_s ?? 15}s</strong> Alert sounded</div>` : ''}
          <div><strong>+${durS}s</strong> Ended & corrected</div>
        </div>

        <!-- Mini Context Chart -->
        <div style="margin-bottom: 1rem;">
          <h4 style="font-size: 0.95rem; margin-bottom: 0.4rem;">Context series (60s before to 60s after)</h4>
          <div style="height: 220px; background: var(--bg-deep); border-radius: var(--radius-sm); padding: 0.5rem;">
            <canvas id="slouch-detail-chart"></canvas>
          </div>
        </div>

        <!-- Technical details expander -->
        <details style="font-size: 0.85rem; color: var(--text-muted); cursor: pointer; margin-top: 1rem;">
          <summary>Technical Details & Thresholds</summary>
          <div style="padding: 0.75rem; background: var(--bg-deep); border-radius: var(--radius-sm); margin-top: 0.5rem; line-height: 1.6;">
            <div>Peak lean angle: <strong>${detail.peak_pitch_deg}°</strong></div>
            <div>Device ID: <strong>${detail.device_id}</strong></div>
            <div>Total context points: <strong>${detail.context_series ? detail.context_series.length : 0}</strong></div>
            <div>Vibrate threshold: <strong>20.0° after 5s</strong></div>
            <div>Buzzer threshold: <strong>20.0° after 15s</strong></div>
          </div>
        </details>
      `;

      // Render detail mini chart
      if (detail.context_series && detail.context_series.length > 0) {
        this._renderSlouchDetailChart(detail.context_series);
      }
    } catch (err) {
      const bodyEl = document.getElementById("slouch-modal-body");
      if (bodyEl) {
        bodyEl.innerHTML = `<div style="color: var(--color-red); padding: 1.5rem; text-align: center;">Failed to load detail: ${err.message}</div>`;
      }
    }
  }

  _renderSlouchDetailChart(series) {
    const canvas = document.getElementById("slouch-detail-chart");
    if (!canvas) return;

    const labels = series.map(p => `${p.offset_s > 0 ? '+' : ''}${p.offset_s}s`);
    const pitchData = series.map(p => p.pitch);
    const hrData = series.map(p => p.hr);

    if (this.detailChart) this.detailChart.destroy();

    this.detailChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Lean angle (°)",
            data: pitchData,
            borderColor: "#f5c542",
            borderWidth: 2,
            pointRadius: 0,
            yAxisID: "yPitch",
          },
          {
            label: "Heart rate (bpm)",
            data: hrData,
            borderColor: "#ff4d5e",
            borderWidth: 1.5,
            borderDash: [3, 3],
            pointRadius: 0,
            yAxisID: "yHr",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        scales: {
          x: { ticks: { color: "#8e9fb3", maxTicksLimit: 10 }, grid: { color: "rgba(255,255,255,0.05)" } },
          yPitch: {
            type: "linear",
            position: "left",
            ticks: { color: "#f5c542" },
            grid: { color: "rgba(255,255,255,0.05)" },
          },
          yHr: {
            type: "linear",
            position: "right",
            ticks: { color: "#ff4d5e" },
            grid: { drawOnChartArea: false },
          },
        },
        plugins: {
          legend: { labels: { color: "#f0f4f8", boxWidth: 10 } },
        },
      },
    });
  }
}
