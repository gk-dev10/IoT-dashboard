/**
 * Smart Posture T-Shirt v2 — History View Component.
 *
 * Implements:
 * - Range pills (Today, Yesterday, Last 7 days, All available) + custom From/To datetime-local picker
 * - Persistent URL hash parameters (#/history?from=...&to=...&device_id=...)
 * - Simulated data banner
 * - Summary cards row (Monitored time, Good posture %, Slouches, Longest slouch, Time sitting, Avg HR)
 * - Hero Posture Timeline strip: RLE colored segments with hover tooltip, drag-zoom, reset zoom, and vitals toggle
 * - Day by day breakdown (clicking a day sets range to that day)
 * - Sessions list (continuous stretches of data, clicking a session sets range to that session)
 * - Raw readings table (collapsible, paginated 50 per page, order toggle, extra columns toggle)
 * - Empty, Loading, and Error states
 */

import { api } from "../api.js";

export class HistoryView {
  constructor(container) {
    this.container = container;
    this.devices = [];
    this.selectedDevice = "";
    this.bounds = null;
    this.currentRange = "today"; // today | yesterday | week | all | custom
    this.fromIso = null;
    this.toIso = null;
    this.zoomFromIso = null;
    this.zoomToIso = null;
    this.showVitals = false;
    this.vitalsChart = null;

    // Readings state
    this.showReadings = false;
    this.readingsPage = 0;
    this.readingsLimit = 50;
    this.readingsOrder = "desc";
    this.readingsMoreCols = false;
    this.readingsTotal = 0;

    // Drag-zoom state on canvas
    this.isDragging = false;
    this.dragStartX = 0;
    this.dragCurrentX = 0;
  }

  async mount() {
    this.container.innerHTML = `
      <div class="history-view">
        <div id="hist-sim-banner"></div>
        <div class="analysis-header">
          <div>
            <h1 class="analysis-title">History</h1>
            <div class="analysis-subtitle" id="hist-subtitle">Loading posture and vitals history...</div>
          </div>
          <div class="header-controls" id="hist-header-controls"></div>
        </div>

        <div id="hist-content">
          <div class="loading-state">
            <span class="spinner-inline"></span> Loading historical telemetry...
          </div>
        </div>
      </div>
    `;

    // 1. Fetch bounds & device list
    this.bounds = await api.fetchHistoryBounds();
    if (this.bounds && this.bounds.devices && this.bounds.devices.length > 0) {
      this.devices = this.bounds.devices;
      this.selectedDevice = this.devices[0].device_id;
    }

    // 2. Parse URL hash query params if any
    this._readHashParams();

    // 3. Render header controls & load data
    this._renderHeaderControls();
    await this.loadData();
  }

  unmount() {
    window.onmousemove = null;
    window.onmouseup = null;
    if (this.vitalsChart) {
      try { this.vitalsChart.destroy(); } catch (e) {}
      this.vitalsChart = null;
    }
    this.container.innerHTML = "";
  }

  _readHashParams() {
    const hash = window.location.hash || "";
    const qIdx = hash.indexOf("?");
    if (qIdx !== -1) {
      const qs = hash.substring(qIdx + 1);
      const params = new URLSearchParams(qs);
      if (params.get("from") && params.get("to")) {
        this.fromIso = params.get("from");
        this.toIso = params.get("to");
        this.currentRange = "custom";
      }
      if (params.get("device_id")) {
        this.selectedDevice = params.get("device_id");
      }
    }

    if (!this.fromIso || !this.toIso) {
      this._applyPresetRange(this.currentRange, false);
    }
  }

  _updateHashParams() {
    const params = new URLSearchParams();
    if (this.fromIso) params.set("from", this.fromIso);
    if (this.toIso) params.set("to", this.toIso);
    if (this.selectedDevice) params.set("device_id", this.selectedDevice);
    window.location.hash = `#/history?${params.toString()}`;
  }

  _applyPresetRange(preset, reload = true) {
    this.currentRange = preset;
    const now = new Date();
    const tzOffsetMs = now.getTimezoneOffset() * 60 * 1000;

    if (preset === "today") {
      // Local start of today
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      this.fromIso = new Date(startOfToday.getTime()).toISOString();
      this.toIso = now.toISOString();
    } else if (preset === "yesterday") {
      const yestStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
      const yestEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, -1);
      this.fromIso = yestStart.toISOString();
      this.toIso = yestEnd.toISOString();
    } else if (preset === "week") {
      const weekAgo = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
      this.fromIso = weekAgo.toISOString();
      this.toIso = now.toISOString();
    } else if (preset === "all") {
      if (this.bounds && this.bounds.first_ts) {
        this.fromIso = this.bounds.first_ts;
      } else {
        this.fromIso = new Date(now.getTime() - 7 * 24 * 3600 * 1000).toISOString();
      }
      this.toIso = now.toISOString();
    }

    this.zoomFromIso = null;
    this.zoomToIso = null;
    this._updateHashParams();
    if (reload) {
      this._renderHeaderControls();
      this.loadData();
    }
  }

  _renderHeaderControls() {
    const bannerEl = document.getElementById("hist-sim-banner");
    const isSim = this.selectedDevice && this.selectedDevice.startsWith("sim-");
    if (isSim) {
      bannerEl.innerHTML = `
        <div class="simulated-data-banner">
          <span>⚠️</span>
          <span><strong>SIMULATED DATA</strong> — synthetic demo device active (${this.selectedDevice})</span>
        </div>
      `;
    } else {
      bannerEl.innerHTML = "";
    }

    const subEl = document.getElementById("hist-subtitle");
    let availableText = "Data available for the past 7 days (retention limit).";
    if (this.bounds && this.bounds.first_ts && this.bounds.last_ts) {
      const fStr = new Date(this.bounds.first_ts).toLocaleDateString([], { month: "short", day: "numeric" });
      const lStr = new Date(this.bounds.last_ts).toLocaleDateString([], { month: "short", day: "numeric" });
      availableText = `Data available from ${fStr} to ${lStr} • History goes back 7 days.`;
    }
    subEl.textContent = availableText;

    const ctrlEl = document.getElementById("hist-header-controls");
    ctrlEl.innerHTML = `
      <div class="segmented-control" id="hist-range-pills">
        <button class="seg-btn ${this.currentRange === "today" ? "active" : ""}" data-range="today">Today</button>
        <button class="seg-btn ${this.currentRange === "yesterday" ? "active" : ""}" data-range="yesterday">Yesterday</button>
        <button class="seg-btn ${this.currentRange === "week" ? "active" : ""}" data-range="week">Last 7 days</button>
        <button class="seg-btn ${this.currentRange === "all" ? "active" : ""}" data-range="all">All available</button>
      </div>

      <div style="display: flex; align-items: center; gap: 0.4rem;">
        <input type="datetime-local" class="btn" id="hist-custom-from" style="padding: 0.35rem 0.6rem; font-size: 0.85rem;" />
        <span style="color: var(--text-muted); font-size: 0.85rem;">to</span>
        <input type="datetime-local" class="btn" id="hist-custom-to" style="padding: 0.35rem 0.6rem; font-size: 0.85rem;" />
        <button class="btn btn-secondary" id="hist-custom-apply" style="padding: 0.35rem 0.75rem;">Apply</button>
      </div>

      ${this.devices.length > 1 ? `
        <select class="btn" id="hist-device-select" style="padding: 0.35rem 0.6rem;">
          ${this.devices.map(d => `<option value="${d.device_id}" ${d.device_id === this.selectedDevice ? "selected" : ""}>${d.device_id}</option>`).join("")}
        </select>
      ` : ""}

      <button class="btn btn-secondary" id="hist-export-btn" style="display: flex; align-items: center; gap: 0.4rem;">
        <span>📥</span> Download CSV
      </button>
    `;

    // Populate custom picker values in local time
    const fromInput = document.getElementById("hist-custom-from");
    const toInput = document.getElementById("hist-custom-to");
    if (this.fromIso) {
      const fDate = new Date(this.fromIso);
      fromInput.value = this._toLocalDatetimeInput(fDate);
    }
    if (this.toIso) {
      const tDate = new Date(this.toIso);
      toInput.value = this._toLocalDatetimeInput(tDate);
    }

    // Bind pill buttons
    ctrlEl.querySelectorAll("#hist-range-pills .seg-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const rng = btn.getAttribute("data-range");
        this._applyPresetRange(rng);
      });
    });

    // Custom Apply
    document.getElementById("hist-custom-apply").addEventListener("click", () => {
      const fVal = fromInput.value;
      const tVal = toInput.value;
      if (fVal && tVal) {
        this.fromIso = new Date(fVal).toISOString();
        this.toIso = new Date(tVal).toISOString();
        this.currentRange = "custom";
        this.zoomFromIso = null;
        this.zoomToIso = null;
        this._updateHashParams();
        this._renderHeaderControls();
        this.loadData();
      }
    });

    // Device change
    const devSelect = document.getElementById("hist-device-select");
    if (devSelect) {
      devSelect.addEventListener("change", (e) => {
        this.selectedDevice = e.target.value;
        this._updateHashParams();
        this._renderHeaderControls();
        this.loadData();
      });
    }

    // CSV Download
    document.getElementById("hist-export-btn").addEventListener("click", () => {
      const tzOffset = -new Date().getTimezoneOffset();
      const csvUrl = `/api/history/export.csv?device_id=${encodeURIComponent(this.selectedDevice)}&from=${encodeURIComponent(this.zoomFromIso || this.fromIso)}&to=${encodeURIComponent(this.zoomToIso || this.toIso)}&tz_offset_minutes=${tzOffset}`;
      window.location.href = csvUrl;
    });
  }

  _toLocalDatetimeInput(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  async loadData() {
    const contentEl = document.getElementById("hist-content");
    contentEl.innerHTML = `
      <div class="loading-state">
        <span class="spinner-inline"></span> Fetching timeline and day statistics...
      </div>
    `;

    const activeFrom = this.zoomFromIso || this.fromIso;
    const activeTo = this.zoomToIso || this.toIso;
    const tzOffset = -new Date().getTimezoneOffset();

    const queryParams = {
      device_id: this.selectedDevice,
      from: activeFrom,
      to: activeTo,
      tz_offset_minutes: tzOffset,
    };

    try {
      const [summary, timeline, daysRes, sessionsRes] = await Promise.all([
        api.fetchHistorySummary(queryParams),
        api.fetchHistoryTimeline(queryParams),
        api.fetchHistoryDays(queryParams),
        api.fetchSessions({ ...queryParams, limit: 10 }),
      ]);

      this._renderHistoryContent(summary, timeline, daysRes.days || [], sessionsRes.sessions || [], sessionsRes.total || 0, activeFrom, activeTo);
    } catch (err) {
      contentEl.innerHTML = `
        <div class="placeholder-card" style="margin: 2rem auto; max-width: 500px; text-align: center;">
          <div style="font-size: 2rem; margin-bottom: 0.5rem;">⚠️</div>
          <h3>Failed to load history</h3>
          <p style="color: var(--text-muted); margin: 0.5rem 0 1rem 0;">${err.message || "Network error"}</p>
          <button class="btn btn-primary" id="hist-retry-btn">Retry</button>
        </div>
      `;
      document.getElementById("hist-retry-btn")?.addEventListener("click", () => this.loadData());
    }
  }

  _renderHistoryContent(summary, timeline, days, sessions, totalSessions, activeFrom, activeTo) {
    const contentEl = document.getElementById("hist-content");

    if (!timeline.series || timeline.series.length === 0) {
      contentEl.innerHTML = `
        <div class="placeholder-card" style="margin: 3rem auto; max-width: 500px; text-align: center;">
          <div style="font-size: 2.5rem; margin-bottom: 0.5rem;">📅</div>
          <h3>No data in this range</h3>
          <p style="color: var(--text-muted); margin: 0.5rem 0 1rem 0;">
            No posture telemetry was recorded for this device between the selected dates.
          </p>
          <button class="btn btn-secondary" id="hist-empty-reset">Show all available data</button>
        </div>
      `;
      document.getElementById("hist-empty-reset")?.addEventListener("click", () => this._applyPresetRange("all"));
      return;
    }

    const fmtVal = (val, suffix = "") => (val !== null && val !== undefined ? `${val}${suffix}` : "Not enough data yet");

    contentEl.innerHTML = `
      <!-- Summary Cards Row -->
      <div class="summary-cards-row">
        <div class="summary-card" title="Total active recording duration">
          <div class="summary-card-label">Monitored time</div>
          <div class="summary-card-val">${summary.monitored_time_text || fmtVal(summary.monitored_seconds, "s")}</div>
          <div class="summary-card-hint">${summary.sessions_count || 0} active sessions</div>
        </div>

        <div class="summary-card" title="Percentage of standing time maintaining upright posture">
          <div class="summary-card-label">Good posture (while standing)</div>
          <div class="summary-card-val" style="color: ${summary.good_posture_percent >= 75 ? 'var(--color-green)' : 'var(--color-yellow)'};">
            ${fmtVal(summary.good_posture_percent, "%")}
          </div>
          <div class="summary-card-hint">While standing</div>
        </div>

        <div class="summary-card" title="Total bend events exceeding warning threshold">
          <div class="summary-card-label">Slouches</div>
          <div class="summary-card-val">${summary.slouch_count ?? 0}</div>
          <div class="summary-card-hint">Avg length: ${fmtVal(summary.avg_slouch_length_s, "s")}</div>
        </div>

        <div class="summary-card" title="Longest continuous forward slouch">
          <div class="summary-card-label">Longest slouch</div>
          <div class="summary-card-val">${fmtVal(summary.longest_slouch_s, "s")}</div>
          <div class="summary-card-hint">Peak angle event</div>
        </div>

        <div class="summary-card" title="Time spent sitting vs standing">
          <div class="summary-card-label">Time sitting</div>
          <div class="summary-card-val">${fmtVal(summary.percent_per_category?.SITTING, "%")}</div>
          <div class="summary-card-hint">${Math.round((summary.time_per_category?.SITTING || 0) / 60)} min seated</div>
        </div>

        <div class="summary-card" title="Average heart rate during valid readings">
          <div class="summary-card-label">Heart rate</div>
          <div class="summary-card-val">${fmtVal(summary.avg_heart_rate_bpm, " bpm")}</div>
          <div class="summary-card-hint">Sensor contact: active</div>
        </div>
      </div>

      <!-- Posture Timeline Hero Strip -->
      <div class="timeline-card">
        <div class="timeline-header-bar">
          <div>
            <h3 style="font-size: 1.15rem; font-weight: 700;">Posture Timeline</h3>
            <div style="font-size: 0.8rem; color: var(--text-faint); margin-top: 0.2rem;">
              Click and drag to zoom into any interval. Each point = ${timeline.resolution_s || 1}s average.
              ${this.zoomFromIso ? `<button class="btn btn-secondary" id="hist-reset-zoom" style="padding: 0.15rem 0.5rem; font-size: 0.75rem; margin-left: 0.5rem;">Reset zoom</button>` : ""}
            </div>
          </div>
          <label class="toggle-control">
            <input type="checkbox" id="hist-toggle-vitals" ${this.showVitals ? "checked" : ""}>
            <span>Show vitals</span>
          </label>
        </div>

        <div class="timeline-strip-container" id="timeline-strip-container">
          <canvas class="timeline-canvas" id="timeline-strip-canvas"></canvas>
          <div id="timeline-tooltip" style="position: absolute; display: none; background: rgba(11,16,32,0.9); border: 1px solid var(--border-accent); border-radius: var(--radius-sm); padding: 0.3rem 0.6rem; font-size: 0.75rem; color: #fff; pointer-events: none; z-index: 10;"></div>
        </div>
        <div class="timeline-axis-labels" id="timeline-axis-labels"></div>

        <div class="timeline-vitals-container ${this.showVitals ? "" : "hidden"}" id="timeline-vitals-wrapper">
          <canvas id="timeline-vitals-chart"></canvas>
        </div>
      </div>

      <!-- Day by Day breakdown -->
      <div style="margin-bottom: 1.5rem;">
        <h3 style="font-size: 1.15rem; font-weight: 700; margin-bottom: 0.75rem;">Daily Breakdown</h3>
        <div class="day-cards-list">
          ${days.length === 0 ? `<div style="color: var(--text-muted); font-size: 0.9rem;">No daily summaries available.</div>` : ""}
          ${days.map(d => `
            <div class="day-row-card" data-date="${d.date}">
              <div>
                <strong style="color: var(--text-main); font-size: 0.95rem;">${d.date}</strong>
                <div style="font-size: 0.75rem; color: var(--text-faint);">${d.sessions_count} sessions</div>
              </div>
              <div style="font-size: 0.9rem; color: var(--text-muted);">${d.monitored_time_text}</div>
              <div>
                <div class="day-mini-bar">
                  <div style="width: ${d.posture_share?.UPRIGHT || 0}%; background: var(--color-green);"></div>
                  <div style="width: ${d.posture_share?.SITTING || 0}%; background: var(--color-blue);"></div>
                  <div style="width: ${d.posture_share?.WARNING || 0}%; background: var(--color-yellow);"></div>
                  <div style="width: ${d.posture_share?.ALERT || 0}%; background: var(--color-red);"></div>
                </div>
                <div style="font-size: 0.72rem; color: var(--text-faint); margin-top: 0.2rem;">${d.good_posture_percent}% good posture</div>
              </div>
              <div style="font-size: 0.88rem; color: var(--text-main);">${d.slouch_count} slouches</div>
              <div style="font-size: 0.88rem; color: var(--text-muted);">${d.longest_slouch_s ? d.longest_slouch_s + 's peak' : '—'}</div>
              <div style="font-size: 0.88rem; color: var(--text-muted);">${d.avg_heart_rate_bpm ? d.avg_heart_rate_bpm + ' bpm' : '—'}</div>
            </div>
          `).join("")}
        </div>
      </div>

      <!-- Monitoring Sessions -->
      <div style="margin-bottom: 1.5rem;">
        <h3 style="font-size: 1.15rem; font-weight: 700; margin-bottom: 0.75rem;">Monitoring Sessions</h3>
        <div class="sessions-list-container">
          ${sessions.length === 0 ? `<div style="color: var(--text-muted); font-size: 0.9rem;">No continuous sessions found.</div>` : ""}
          ${sessions.map(s => {
            const sStart = new Date(s.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const sEnd = new Date(s.end).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            return `
              <div class="session-item-row" data-start="${s.start}" data-end="${s.end}">
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                  <span style="font-size: 1.2rem;">⏱️</span>
                  <div>
                    <strong style="color: var(--text-main); font-size: 0.92rem;">${sStart} – ${sEnd}</strong>
                    <div style="font-size: 0.75rem; color: var(--text-muted);">${s.duration_text} duration</div>
                  </div>
                </div>
                <div style="display: flex; align-items: center; gap: 1.5rem; font-size: 0.88rem;">
                  <div><span style="color: var(--text-muted);">Good posture:</span> <strong style="color: var(--color-green);">${s.good_posture_percent}%</strong></div>
                  <div><span style="color: var(--text-muted);">Slouches:</span> <strong>${s.slouch_count}</strong></div>
                  <div><span style="color: var(--text-muted);">Heart rate:</span> <strong>${s.avg_heart_rate_bpm ? s.avg_heart_rate_bpm + ' bpm' : '—'}</strong></div>
                </div>
              </div>
            `;
          }).join("")}
        </div>
      </div>

      <!-- Raw Readings Collapsible -->
      <div class="timeline-card" style="margin-bottom: 1.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <h3 style="font-size: 1.15rem; font-weight: 700;">Raw Telemetry Readings</h3>
          <button class="btn btn-secondary" id="hist-toggle-readings-btn">
            ${this.showReadings ? "Hide raw readings" : "Show raw readings"}
          </button>
        </div>

        <div id="hist-readings-panel" class="${this.showReadings ? "" : "hidden"}" style="margin-top: 1rem;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; flex-wrap: wrap; gap: 0.5rem;">
            <label class="toggle-control">
              <input type="checkbox" id="hist-readings-more-cols" ${this.readingsMoreCols ? "checked" : ""}>
              <span>Show technical sensor columns</span>
            </label>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <button class="btn btn-secondary" id="hist-order-btn" style="padding: 0.25rem 0.6rem; font-size: 0.8rem;">
                Order: ${this.readingsOrder.toUpperCase()}
              </button>
              <div id="hist-readings-page-info" style="font-size: 0.8rem; color: var(--text-muted);"></div>
              <button class="btn btn-secondary" id="hist-readings-prev" style="padding: 0.25rem 0.5rem;">‹</button>
              <button class="btn btn-secondary" id="hist-readings-next" style="padding: 0.25rem 0.5rem;">›</button>
            </div>
          </div>

          <div class="data-table-wrapper" id="hist-readings-table-container">
            <div style="padding: 1.5rem; text-align: center; color: var(--text-muted);">Loading readings...</div>
          </div>
        </div>
      </div>
    `;

    // Initialize Hero Timeline canvas & vitals
    this._renderTimelineStrip(timeline.segments, activeFrom, activeTo);
    if (this.showVitals) {
      this._renderVitalsChart(timeline.series);
    }

    // Bind Timeline vitals toggle & reset zoom
    document.getElementById("hist-toggle-vitals")?.addEventListener("change", (e) => {
      this.showVitals = e.target.checked;
      const wrap = document.getElementById("timeline-vitals-wrapper");
      if (this.showVitals) {
        wrap.classList.remove("hidden");
        this._renderVitalsChart(timeline.series);
      } else {
        wrap.classList.add("hidden");
      }
    });

    document.getElementById("hist-reset-zoom")?.addEventListener("click", () => {
      this.zoomFromIso = null;
      this.zoomToIso = null;
      this.loadData();
    });

    // Bind Day clicks -> sets range to that day
    contentEl.querySelectorAll(".day-row-card").forEach(card => {
      card.addEventListener("click", () => {
        const dStr = card.getAttribute("data-date");
        const [year, month, day] = dStr.split("-").map(Number);
        const dayStart = new Date(year, month - 1, day, 0, 0, 0);
        const dayEnd = new Date(year, month - 1, day, 23, 59, 59);
        this.fromIso = dayStart.toISOString();
        this.toIso = dayEnd.toISOString();
        this.zoomFromIso = null;
        this.zoomToIso = null;
        this.currentRange = "custom";
        this._updateHashParams();
        this._renderHeaderControls();
        this.loadData();
      });
    });

    // Bind Session clicks -> sets range to session
    contentEl.querySelectorAll(".session-item-row").forEach(row => {
      row.addEventListener("click", () => {
        const sStart = row.getAttribute("data-start");
        const sEnd = row.getAttribute("data-end");
        if (sStart && sEnd) {
          this.fromIso = sStart;
          this.toIso = sEnd;
          this.zoomFromIso = null;
          this.zoomToIso = null;
          this.currentRange = "custom";
          this._updateHashParams();
          this._renderHeaderControls();
          this.loadData();
        }
      });
    });

    // Bind Readings toggle & pagination
    document.getElementById("hist-toggle-readings-btn")?.addEventListener("click", () => {
      this.showReadings = !this.showReadings;
      document.getElementById("hist-readings-panel").classList.toggle("hidden", !this.showReadings);
      document.getElementById("hist-toggle-readings-btn").textContent = this.showReadings ? "Hide raw readings" : "Show raw readings";
      if (this.showReadings) {
        this.loadReadings();
      }
    });

    document.getElementById("hist-readings-more-cols")?.addEventListener("change", (e) => {
      this.readingsMoreCols = e.target.checked;
      this.loadReadings();
    });

    document.getElementById("hist-order-btn")?.addEventListener("click", () => {
      this.readingsOrder = this.readingsOrder === "desc" ? "asc" : "desc";
      document.getElementById("hist-order-btn").textContent = `Order: ${this.readingsOrder.toUpperCase()}`;
      this.readingsPage = 0;
      this.loadReadings();
    });

    document.getElementById("hist-readings-prev")?.addEventListener("click", () => {
      if (this.readingsPage > 0) {
        this.readingsPage--;
        this.loadReadings();
      }
    });

    document.getElementById("hist-readings-next")?.addEventListener("click", () => {
      if ((this.readingsPage + 1) * this.readingsLimit < this.readingsTotal) {
        this.readingsPage++;
        this.loadReadings();
      }
    });
  }

  _renderTimelineStrip(segments, rangeStartIso, rangeEndIso) {
    const canvas = document.getElementById("timeline-strip-canvas");
    const container = document.getElementById("timeline-strip-container");
    const tooltip = document.getElementById("timeline-tooltip");
    const labelsEl = document.getElementById("timeline-axis-labels");
    if (!canvas || !container) return;

    const startMs = new Date(rangeStartIso).getTime();
    const endMs = new Date(rangeEndIso).getTime();
    const spanMs = Math.max(1000, endMs - startMs);

    // Setup axis labels
    labelsEl.innerHTML = `
      <span>${new Date(startMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} (${new Date(startMs).toLocaleDateString([], { month: 'short', day: 'numeric' })})</span>
      <span>${new Date(startMs + spanMs / 2).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
      <span>${new Date(endMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} (${new Date(endMs).toLocaleDateString([], { month: 'short', day: 'numeric' })})</span>
    `;

    // Resize canvas
    const rect = container.getBoundingClientRect();
    canvas.width = rect.width * (window.devicePixelRatio || 1);
    canvas.height = rect.height * (window.devicePixelRatio || 1);

    const ctx = canvas.getContext("2d");
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);
    ctx.clearRect(0, 0, rect.width, rect.height);

    const colorMap = {
      UPRIGHT: "#2ecc71",
      SITTING: "#3498db",
      WARNING: "#f5c542",
      ALERT: "#ff4d5e",
    };

    // Draw run-length segments
    for (const seg of segments) {
      const segStart = new Date(seg.start).getTime();
      const segEnd = new Date(seg.end).getTime();
      const x1 = Math.max(0, ((segStart - startMs) / spanMs) * rect.width);
      const x2 = Math.min(rect.width, ((segEnd - startMs) / spanMs) * rect.width);
      const w = Math.max(1.5, x2 - x1);

      ctx.fillStyle = colorMap[seg.cat] || "#5a6e85";
      ctx.fillRect(x1, 0, w, rect.height);
    }

    // Drag-zoom handlers
    container.onmousedown = (e) => {
      this.isDragging = true;
      const b = container.getBoundingClientRect();
      this.dragStartX = e.clientX - b.left;
      this.dragCurrentX = this.dragStartX;
    };

    window.onmousemove = (e) => {
      if (!container) return;
      const b = container.getBoundingClientRect();
      const curX = e.clientX - b.left;

      if (this.isDragging) {
        this.dragCurrentX = Math.max(0, Math.min(b.width, curX));
        // Redraw with selection overlay
        ctx.clearRect(0, 0, rect.width, rect.height);
        for (const seg of segments) {
          const segStart = new Date(seg.start).getTime();
          const segEnd = new Date(seg.end).getTime();
          const x1 = Math.max(0, ((segStart - startMs) / spanMs) * rect.width);
          const x2 = Math.min(rect.width, ((segEnd - startMs) / spanMs) * rect.width);
          const w = Math.max(1.5, x2 - x1);
          ctx.fillStyle = colorMap[seg.cat] || "#5a6e85";
          ctx.fillRect(x1, 0, w, rect.height);
        }
        // Selection rect
        const selLeft = Math.min(this.dragStartX, this.dragCurrentX);
        const selWidth = Math.abs(this.dragCurrentX - this.dragStartX);
        ctx.fillStyle = "rgba(52, 152, 219, 0.35)";
        ctx.fillRect(selLeft, 0, selWidth, rect.height);
        ctx.strokeStyle = "#3498db";
        ctx.lineWidth = 1;
        ctx.strokeRect(selLeft, 0, selWidth, rect.height);
      } else if (curX >= 0 && curX <= b.width) {
        // Hover tooltip
        const hoverMs = startMs + (curX / b.width) * spanMs;
        const hoverIso = new Date(hoverMs).toISOString();
        const activeSeg = segments.find(s => s.start <= hoverIso && hoverIso <= s.end);
        tooltip.style.display = "block";
        tooltip.style.left = `${Math.min(b.width - 120, curX + 10)}px`;
        tooltip.style.top = "8px";
        const tStr = new Date(hoverMs).toLocaleTimeString();
        tooltip.innerHTML = `<strong>${tStr}</strong><br>${activeSeg ? activeSeg.cat : "Gap / No data"}`;
      } else {
        tooltip.style.display = "none";
      }
    };

    window.onmouseup = () => {
      if (this.isDragging) {
        this.isDragging = false;
        const diffX = Math.abs(this.dragCurrentX - this.dragStartX);
        if (diffX > 15) {
          const minX = Math.min(this.dragStartX, this.dragCurrentX);
          const maxX = Math.max(this.dragStartX, this.dragCurrentX);
          const zStartMs = startMs + (minX / rect.width) * spanMs;
          const zEndMs = startMs + (maxX / rect.width) * spanMs;
          this.zoomFromIso = new Date(zStartMs).toISOString();
          this.zoomToIso = new Date(zEndMs).toISOString();
          this.loadData();
        }
      }
    };
  }

  _renderVitalsChart(series) {
    const canvas = document.getElementById("timeline-vitals-chart");
    if (!canvas) return;

    if (this.vitalsChart) {
      this.vitalsChart.destroy();
    }

    const labels = series.map(p => new Date(p.t).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
    const pitchData = series.map(p => p.pitch);
    const hrData = series.map(p => p.hr);
    const tempData = series.map(p => p.temp);

    this.vitalsChart = new Chart(canvas, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Lean angle (°)",
            data: pitchData,
            borderColor: "#f5c542",
            borderWidth: 1.5,
            pointRadius: 0,
            yAxisID: "yPitch",
          },
          {
            label: "Heart rate (bpm)",
            data: hrData,
            borderColor: "#ff4d5e",
            borderWidth: 1.5,
            pointRadius: 0,
            yAxisID: "yHr",
          },
          {
            label: "Temperature (°C)",
            data: tempData,
            borderColor: "#3498db",
            borderWidth: 1.2,
            borderDash: [4, 4],
            pointRadius: 0,
            yAxisID: "yTemp",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            ticks: { color: "#8e9fb3", maxTicksLimit: 8 },
            grid: { color: "rgba(255, 255, 255, 0.05)" },
          },
          yPitch: {
            type: "linear",
            position: "left",
            ticks: { color: "#f5c542" },
            grid: { color: "rgba(255, 255, 255, 0.05)" },
          },
          yHr: {
            type: "linear",
            position: "right",
            ticks: { color: "#ff4d5e" },
            grid: { drawOnChartArea: false },
          },
          yTemp: {
            type: "linear",
            position: "right",
            ticks: { color: "#3498db" },
            grid: { drawOnChartArea: false },
          },
        },
        plugins: {
          legend: { labels: { color: "#f0f4f8", boxWidth: 12 } },
        },
      },
    });
  }

  async loadReadings() {
    const container = document.getElementById("hist-readings-table-container");
    const pageInfo = document.getElementById("hist-readings-page-info");
    const activeFrom = this.zoomFromIso || this.fromIso;
    const activeTo = this.zoomToIso || this.toIso;
    const tzOffset = -new Date().getTimezoneOffset();

    try {
      const data = await api.fetchHistoryReadings({
        device_id: this.selectedDevice,
        from: activeFrom,
        to: activeTo,
        tz_offset_minutes: tzOffset,
        limit: this.readingsLimit,
        offset: this.readingsPage * this.readingsLimit,
        order: this.readingsOrder,
      });

      this.readingsTotal = data.total;
      const startIdx = this.readingsPage * this.readingsLimit + 1;
      const endIdx = Math.min(this.readingsTotal, (this.readingsPage + 1) * this.readingsLimit);
      pageInfo.textContent = `${this.readingsTotal === 0 ? 0 : startIdx}–${endIdx} of ${this.readingsTotal}`;

      const rows = data.rows || [];
      if (rows.length === 0) {
        container.innerHTML = `<div style="padding: 1.5rem; text-align: center; color: var(--text-muted);">No raw readings found in this range.</div>`;
        return;
      }

      container.innerHTML = `
        <table class="data-table">
          <thead>
            <tr>
              <th>Time (local)</th>
              <th>Posture</th>
              <th>Lean angle</th>
              <th>Standing</th>
              <th>Heart rate</th>
              <th>Temp</th>
              <th>Humidity</th>
              ${this.readingsMoreCols ? `
                <th>Side lean</th>
                <th>Thigh tilt</th>
                <th>Sensors</th>
              ` : ""}
            </tr>
          </thead>
          <tbody>
            ${rows.map(r => `
              <tr>
                <td>${r.local_time}</td>
                <td><span class="status-pill status-${(r.posture_category || 'upright').toLowerCase()}">${r.posture_category}</span></td>
                <td>${r.lean_angle !== null ? r.lean_angle + '°' : '—'}</td>
                <td>${r.is_standing ? 'Yes' : 'No (Sitting)'}</td>
                <td>${r.heart_rate !== null ? r.heart_rate + ' bpm' : '—'}</td>
                <td>${r.temperature_c !== null ? r.temperature_c + '°C' : '—'}</td>
                <td>${r.humidity_pct !== null ? r.humidity_pct + '%' : '—'}</td>
                ${this.readingsMoreCols ? `
                  <td>${r.imu_roll_deg !== null ? r.imu_roll_deg + '°' : '—'}</td>
                  <td>${r.adxl_tilt_deg !== null ? r.adxl_tilt_deg + '°' : '—'}</td>
                  <td>${r.mpu_ok && r.adxl_ok ? 'OK' : 'ERR'}</td>
                ` : ""}
              </tr>
            `).join("")}
          </tbody>
        </table>
      `;
    } catch (err) {
      container.innerHTML = `<div style="padding: 1.5rem; text-align: center; color: var(--color-red);">Failed to load readings: ${err.message}</div>`;
    }
  }
}
