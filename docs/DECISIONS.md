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

---

## 5. Analysis Engine & Honesty Rules Architecture
- **5-Second Bucket Aggregation:** 1 Hz telemetry samples exhibit intense autocorrelation. Treating individual 1 Hz samples as independent data points would artificially inflate degrees of freedom and overstate statistical confidence. Bucketing into 5-second intervals provides biologically and kinematically reasonable independence while preserving episode onset resolution.
- **Bucket Severity Precedence:** When assigning the single posture category to a 5-second bucket, the highest severity state takes precedence (`ALERT` > `WARNING` > `SITTING` > `UPRIGHT`). If an alert was triggered during any fraction of the 5-second window, the bucket reflects the alert rather than masking it.
- **Sample Size (n) Transparency:** Sample size `n` is displayed alongside every single statistic, metric, and automated insight. Summaries and differences are never shown in isolation.
- **Minimum Data Thresholds:**
  - `MIN_BUCKETS_PER_GROUP = 12`: At least 12 valid buckets (~1 minute) are required before a posture category displays mean, median, SD, or min–max. Below this threshold, the UI explicitly renders "Not enough data (n = X, need 12)".
  - `MIN_BUCKETS_CORR = 30`: At least 30 buckets are required to compute Pearson r and fit a linear trendline.
  - `MIN_HR_SAMPLES_WINDOW = 5`: Windows for before/during/after episode impact require at least 5 valid samples; otherwise the episode is omitted.
- **Why No p-values or Confidence Intervals:** Demonstrations of student IoT hardware should never create an illusion of clinical certainty. Sensor noise, motion artifacts, subject habituation, and calibration drift make classical inferential p-values misleading and scientifically dubious. The dashboard reports descriptive statistics (mean, median, SD, min–max, sample count) and Pearson r with qualitative effect sizes.
- **Zero-Causal Language:** Insights strictly use associative phrasing ("tended to", "moved together with", "averaged X bpm while..."). Words like "caused", "because of", and "due to" are forbidden in system-generated text. Every insight view includes the reminder: *"Correlation is not causation."*
- **SIMULATED DATA Banner:** Any device whose ID starts with `sim-` triggers a prominent yellow warning banner on the page to prevent synthetic demonstration datasets from being mistaken for real physiological measurements.
- **Variance Guard on Pearson Correlation:** To prevent `ZeroDivisionError` or invalid `NaN`/`Infinity` in JSON payloads, the Pearson correlation function checks sample variance. If either X or Y variance is ≤ 1e-9 (e.g. constant temperature or flat posture), `r` is returned as `null` with an explanatory reason string.

