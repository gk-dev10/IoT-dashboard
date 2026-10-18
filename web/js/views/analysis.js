/**
 * Smart Posture T-Shirt v2 — Analysis Page View
 *
 * Implements:
 * 1. SIMULATED DATA banner when meta.simulated is true
 * 2. Range selector (5m, 15m, 1h, 6h, 24h, All)
 * 3. Exclude moving toggle (default on)
 * 4. 15s auto-refresh with Pause/Resume and "Updated X s ago" ticker
 * 5. Download CSV button (GET /api/analysis/export.csv)
 * 6. "How to read this" drawer detailing sensor limits and definitions
 * 7. Data quality metrics strip (HR %, Temp %, Hum %, Moving %, Buckets, Time Range)
 * 8. Hero Overlay Chart with custom background bands plugin for posture categories (UPRIGHT, WARNING, ALERT, SITTING),
 *    HR, Air Temp, Air Hum, Pitch toggle, and 0-100% normalization
 * 9. Posture Comparison card (stacked time share bar, HR/Temp/Hum stats with sample size n, "Not enough data" placeholders)
 * 10. Bend Episode Impact panel (aligned trace [-60s..+60s], episode table, average change line)
 * 11. Relationships grid (2x2 scatter plots with trendlines, plus temp vs hum row)
 * 12. Conservative server insights panel
 */

import { api } from "../api.js";

// Posture Category Palette (Section 5)
const POSTURE_COLORS = {
  UPRIGHT: "#2ecc71",
  WARNING: "#f5c542",
  ALERT: "#ff4d5e",
  SITTING: "#6c8cff",
  UNKNOWN: "#4b5563",
};

const POSTURE_BG_COLORS = {
  UPRIGHT: "rgba(46, 204, 113, 0.12)",
  WARNING: "rgba(245, 197, 66, 0.18)",
  ALERT: "rgba(255, 77, 94, 0.22)",
  SITTING: "rgba(108, 140, 255, 0.14)",
};

export class AnalysisView {
  constructor(container) {
    this.container = container;
    this.minutes = 60;
    this.excludeMoving = 1;
    this.autoRefresh = true;
    this.timerId = null;
    this.tickerId = null;
    this.lastUpdated = null;
    this.data = null;
    this.isLoading = false;

    // Overlay chart state
    this.overlayChart = null;
    this.visibleSeries = {
      hr: true,
      temp: true,
      hum: false,
      pitch: false,
    };
    this.normalized = false;

    // Episode & Scatter charts
    this.alignedChart = null;
    this.scatterCharts = {};
  }

  mount() {
    this.renderSkeleton();
    this.setupEventListeners();
    this.loadData();
    this.startAutoRefresh();
  }

  unmount() {
    this.stopAutoRefresh();
    this.destroyCharts();
    if (this.drawerEl && this.drawerEl.parentNode) {
      this.drawerEl.remove();
    }
  }

  startAutoRefresh() {
    this.stopAutoRefresh();
    this.timerId = setInterval(() => {
      if (this.autoRefresh && !this.isLoading) {
        this.loadData(true);
      }
    }, 15000);

    this.tickerId = setInterval(() => {
      this.updateTicker();
    }, 1000);
  }

  stopAutoRefresh() {
    if (this.timerId) clearInterval(this.timerId);
    if (this.tickerId) clearInterval(this.tickerId);
    this.timerId = null;
    this.tickerId = null;
  }

  updateTicker() {
    const tickerEl = document.getElementById("analysis-ticker");
    if (!tickerEl) return;
    if (!this.lastUpdated) {
      tickerEl.textContent = "Syncing...";
      return;
    }
    const sec = Math.floor((Date.now() - this.lastUpdated) / 1000);
    tickerEl.textContent = `Updated ${sec}s ago`;
  }

  async loadData(silent = false) {
    this.isLoading = true;
    if (!silent) {
      const loader = document.getElementById("analysis-spinner");
      if (loader) loader.classList.remove("hidden");
    }

    try {
      const res = await api.fetchAnalysis(this.minutes, this.excludeMoving);
      if (res && res.meta) {
        this.data = res;
        this.lastUpdated = Date.now();
        this.render();
      } else {
        console.warn("Analysis response empty or invalid:", res);
      }
    } catch (err) {
      console.error("Failed to load analysis:", err);
      this.renderError(err.message || "Unable to reach server");
    } finally {
      this.isLoading = false;
      const loader = document.getElementById("analysis-spinner");
      if (loader) loader.classList.add("hidden");
      this.updateTicker();
    }
  }

  renderSkeleton() {
    this.container.innerHTML = `
      <div class="analysis-view" id="analysis-page">
        <!-- Top Banner Placeholder -->
        <div id="sim-banner-container"></div>

        <!-- Page Header & Controls -->
        <header class="analysis-header">
          <div class="title-group">
            <h1 class="analysis-title">Posture & Vitals Analysis</h1>
            <p class="analysis-subtitle">Correlating posture state against heart rate, near-body air temperature and air humidity</p>
          </div>

          <div class="header-controls">
            <!-- Range Selector -->
            <div class="segmented-control" id="range-control" role="group" aria-label="Analysis Time Range">
              <button class="seg-btn" data-minutes="5">5 min</button>
              <button class="seg-btn" data-minutes="15">15 min</button>
              <button class="seg-btn active" data-minutes="60">1 h</button>
              <button class="seg-btn" data-minutes="360">6 h</button>
              <button class="seg-btn" data-minutes="1440">24 h</button>
              <button class="seg-btn" data-minutes="0">All</button>
            </div>

            <!-- Exclude Moving Switch -->
            <label class="toggle-control" title="Drop heart rate during movement to avoid optical motion artifacts">
              <input type="checkbox" id="chk-exclude-moving" ${this.excludeMoving ? "checked" : ""}>
              <span class="toggle-label">Exclude moving (HR)</span>
            </label>

            <!-- Auto-Refresh & Ticker -->
            <div class="refresh-group">
              <button class="btn btn-secondary btn-sm" id="btn-toggle-refresh">
                <span id="refresh-state-icon">⏸</span> <span id="refresh-state-text">Pause</span>
              </button>
              <span class="refresh-ticker" id="analysis-ticker">Syncing...</span>
              <span class="spinner-inline hidden" id="analysis-spinner"></span>
            </div>

            <!-- Download CSV -->
            <button class="btn btn-secondary btn-sm" id="btn-export-csv" title="Download 5s aggregated bucket table">
              📥 Export CSV
            </button>

            <!-- How to read this -->
            <button class="btn btn-secondary btn-sm" id="btn-open-drawer">
              ℹ️ How to read this
            </button>
          </div>
        </header>

        <!-- Main Dynamic Body Container -->
        <div id="analysis-content" class="analysis-content">
          <div class="analysis-skeleton-card card">
            <div class="skeleton-shimmer" style="height: 60px;"></div>
          </div>
          <div class="analysis-skeleton-card card" style="margin-top: 1rem;">
            <div class="skeleton-shimmer" style="height: 320px;"></div>
          </div>
        </div>

        <!-- Info Drawer Modal / Overlay -->
        <div id="info-drawer" class="drawer-overlay hidden">
          <div class="drawer-panel">
            <div class="drawer-header">
              <h2>How to read this analysis</h2>
              <button class="drawer-close-btn" id="btn-close-drawer">✕</button>
            </div>
            <div class="drawer-body">
              <section class="drawer-section">
                <h3>⚠️ Sensor Limits & Honesty Rules</h3>
                <ul>
                  <li><strong>Air Temperature & Humidity:</strong> Measured by a DHT11 sensor near the torso, <em>not skin temperature</em>. It has a coarse resolution (~±2 °C, ±5 %RH) and updates once every 5 seconds.</li>
                  <li><strong>Heart Rate (BPM):</strong> Sourced from an optical MAX30105 sensor on the wrist/arm. It is sensitive to movement artifacts and is only considered valid when <code>finger_present</code> is true and BPM is between 40 and 200.</li>
                  <li><strong>Posture Categories:</strong> Defined relative to initial upright calibration.</li>
                  <li><strong>Correlation is not causation:</strong> Vitals and posture may covary without one directly triggering the other.</li>
                </ul>
              </section>

              <section class="drawer-section">
                <h3>📊 Aggregation & Thresholds</h3>
                <ul>
                  <li>All statistics operate on <strong>5-second bucket means</strong> to minimize autocorrelation bias.</li>
                  <li><strong>Group Summary Threshold:</strong> Requires at least 12 valid buckets (~1 minute) to summarize.</li>
                  <li><strong>Correlation Threshold:</strong> Requires at least 30 buckets with non-zero variance.</li>
                  <li><strong>Episode Window:</strong> Requires at least 5 valid samples in each window.</li>
                </ul>
              </section>

              <section class="drawer-section">
                <h3>🪑 Posture Categories</h3>
                <p>Each 5-second bucket is categorized by the highest severity present:</p>
                <div class="posture-pill-row">
                  <span class="badge" style="background: ${POSTURE_COLORS.ALERT}; color: #000;">ALERT</span>
                  <span class="badge" style="background: ${POSTURE_COLORS.WARNING}; color: #000;">WARNING</span>
                  <span class="badge" style="background: ${POSTURE_COLORS.SITTING}; color: #000;">SITTING</span>
                  <span class="badge" style="background: ${POSTURE_COLORS.UPRIGHT}; color: #000;">UPRIGHT</span>
                </div>
              </section>
            </div>
          </div>
        </div>
      </div>
    `;

    this.drawerEl = document.getElementById("info-drawer");
  }

  setupEventListeners() {
    // Range selector buttons
    const rangeControl = document.getElementById("range-control");
    if (rangeControl) {
      rangeControl.addEventListener("click", (e) => {
        const btn = e.target.closest(".seg-btn");
        if (!btn) return;
        const mins = parseInt(btn.getAttribute("data-minutes"), 10);
        if (isNaN(mins)) return;

        rangeControl.querySelectorAll(".seg-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");

        this.minutes = mins;
        this.loadData();
      });
    }

    // Exclude moving toggle
    const chkMoving = document.getElementById("chk-exclude-moving");
    if (chkMoving) {
      chkMoving.addEventListener("change", (e) => {
        this.excludeMoving = e.target.checked ? 1 : 0;
        this.loadData();
      });
    }

    // Auto-refresh toggle
    const btnRefresh = document.getElementById("btn-toggle-refresh");
    if (btnRefresh) {
      btnRefresh.addEventListener("click", () => {
        this.autoRefresh = !this.autoRefresh;
        const icon = document.getElementById("refresh-state-icon");
        const text = document.getElementById("refresh-state-text");
        if (this.autoRefresh) {
          if (icon) icon.textContent = "⏸";
          if (text) text.textContent = "Pause";
        } else {
          if (icon) icon.textContent = "▶";
          if (text) text.textContent = "Resume";
        }
      });
    }

    // CSV export button
    const btnCsv = document.getElementById("btn-export-csv");
    if (btnCsv) {
      btnCsv.addEventListener("click", () => {
        const url = `/api/analysis/export.csv?minutes=${this.minutes}&exclude_moving=${this.excludeMoving}`;
        window.location.href = url;
      });
    }

    // Drawer modal toggle
    const btnOpenDrawer = document.getElementById("btn-open-drawer");
    const btnCloseDrawer = document.getElementById("btn-close-drawer");
    const drawer = document.getElementById("info-drawer");

    if (btnOpenDrawer && drawer) {
      btnOpenDrawer.addEventListener("click", () => drawer.classList.remove("hidden"));
    }
    if (btnCloseDrawer && drawer) {
      btnCloseDrawer.addEventListener("click", () => drawer.classList.add("hidden"));
    }
    if (drawer) {
      drawer.addEventListener("click", (e) => {
        if (e.target === drawer) drawer.classList.add("hidden");
      });
    }
  }

  renderError(msg) {
    const content = document.getElementById("analysis-content");
    if (!content) return;
    content.innerHTML = `
      <div class="card error-card">
        <h3>Analysis Error</h3>
        <p>${msg}</p>
        <button class="btn btn-primary" id="btn-retry" style="margin-top: 1rem;">Retry</button>
      </div>
    `;
    const btnRetry = document.getElementById("btn-retry");
    if (btnRetry) btnRetry.addEventListener("click", () => this.loadData());
  }

  render() {
    const content = document.getElementById("analysis-content");
    if (!content || !this.data) return;

    const { meta, quality, time_share, by_posture, episode_impact, correlations, series, insights } = this.data;

    // 1. Simulated banner
    const bannerContainer = document.getElementById("sim-banner-container");
    if (bannerContainer) {
      if (meta && meta.simulated) {
        bannerContainer.innerHTML = `
          <div class="simulated-data-banner">
            <span class="sim-icon">⚠️</span>
            <strong>SIMULATED DATA</strong> — This analysis is computed from synthetic simulated device telemetry.
          </div>
        `;
      } else {
        bannerContainer.innerHTML = "";
      }
    }

    // 2. Build complete DOM layout
    content.innerHTML = `
      <!-- 5.2 Data Quality Strip -->
      <section class="quality-strip-card card">
        <div class="quality-grid">
          <div class="quality-item">
            <span class="quality-label">Heart Rate Valid</span>
            <span class="quality-value ${quality.hr_valid_pct < 50 ? "warn-text" : ""}">${quality.hr_valid_pct.toFixed(1)}%</span>
            ${quality.hr_valid_pct < 50 ? '<span class="warn-chip">Patchy signal</span>' : ""}
          </div>
          <div class="quality-item">
            <span class="quality-label">Air Temp Valid</span>
            <span class="quality-value">${quality.temp_valid_pct.toFixed(1)}%</span>
          </div>
          <div class="quality-item">
            <span class="quality-label">Air Hum Valid</span>
            <span class="quality-value">${quality.hum_valid_pct.toFixed(1)}%</span>
          </div>
          <div class="quality-item">
            <span class="quality-label">Time Moving</span>
            <span class="quality-value">${quality.moving_pct.toFixed(1)}%</span>
          </div>
          <div class="quality-item">
            <span class="quality-label">Buckets Analysed</span>
            <span class="quality-value">${meta.buckets} <small class="text-faint">(5s)</small></span>
          </div>
          <div class="quality-item">
            <span class="quality-label">Time Window</span>
            <span class="quality-value">${meta.minutes ? meta.minutes + " min" : "All retained"}</span>
          </div>
        </div>
        ${
          quality.hr_valid_pct < 50
            ? '<div class="quality-warning-bar">⚠️ Heart-rate coverage is patchy (< 50%) — heart-rate comparisons are unreliable.</div>'
            : ""
        }
      </section>

      <!-- 5.7 Conservative Insights Panel -->
      <section class="insights-card card">
        <div class="card-header">
          <h2 class="card-title">Automated Observations</h2>
          <span class="text-faint honesty-note">Correlation is not causation. Thresholds strictly applied.</span>
        </div>
        <div class="insights-list" id="insights-list">
          ${this.renderInsightsHtml(insights)}
        </div>
      </section>

      <!-- 5.3 Hero Overlay Chart -->
      <section class="overlay-chart-card card">
        <div class="card-header chart-header-row">
          <div>
            <h2 class="card-title">Overlay Timeline</h2>
            <div class="posture-band-legend">
              <span class="legend-dot" style="background:${POSTURE_COLORS.UPRIGHT}"></span> Upright
              <span class="legend-dot" style="background:${POSTURE_COLORS.WARNING}"></span> Warning
              <span class="legend-dot" style="background:${POSTURE_COLORS.ALERT}"></span> Alert
              <span class="legend-dot" style="background:${POSTURE_COLORS.SITTING}"></span> Sitting
            </div>
          </div>
          <div class="chart-toggles">
            <button class="toggle-pill ${this.visibleSeries.hr ? "active" : ""}" id="tog-hr">Heart Rate</button>
            <button class="toggle-pill ${this.visibleSeries.temp ? "active" : ""}" id="tog-temp">Air Temp</button>
            <button class="toggle-pill ${this.visibleSeries.hum ? "active" : ""}" id="tog-hum">Air Humidity</button>
            <button class="toggle-pill ${this.visibleSeries.pitch ? "active" : ""}" id="tog-pitch">Pitch</button>
            <button class="toggle-pill normalise-btn ${this.normalized ? "active" : ""}" id="tog-norm">Normalise (0–100%)</button>
          </div>
        </div>
        <div class="chart-wrapper hero-wrapper">
          <canvas id="hero-overlay-chart"></canvas>
        </div>
        <p class="chart-caption">Background shading indicates posture category severity. 5-second bucket aggregates.</p>
      </section>

      <!-- 5.4 Posture Comparison -->
      <section class="posture-comparison-card card">
        <div class="card-header">
          <h2 class="card-title">Vitals by Posture Category</h2>
          <span class="text-faint">Minimum 12 buckets (60s) required per group</span>
        </div>

        <!-- Stacked Time Share Bar -->
        <div class="time-share-container">
          <div class="time-share-bar">
            <div class="share-seg" style="width:${time_share.UPRIGHT || 0}%; background:${POSTURE_COLORS.UPRIGHT}" title="Upright: ${time_share.UPRIGHT}%"></div>
            <div class="share-seg" style="width:${time_share.WARNING || 0}%; background:${POSTURE_COLORS.WARNING}" title="Warning: ${time_share.WARNING}%"></div>
            <div class="share-seg" style="width:${time_share.ALERT || 0}%; background:${POSTURE_COLORS.ALERT}" title="Alert: ${time_share.ALERT}%"></div>
            <div class="share-seg" style="width:${time_share.SITTING || 0}%; background:${POSTURE_COLORS.SITTING}" title="Sitting: ${time_share.SITTING}%"></div>
          </div>
          <div class="time-share-labels">
            <span><span class="swatch" style="background:${POSTURE_COLORS.UPRIGHT}"></span> Upright ${time_share.UPRIGHT}%</span>
            <span><span class="swatch" style="background:${POSTURE_COLORS.WARNING}"></span> Warning ${time_share.WARNING}%</span>
            <span><span class="swatch" style="background:${POSTURE_COLORS.ALERT}"></span> Alert ${time_share.ALERT}%</span>
            <span><span class="swatch" style="background:${POSTURE_COLORS.SITTING}"></span> Sitting ${time_share.SITTING}%</span>
          </div>
        </div>

        <!-- Columns for each posture category -->
        <div class="posture-group-grid">
          ${this.renderPostureCategoryCard("UPRIGHT", by_posture.UPRIGHT, POSTURE_COLORS.UPRIGHT)}
          ${this.renderPostureCategoryCard("WARNING", by_posture.WARNING, POSTURE_COLORS.WARNING)}
          ${this.renderPostureCategoryCard("ALERT", by_posture.ALERT, POSTURE_COLORS.ALERT)}
          ${this.renderPostureCategoryCard("SITTING", by_posture.SITTING, POSTURE_COLORS.SITTING)}
        </div>
        <div class="card-caption">Differences between groups are descriptive. Small differences are within normal variation.</div>
      </section>

      <!-- 5.5 Bend Episode Impact -->
      <section class="episode-impact-card card">
        <div class="card-header">
          <h2 class="card-title">Bend Episode Impact</h2>
          <span class="summary-highlight">
            ${
              episode_impact.average && episode_impact.average.delta_during !== null
                ? `Average change during bends: <strong>${episode_impact.average.delta_during > 0 ? "+" : ""}${episode_impact.average.delta_during.toFixed(1)} bpm</strong> (n = ${episode_impact.average.n} episodes)`
                : `Not enough episodes (n = ${episode_impact.episodes_used}, need 3)`
            }
          </span>
        </div>

        <div class="episode-layout-grid">
          <div class="aligned-trace-col">
            <h3 class="subheading">Aligned Heart Rate Response (–60s to +60s)</h3>
            <div class="chart-wrapper trace-wrapper">
              <canvas id="aligned-trace-chart"></canvas>
            </div>
            <p class="chart-caption">Heart rate relative to pre-bend upright baseline. Red region indicates vibration delay window.</p>
          </div>

          <div class="episode-table-col">
            <h3 class="subheading">Recent Episodes (In Range)</h3>
            <div class="table-scroll">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Start</th>
                    <th>Dur</th>
                    <th>Max</th>
                    <th>Pitch</th>
                    <th>HR Bef</th>
                    <th>HR Dur</th>
                    <th>HR Aft</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  ${this.renderEpisodeRows(episode_impact.per_episode)}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <!-- 5.6 Relationships (Scatter Plots) -->
      <section class="relationships-card card">
        <div class="card-header">
          <h2 class="card-title">Relationships & Correlations</h2>
          <span class="text-faint">Pearson correlation r with non-zero variance guard (min n = 30)</span>
        </div>

        <div class="scatter-grid">
          <div class="scatter-cell card" id="scatter-pitch-hr">
            <h3 class="scatter-title">Trunk Pitch vs Heart Rate</h3>
            ${this.renderCorrelationBadge(correlations[0])}
            <div class="chart-wrapper scatter-wrapper"><canvas id="canvas-pitch-hr"></canvas></div>
          </div>

          <div class="scatter-cell card" id="scatter-bend-hr">
            <h3 class="scatter-title">Bend Duration vs Heart Rate</h3>
            ${this.renderCorrelationBadge(correlations[1])}
            <div class="chart-wrapper scatter-wrapper"><canvas id="canvas-bend-hr"></canvas></div>
          </div>

          <div class="scatter-cell card" id="scatter-temp-hr">
            <h3 class="scatter-title">Air Temperature vs Heart Rate</h3>
            ${this.renderCorrelationBadge(correlations[2])}
            <div class="chart-wrapper scatter-wrapper"><canvas id="canvas-temp-hr"></canvas></div>
          </div>

          <div class="scatter-cell card" id="scatter-hum-hr">
            <h3 class="scatter-title">Air Humidity vs Heart Rate</h3>
            ${this.renderCorrelationBadge(correlations[3])}
            <div class="chart-wrapper scatter-wrapper"><canvas id="canvas-hum-hr"></canvas></div>
          </div>
        </div>

        <!-- DHT11 Environmental Coupling Extra Row -->
        <div class="env-couple-row card">
          <div class="env-couple-header">
            <h3>Environment Coupling: Air Temp vs Air Humidity</h3>
            ${this.renderCorrelationBadge(correlations[4])}
          </div>
          <div class="chart-wrapper env-couple-wrapper"><canvas id="canvas-temp-hum"></canvas></div>
        </div>
      </section>
    `;

    // Wire chart toggle clicks
    this.setupChartControls();

    // Initialize all Chart.js instances
    this.initHeroChart(series);
    this.initAlignedChart(episode_impact.aligned_trace);
    this.initScatterCharts(series, correlations);
  }

  renderInsightsHtml(insights) {
    if (!insights || insights.length === 0) {
      return '<div class="insight-row insight-info"><span class="insight-icon">ℹ️</span><span>No insights available.</span></div>';
    }
    return insights
      .map(
        (ins) => `
        <div class="insight-row insight-${ins.level || "info"}">
          <span class="insight-icon">${ins.level === "warning" ? "⚠️" : "ℹ️"}</span>
          <span class="insight-text">${ins.text}</span>
          ${ins.n ? `<span class="insight-n">(n = ${ins.n})</span>` : ""}
        </div>
      `
      )
      .join("");
  }

  renderPostureCategoryCard(catName, stats, color) {
    if (!stats || !stats.buckets || stats.buckets < 12) {
      const n = stats && stats.buckets ? stats.buckets : 0;
      return `
        <div class="posture-cat-column" style="border-top: 3px solid ${color};">
          <div class="cat-header">
            <span class="cat-title" style="color: ${color}">${catName}</span>
            <span class="cat-time text-faint">${stats ? stats.seconds : 0}s</span>
          </div>
          <div class="cat-empty-msg">Not enough data (n = ${n}, need 12)</div>
        </div>
      `;
    }

    const hr = stats.hr;
    const temp = stats.temp;
    const hum = stats.hum;

    return `
      <div class="posture-cat-column" style="border-top: 3px solid ${color};">
        <div class="cat-header">
          <span class="cat-title" style="color: ${color}">${catName}</span>
          <span class="cat-time text-muted">${stats.seconds}s (${stats.buckets} buckets)</span>
        </div>

        <div class="metric-block">
          <div class="metric-name">Heart Rate</div>
          ${
            hr
              ? `
            <div class="metric-primary">${hr.mean.toFixed(1)} <span class="unit">bpm</span></div>
            <div class="metric-details">
              <span>med: ${hr.median.toFixed(1)}</span>
              <span>sd: ±${hr.sd.toFixed(1)}</span>
              <span>range: ${hr.min}–${hr.max}</span>
            </div>
            <div class="metric-n">n = ${hr.n} buckets</div>
          `
              : '<div class="metric-empty text-faint">No valid HR</div>'
          }
        </div>

        <div class="metric-block">
          <div class="metric-name">Air Temperature</div>
          ${
            temp
              ? `
            <div class="metric-primary">${temp.mean.toFixed(1)} <span class="unit">°C</span></div>
            <div class="metric-details">
              <span>med: ${temp.median.toFixed(1)}</span>
              <span>sd: ±${temp.sd.toFixed(1)}</span>
              <span>range: ${temp.min}–${temp.max}</span>
            </div>
            <div class="metric-n">n = ${temp.n} buckets</div>
          `
              : '<div class="metric-empty text-faint">No temp</div>'
          }
        </div>

        <div class="metric-block">
          <div class="metric-name">Air Humidity</div>
          ${
            hum
              ? `
            <div class="metric-primary">${hum.mean.toFixed(1)} <span class="unit">%RH</span></div>
            <div class="metric-details">
              <span>med: ${hum.median.toFixed(1)}</span>
              <span>sd: ±${hum.sd.toFixed(1)}</span>
              <span>range: ${hum.min}–${hum.max}</span>
            </div>
            <div class="metric-n">n = ${hum.n} buckets</div>
          `
              : '<div class="metric-empty text-faint">No hum</div>'
          }
        </div>
      </div>
    `;
  }

  renderEpisodeRows(episodes) {
    if (!episodes || episodes.length === 0) {
      return '<tr><td colspan="8" class="text-center text-faint">No closed bend episodes in this range</td></tr>';
    }
    return episodes
      .slice(0, 8)
      .map((ep) => {
        const timeStr = ep.start_ts ? new Date(ep.start_ts).toLocaleTimeString() : "—";
        const durSec = ep.duration_ms ? (ep.duration_ms / 1000).toFixed(1) + "s" : "—";
        const dDuring = ep.delta_during !== null && ep.delta_during !== undefined
          ? `${ep.delta_during > 0 ? "+" : ""}${ep.delta_during.toFixed(1)} bpm`
          : "—";

        const badgeColor = POSTURE_COLORS[ep.max_level] || "#8e9fb3";

        return `
          <tr>
            <td>${timeStr}</td>
            <td>${durSec}</td>
            <td><span class="badge" style="background:${badgeColor}; color:#000; font-size:0.75rem;">${ep.max_level}</span></td>
            <td>${ep.peak_pitch_deg ? ep.peak_pitch_deg.toFixed(1) + "°" : "—"}</td>
            <td>${ep.hr_before !== null ? ep.hr_before.toFixed(1) : "—"}</td>
            <td>${ep.hr_during !== null ? ep.hr_during.toFixed(1) : "—"}</td>
            <td>${ep.hr_after !== null ? ep.hr_after.toFixed(1) : "—"}</td>
            <td class="${ep.delta_during > 0 ? "highlight-delta" : ""}">${dDuring}</td>
          </tr>
        `;
      })
      .join("");
  }

  renderCorrelationBadge(corr) {
    if (!corr) return "";
    if (corr.r === null || corr.r === undefined) {
      return `<div class="corr-badge corr-none">⚠️ ${corr.reason || "Not enough data"}</div>`;
    }
    return `
      <div class="corr-badge corr-valid">
        <strong>r = ${corr.r.toFixed(2)}</strong> (${corr.strength}, ${corr.direction}, n = ${corr.n})
        ${corr.slope !== null ? `<small class="slope-text">slope: ${corr.slope.toFixed(2)}</small>` : ""}
      </div>
    `;
  }

  setupChartControls() {
    const bindToggle = (btnId, key) => {
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.addEventListener("click", () => {
          this.visibleSeries[key] = !this.visibleSeries[key];
          btn.classList.toggle("active", this.visibleSeries[key]);
          this.updateHeroChart();
        });
      }
    };

    bindToggle("tog-hr", "hr");
    bindToggle("tog-temp", "temp");
    bindToggle("tog-hum", "hum");
    bindToggle("tog-pitch", "pitch");

    const btnNorm = document.getElementById("tog-norm");
    if (btnNorm) {
      btnNorm.addEventListener("click", () => {
        this.normalized = !this.normalized;
        btnNorm.classList.toggle("active", this.normalized);
        this.updateHeroChart();
      });
    }
  }

  // --- Chart.js Rendering ---

  destroyCharts() {
    if (this.overlayChart) {
      this.overlayChart.destroy();
      this.overlayChart = null;
    }
    if (this.alignedChart) {
      this.alignedChart.destroy();
      this.alignedChart = null;
    }
    for (const key of Object.keys(this.scatterCharts)) {
      if (this.scatterCharts[key]) {
        this.scatterCharts[key].destroy();
      }
    }
    this.scatterCharts = {};
  }

  initHeroChart(series) {
    const canvas = document.getElementById("hero-overlay-chart");
    if (!canvas || !series || series.length === 0) return;

    // Posture background bands custom Chart.js plugin
    const postureBandsPlugin = {
      id: "postureBandsPlugin",
      beforeDraw: (chart) => {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea || !scales.x) return;

        const count = series.length;
        if (count === 0) return;

        ctx.save();
        for (let i = 0; i < count; i++) {
          const pt = series[i];
          if (!pt.cat) continue;

          const color = POSTURE_BG_COLORS[pt.cat];
          if (!color) continue;

          const xStart = scales.x.getPixelForValue(i === 0 ? 0 : i - 0.5);
          const xEnd = scales.x.getPixelForValue(i === count - 1 ? count - 1 : i + 0.5);
          const width = Math.max(1, xEnd - xStart);

          ctx.fillStyle = color;
          ctx.fillRect(xStart, chartArea.top, width, chartArea.bottom - chartArea.top);
        }
        ctx.restore();
      },
    };

    const labels = series.map((pt) => {
      const d = new Date(pt.t);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    });

    const datasets = this.buildHeroDatasets(series);

    this.overlayChart = new Chart(canvas, {
      type: "line",
      data: { labels, datasets },
      plugins: [postureBandsPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 300 },
        interaction: { mode: "index", intersect: false },
        scales: this.buildHeroScales(),
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "rgba(11, 16, 32, 0.95)",
            titleColor: "#f0f4f8",
            bodyColor: "#8e9fb3",
            borderColor: "rgba(255, 255, 255, 0.15)",
            borderWidth: 1,
            callbacks: {
              afterTitle: (items) => {
                if (!items.length) return "";
                const idx = items[0].dataIndex;
                const pt = series[idx];
                return `Posture: ${pt ? pt.cat : "—"}`;
              },
            },
          },
        },
      },
    });
  }

  buildHeroScales() {
    if (this.normalized) {
      return {
        x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#8e9fb3", maxTicksLimit: 10 } },
        y: {
          min: 0,
          max: 100,
          title: { display: true, text: "Normalised (0–100%)", color: "#8e9fb3" },
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#8e9fb3" },
        },
      };
    }

    return {
      x: { grid: { color: "rgba(255, 255, 255, 0.05)" }, ticks: { color: "#8e9fb3", maxTicksLimit: 10 } },
      yHR: {
        type: "linear",
        position: "left",
        display: this.visibleSeries.hr,
        title: { display: true, text: "Heart Rate (bpm)", color: "#ff4d5e" },
        grid: { color: "rgba(255, 255, 255, 0.05)" },
        ticks: { color: "#ff4d5e" },
      },
      yTemp: {
        type: "linear",
        position: "right",
        display: this.visibleSeries.temp,
        title: { display: true, text: "Air Temp (°C)", color: "#f5c542" },
        grid: { drawOnChartArea: false },
        ticks: { color: "#f5c542" },
      },
      yHum: {
        type: "linear",
        position: "right",
        display: this.visibleSeries.hum,
        title: { display: true, text: "Air Hum (%)", color: "#3498db" },
        grid: { drawOnChartArea: false },
        ticks: { color: "#3498db" },
      },
      yPitch: {
        type: "linear",
        position: "left",
        display: this.visibleSeries.pitch,
        title: { display: true, text: "Pitch (°)", color: "#2ecc71" },
        grid: { drawOnChartArea: false },
        ticks: { color: "#2ecc71" },
      },
    };
  }

  buildHeroDatasets(series) {
    const minMaxNorm = (vals) => {
      const valid = vals.filter((v) => v !== null && !isNaN(v));
      if (valid.length === 0) return vals;
      const min = Math.min(...valid);
      const max = Math.max(...valid);
      if (max - min === 0) return vals.map((v) => (v === null ? null : 50));
      return vals.map((v) => (v === null ? null : ((v - min) / (max - min)) * 100));
    };

    const rawHr = series.map((s) => s.hr);
    const rawTemp = series.map((s) => s.temp);
    const rawHum = series.map((s) => s.hum);
    const rawPitch = series.map((s) => s.pitch);

    const hrData = this.normalized ? minMaxNorm(rawHr) : rawHr;
    const tempData = this.normalized ? minMaxNorm(rawTemp) : rawTemp;
    const humData = this.normalized ? minMaxNorm(rawHum) : rawHum;
    const pitchData = this.normalized ? minMaxNorm(rawPitch) : rawPitch;

    return [
      {
        label: "Heart Rate",
        data: hrData,
        borderColor: "#ff4d5e",
        backgroundColor: "rgba(255, 77, 94, 0.1)",
        yAxisID: this.normalized ? "y" : "yHR",
        hidden: !this.visibleSeries.hr,
        spanGaps: false,
        pointRadius: 0,
        borderWidth: 2,
        tension: 0.15,
      },
      {
        label: "Air Temp",
        data: tempData,
        borderColor: "#f5c542",
        backgroundColor: "rgba(245, 197, 66, 0.1)",
        yAxisID: this.normalized ? "y" : "yTemp",
        hidden: !this.visibleSeries.temp,
        spanGaps: false,
        pointRadius: 0,
        borderWidth: 2,
        tension: 0.15,
      },
      {
        label: "Air Humidity",
        data: humData,
        borderColor: "#3498db",
        backgroundColor: "rgba(52, 152, 219, 0.1)",
        yAxisID: this.normalized ? "y" : "yHum",
        hidden: !this.visibleSeries.hum,
        spanGaps: false,
        pointRadius: 0,
        borderWidth: 2,
        tension: 0.15,
      },
      {
        label: "Trunk Pitch",
        data: pitchData,
        borderColor: "#2ecc71",
        backgroundColor: "rgba(46, 204, 113, 0.1)",
        yAxisID: this.normalized ? "y" : "yPitch",
        hidden: !this.visibleSeries.pitch,
        spanGaps: false,
        pointRadius: 0,
        borderWidth: 2,
        tension: 0.15,
      },
    ];
  }

  updateHeroChart() {
    if (!this.overlayChart || !this.data || !this.data.series) return;
    this.overlayChart.options.scales = this.buildHeroScales();
    this.overlayChart.data.datasets = this.buildHeroDatasets(this.data.series);
    this.overlayChart.update();
  }

  initAlignedChart(alignedTrace) {
    const canvas = document.getElementById("aligned-trace-chart");
    if (!canvas || !alignedTrace || !alignedTrace.offsets_s) return;

    const labels = alignedTrace.offsets_s.map((off) => `${off > 0 ? "+" : ""}${off}s`);
    const data = alignedTrace.hr_mean;

    // Draw shaded band for vibration onset delay (0 to 3s)
    const delayPlugin = {
      id: "delayPlugin",
      beforeDraw: (chart) => {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea || !scales.x) return;

        const zeroIdx = alignedTrace.offsets_s.indexOf(0);
        if (zeroIdx === -1) return;

        const xZero = scales.x.getPixelForValue(zeroIdx);
        const x3s = scales.x.getPixelForValue(zeroIdx + 1); // 0 to 5s bin

        ctx.save();
        ctx.fillStyle = "rgba(255, 77, 94, 0.15)";
        ctx.fillRect(xZero, chartArea.top, x3s - xZero, chartArea.bottom - chartArea.top);

        // Vertical reference line at 0s
        ctx.strokeStyle = "rgba(255, 77, 94, 0.7)";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(xZero, chartArea.top);
        ctx.lineTo(xZero, chartArea.bottom);
        ctx.stroke();
        ctx.restore();
      },
    };

    this.alignedChart = new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Δ Heart Rate (bpm)",
            data: data,
            borderColor: "#ff4d5e",
            backgroundColor: "rgba(255, 77, 94, 0.15)",
            borderWidth: 2.5,
            spanGaps: false,
            fill: true,
            pointRadius: 3,
            pointBackgroundColor: "#ff4d5e",
          },
        ],
      },
      plugins: [delayPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              afterBody: (items) => {
                if (!items.length) return "";
                const idx = items[0].dataIndex;
                const n = alignedTrace.n[idx];
                return n !== null ? `Episodes in bin: ${n}` : "Not enough data";
              },
            },
          },
        },
        scales: {
          x: {
            title: { display: true, text: "Offset from bend start (s)", color: "#8e9fb3" },
            grid: { color: "rgba(255, 255, 255, 0.05)" },
            ticks: { color: "#8e9fb3" },
          },
          y: {
            title: { display: true, text: "Δ BPM from baseline", color: "#8e9fb3" },
            grid: { color: "rgba(255, 255, 255, 0.05)" },
            ticks: { color: "#8e9fb3" },
          },
        },
      },
    });
  }

  initScatterCharts(series, correlations) {
    if (!series || !correlations) return;

    const configs = [
      { id: "canvas-pitch-hr", corrIdx: 0, xKey: "pitch", yKey: "hr", xLabel: "Pitch (°)", yLabel: "HR (bpm)" },
      { id: "canvas-bend-hr", corrIdx: 1, xKey: "bend_dur", yKey: "hr", xLabel: "Bend Dur (s)", yLabel: "HR (bpm)" },
      { id: "canvas-temp-hr", corrIdx: 2, xKey: "temp", yKey: "hr", xLabel: "Air Temp (°C)", yLabel: "HR (bpm)" },
      { id: "canvas-hum-hr", corrIdx: 3, xKey: "hum", yKey: "hr", xLabel: "Air Hum (%)", yLabel: "HR (bpm)" },
      { id: "canvas-temp-hum", corrIdx: 4, xKey: "temp", yKey: "hum", xLabel: "Air Temp (°C)", yLabel: "Air Hum (%)" },
    ];

    for (const cfg of configs) {
      const canvas = document.getElementById(cfg.id);
      if (!canvas) continue;

      const corr = correlations[cfg.corrIdx];
      const pts = [];

      for (const s of series) {
        let xVal = s[cfg.xKey];
        const yVal = s[cfg.yKey];

        // Specific handling for bend duration
        if (cfg.xKey === "bend_dur") {
          // If not bending, duration is 0 or null
          if (s.cat === "UPRIGHT" || s.cat === "SITTING") continue;
          xVal = s.bend_dur !== undefined ? s.bend_dur : 3.0; // fallback bucket approximation
        }

        if (xVal !== null && yVal !== null && !isNaN(xVal) && !isNaN(yVal)) {
          pts.push({
            x: xVal,
            y: yVal,
            cat: s.cat || "UPRIGHT",
          });
        }
      }

      // If no valid points or correlation couldn't be computed
      if (pts.length === 0) {
        const parent = canvas.parentElement;
        if (parent) {
          parent.innerHTML = `<div class="chart-empty-msg text-faint">${corr ? corr.reason : "No points available"}</div>`;
        }
        continue;
      }

      const pointColors = pts.map((p) => POSTURE_COLORS[p.cat] || "#8e9fb3");

      const datasets = [
        {
          type: "scatter",
          label: "Buckets",
          data: pts,
          pointBackgroundColor: pointColors,
          pointBorderColor: "rgba(0,0,0,0.3)",
          pointRadius: 3.5,
        },
      ];

      // Add fitted trendline if slope and intercept exist
      if (corr && corr.slope !== null && corr.intercept !== null) {
        const xVals = pts.map((p) => p.x);
        const minX = Math.min(...xVals);
        const maxX = Math.max(...xVals);
        datasets.push({
          type: "line",
          label: "Trendline",
          data: [
            { x: minX, y: corr.slope * minX + corr.intercept },
            { x: maxX, y: corr.slope * maxX + corr.intercept },
          ],
          borderColor: "#3498db",
          borderWidth: 2,
          pointRadius: 0,
          fill: false,
        });
      }

      this.scatterCharts[cfg.id] = new Chart(canvas, {
        data: { datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => `(${ctx.parsed.x.toFixed(1)}, ${ctx.parsed.y.toFixed(1)}) [${pts[ctx.dataIndex] ? pts[ctx.dataIndex].cat : ""}]`,
              },
            },
          },
          scales: {
            x: {
              type: "linear",
              title: { display: true, text: cfg.xLabel, color: "#8e9fb3" },
              grid: { color: "rgba(255, 255, 255, 0.05)" },
              ticks: { color: "#8e9fb3" },
            },
            y: {
              type: "linear",
              title: { display: true, text: cfg.yLabel, color: "#8e9fb3" },
              grid: { color: "rgba(255, 255, 255, 0.05)" },
              ticks: { color: "#8e9fb3" },
            },
          },
        },
      });
    }
  }
}
