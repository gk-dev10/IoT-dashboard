/**
 * Smart Posture T-Shirt v2 — Recent Bend Episodes Table Component.
 * Displays recent stooping episodes with peak pitch, severity, and duration.
 */

export class EpisodesTableComponent {
  constructor(container) {
    this.container = container;
    this.renderInitial();
  }

  renderInitial() {
    this.container.innerHTML = `
      <div class="episodes-card">
        <div class="card-title">Recent Stoop Episodes Log</div>
        <div class="table-responsive">
          <table class="episodes-table">
            <thead>
              <tr>
                <th>Start Time (UTC)</th>
                <th>Duration</th>
                <th>Severity Level</th>
                <th>Peak Pitch</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody id="episodes-tbody">
              <tr><td colspan="5" class="table-empty">No stoop episodes recorded yet.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    `;

    this.tbody = document.getElementById("episodes-tbody");
  }

  update(episodes) {
    if (!Array.isArray(episodes) || episodes.length === 0) {
      this.tbody.innerHTML = `<tr><td colspan="5" class="table-empty">No stoop episodes recorded yet.</td></tr>`;
      return;
    }

    const rowsHtml = episodes
      .slice(0, 5)
      .map((ep) => {
        const timeStr = ep.start_ts ? ep.start_ts.substring(11, 19) : "—";
        const durSec = ep.duration_ms ? (ep.duration_ms / 1000.0).toFixed(1) + " s" : "—";
        const peakPitch =
          ep.peak_pitch_deg !== null ? `${ep.peak_pitch_deg.toFixed(1)}°` : "—";
        const isClosed = Boolean(ep.end_ts);
        const level = ep.max_level || "WARNING";

        const badgeClass = level === "ALERT" ? "badge-alert" : "badge-warning";
        const statusBadge = isClosed
          ? `<span class="badge badge-neutral">Closed</span>`
          : `<span class="badge badge-alert pulse-subtle">ACTIVE</span>`;

        return `
          <tr>
            <td><strong>${timeStr}</strong></td>
            <td>${durSec}</td>
            <td><span class="badge ${badgeClass}">${level}</span></td>
            <td>${peakPitch}</td>
            <td>${statusBadge}</td>
          </tr>
        `;
      })
      .join("");

    this.tbody.innerHTML = rowsHtml;
  }
}
