# Architectural Decisions & Technical Choices

This document records technical decisions and trade-offs made during the implementation of the Posture T-Shirt v2 telemetry platform.

---

## 1. Storage & Database Design
- **Engine:** SQLite 3 in WAL (`Write-Ahead Logging`) mode with foreign keys enabled (`PRAGMA foreign_keys = ON;`). WAL mode enables simultaneous readers while the 1 Hz ingest writer operates.
- **Database File:** `backend/vest_v2.db` by default (leaving legacy `backend/vest_data.db` untouched).
- **Timezone Awareness:** All server timestamps generated using Python 3's `datetime.now(timezone.utc).isoformat()` (ISO-8601 with timezone offset `+00:00` or `Z`).
- **Telemetry Table:** Contains columns for each protocol field. Null values are stored as SQL `NULL` and serialized to JSON `null`.
- **Episodes Tracking:** An episode is opened whenever `state` in incoming telemetry transitions to `WARNING` or `ALERT`. If an episode is open:
  - `max_level` is escalated if `state == 'ALERT'` (`ALERT` > `WARNING`).
  - `peak_pitch_deg` is updated whenever `imu_pitch_deg` exceeds the previous peak.
  - The episode is closed (`end_ts` and `duration_ms` calculated) when `state` returns to `UPRIGHT`, `UNCALIBRATED`, `CALIBRATING`, `FAULT`, or when no telemetry arrives for >= 10 seconds.
- **Retention Pruning:** At backend startup, records in `telemetry` older than `VEST_RETENTION_DAYS` (default: 7 days) are deleted via `DELETE FROM telemetry WHERE ts < datetime('now', '-N days')`.

## 2. Server-Sent Events (SSE) Pub/Sub Architecture
- **In-Memory Pub/Sub:** A thread-safe `SSEManager` maintains a `queue.Queue(maxsize=100)` per connected SSE subscriber.
- **Events:**
  - `event: telemetry`: Broadcast on each valid ingest with the full live payload (latest telemetry, online flag, seconds_since_last, last 5 commands).
  - `event: command`: Broadcast whenever a command is queued, delivered, or expired.
  - `: heartbeat\n\n`: Sent every 15 seconds to prevent browser or proxy timeouts.
- **Client Disconnect Handling:** Generator checks for client disconnection and unregisters the queue automatically to prevent memory leaks. Flask runs with `threaded=True`.

## 3. Frontend Architecture
- **Zero-Build Vanilla Stack:** HTML5, CSS3, ES modules (`import`/`export`).
- **No External CDN Dependencies:** The app must run completely offline on a laptop. Chart.js is vendored locally into `web/vendor/chart.umd.min.js`.
- **Hash-Based Router:** Lightweight client-side router (`#/live`, `#/history`, `#/alerts`). Currently, `#/live` is the primary view; `#/history` and `#/alerts` are presented in navigation with "soon" badges.
- **Resilience:** Connects to `/api/stream`. If two consecutive SSE connection failures occur, the client gracefully falls back to polling `GET /api/live` every 1,000 ms until SSE reconnects.
- **Human Factor & Accessibility:** Visual representation with an interactive SVG side-view silhouette, 3 LED indicators matching physical hardware (green, yellow, red), animated buzzer soundwaves and vibrating motor glyphs, and high-contrast projection-ready typography.

## 4. Backward Compatibility
- Route `/` serves `web/index.html`.
- Static files under `web/` served at root or `/static/` as appropriate.
- Old endpoints (`/api/status`, `/api/history`, `/api/stats`, `/api/alerts`) are preserved with lightweight adapters querying the new database so existing integrations or tools remain functional where possible.
