# Posture T-Shirt v2 — Manual Testing & State Verification Checklist

This document details the test procedures, commands, and verification criteria for every state defined in Section 5.4 of the specification.

---

## 1. Automated Test Suite

Run pytest in the repository root:
```powershell
python -m pytest backend/tests/ -v
```
All 9 unit tests verify:
- Health check endpoint
- Token rejection (`X-Device-Token` validation)
- Ingest with null preservation (no conversion to 0)
- Command validation acceptance & rejection ranges
- One-shot command delivery and merging
- 60-second command expiration
- Episode opening, severity escalation, peak pitch tracking, and closing
- History downsampling
- 24-hour aggregate stats calculations

---

## 2. Manual Frontend State Verification Checklist

Before starting, ensure the backend is running:
```powershell
python backend/app.py
```
Open your browser to `http://localhost:5000`.

### State 1: Empty Database / Waiting Screen
- **Condition:** Database initialized with zero telemetry rows (e.g. fresh `vest_v2.db`).
- **Expected UI Behavior:**
  - A friendly amber banner appears: *"Waiting for Posture T-Shirt Telemetry…"*.
  - Connection pill displays `WAITING FOR VEST…`.
  - Content grid is dimmed and non-interactive until the first payload arrives.

### State 2: Wearable Offline
- **Trigger:** Start simulator, let it post 2 samples, then terminate with `Ctrl+C`.
- **Expected UI Behavior:**
  - Within 5 to 6 seconds, connection pill turns grey: `OFFLINE — last seen X s ago`.
  - Hero state card switches to *"Wearable Offline — No data received within the last 5 seconds."*
  - Controls panel displays amber warning: *"Vest offline — queued commands expire in 60s"*.
  - Body figure and actuators dim to neutral grey.
- **Recovery:** Restart simulator; page resumes `LIVE` status within 1 to 2 seconds.

### State 3: UNCALIBRATED
- **Trigger:** Launch simulator in `idle` mode before calibration:
  ```powershell
  python tools/simulate_vest.py --scenario idle
  ```
  *(In `idle` mode, vest starts with `armed: false` and `state: UNCALIBRATED`).*
- **Expected UI Behavior:**
  - Top bar displays neutral badge: `NOT CALIBRATED`.
  - Hero card displays: *"Needs Calibration — Vest must be calibrated in an upright stance before monitoring."* with neutral grey glow.
  - Body figure shows neutral grey spine.

### State 4: CALIBRATING
- **Trigger:** Click the **"Calibrate Vest"** button in the Control Panel.
- **Expected UI Behavior:**
  - Button shows pending state: *"Sending command…"*.
  - Simulator receives `"calibrate": true` and enters `CALIBRATING` for 2 seconds.
  - Hero card updates to: *"Calibrating… Please stand upright and keep completely still."* with an hourglass icon.
  - Control panel confirms: *"Vest is calibrating… keep still"*.
  - After 2 seconds, state transitions to `UPRIGHT` and control panel displays *"Calibration complete!"*.

### State 5: UPRIGHT (Good Posture)
- **Trigger:** Simulator in upright stance (pitch ~2–6°, standing `true`):
  ```powershell
  python tools/simulate_vest.py --scenario idle
  ```
- **Expected UI Behavior:**
  - Hero card displays vibrant green glow: *"Good Posture — Spine aligned within healthy ergonomics."*
  - Body figure stands vertical with green spine.
  - Wearable mirror shows green OK bulb illuminated; yellow and red bulbs off.
  - Bend timer ring remains calm (0.0s elapsed).
  - Actuators (motor and buzzer) show `IDLE`.

### State 6: WARNING (Tier 1 Alert)
- **Trigger:** Run the demo scenario:
  ```powershell
  python tools/simulate_vest.py --scenario demo
  ```
  Wait until elapsed cycle hits t = 28s (continuous forward bend for >= 5s).
- **Expected UI Behavior:**
  - Hero card pulses amber: *"Early Warning — Forward bend detected for > 5s. Vibration active."*
  - Bend timer ring advances past 5.0s, turning amber with `TIER 1 WARNING` badge.
  - Wearable mirror: Yellow WARN bulb turns on, vibration motor animates with shaking wave brackets and status `PULSING`.
  - Body figure tilts forward at ~24–28° with amber spine.
  - Live pitch chart traces line crossing above the 20° dashed threshold.

### State 7: ALERT (Tier 2 Alert)
- **Trigger:** Continue running demo scenario until t = 38s (continuous forward bend for >= 15s).
- **Expected UI Behavior:**
  - Hero card pulses red: *"ALERT — Straighten Up — Stoop persisted for > 15s. Buzzer & motor active."*
  - Bend timer ring reaches 15.0s, turning red with `TIER 2 ALERT` badge.
  - Wearable mirror: Red ALERT bulb turns on, buzzer icon animates with sound waves (`ALARMING`), vibration motor continues pulsing.
  - Recent Episodes table updates showing an active stoop episode with `ALERT` severity.

### State 8: SITTING / LYING
- **Trigger:** Demo scenario cycle t = 45s to 60s (sitting posture):
  - `is_standing: false`, `adxl_tilt_deg: ~84°`, pitch ~7°.
- **Expected UI Behavior:**
  - Body figure shows thigh horizontally aligned (90°) and a subtle chair silhouette appears behind the silhouette.
  - Sensor health strip shows *"Posture Pose: Sitting / Lying"*.
  - If user leans forward while sitting, system flags `possible_bend: true`, but does NOT trigger stoop alert (stoop alert requires standing).

### State 9: MUTED
- **Trigger:** Click **"Mute 1 min"** button on the Control Panel during a bend.
- **Expected UI Behavior:**
  - Simulator receives `"mute_s": 60`.
  - Top bar displays amber `MUTED` pill.
  - In Control Panel: *"Current state: MUTED (Alerts silenced)"*.
  - Even during WARNING or ALERT, motor and buzzer actuators stay silent/inactive on the shirt.
  - Clicking **"Un-mute"** immediately restores live alerts.

### State 10: Null Values Everywhere
- **Trigger:** Post a minimal payload containing null sensor fields:
  ```powershell
  python -c "import requests; requests.post('http://localhost:5000/api/data', headers={'X-Device-Token':'change-me'}, json={'device_id':'vest-01','state':'UPRIGHT','imu_pitch_deg':None,'heart_rate_bpm':None,'temperature_c':None,'humidity_pct':None,'flex_upper':None})"
  ```
- **Expected UI Behavior:**
  - Page renders without throwing JavaScript exceptions.
  - Heart rate displays `—` and `No signal`.
  - Air temperature and humidity display `—`.
  - Body figure renders upright with `—°` readout.
  - Flex sensor diagnostics show `Not fitted` or `—`.

---

## 3. Remote Control Verification (Two-Way Communication)

1. **Threshold Configuration:**
   - In Control Panel, adjust Bend-On slider to `25°`, Bend-Off to `20°`, Vibrate Delay to `4s`, Buzzer Delay to `12s`.
   - Click **"Apply Changes"**.
   - UI status shows *"Sent, waiting for the vest…"*.
   - Simulator console prints:
     `[COMMAND RECEIVED] config: {'bend_on_deg': 25.0, 'bend_off_deg': 20.0, 'vibrate_delay_s': 4.0, 'buzzer_delay_s': 12.0}`
   - On the very next upload, the UI confirms *"Applied successfully!"*.
   - Live pitch chart horizontal dashed lines shift to 25° and 20°.
2. **Actuator Burst Test:**
   - Click **"Test Buzzer"**. Button disables for 2.5s. Simulator prints `[COMMAND RECEIVED] test: buzzer` and activates buzzer for 2s.
   - Click **"Test Vibration"**. Simulator activates vibration for 2s.
   - Click **"Test LEDs"**. Simulator lights green, yellow, and red LEDs for 2s.

---

## 4. History Page (`#/history`) Manual Checklist

Seed multi-day demo data first:
```powershell
python tools/seed_demo_data.py --days 3 --effects --clear-sim
```
Open `http://localhost:5000/#/history`:

1. **Range Pills & Custom Picker:**
   - Click **"Today"**, **"Yesterday"**, **"Last 7 days"**, **"All available"**. URL hash updates (`#/history?from=...&to=...`).
   - Pick dates with the `datetime-local` inputs and click **"Apply"**. Range reloads accordingly.
   - Refresh page: selected range persists from the URL hash.
2. **Simulated Data Banner:**
   - If device is `sim-vest-01`, yellow `SIMULATED DATA` banner is visible.
3. **Summary Metric Cards:**
   - Cards display: *Monitored time*, *Good posture (while standing)*, *Slouches*, *Longest slouch*, *Time sitting*, *Average heart rate*.
   - Good posture is UPRIGHT seconds ÷ (UPRIGHT + WARNING + ALERT seconds); sitting is shown separately. The value is unavailable (`null`) when standing time is under 60 seconds.
   - If range has < 12 samples, cards display *"Not enough data yet"*.
4. **Posture Timeline Canvas:**
   - Color-coded horizontal strip renders run-length-encoded segments (green upright, blue-grey sitting, yellow warning, red alert).
   - Hovering displays timestamp and category in a tooltip.
   - Click and drag across a section: zooms in; *"Reset zoom"* button appears and restores the range when clicked.
   - Toggle **"Show vitals"**: displays time-aligned lean angle, heart rate, and temperature line chart directly underneath.
5. **Day by Day Breakdown:**
   - List of cards per calendar day with date, duration, posture proportion bar, slouch count, longest slouch, and average heart rate.
   - Clicking a day sets the active range to that day.
6. **Monitoring Sessions:**
   - List of sessions split by gaps > 60s.
   - Clicking a session card zooms the range to that session.
7. **Raw Telemetry Table:**
   - Click **"Show raw readings"** to expand table.
   - Toggle order (`ASC`/`DESC`).
   - Click pagination (`‹` / `›`).
   - Toggle **"Show technical sensor columns"** to view side lean, thigh tilt, and sensor flags.
8. **CSV Download:**
   - Click **"Download CSV"**: downloads `posture_history_sim-vest-01.csv` with both local and UTC time columns.

---

## 5. Alerts Page (`#/alerts`) Manual Checklist

Open `http://localhost:5000/#/alerts`:

1. **Live Alert Banner:**
   - Start the simulator in demo mode: `python tools/simulate_vest.py --scenario demo`.
   - When a bend begins (warning / alert), top banner appears: *"Alert in progress — leaning forward for X s"*.
   - When posture returns to upright, banner disappears without full page reload.
2. **Filter Controls:**
   - Filter by Level (**"All levels"**, **"Early warnings"**, **"Alerts"**).
   - Filter by Minimum Length (**"Any length"**, **"≥ 10s"**, **"≥ 30s"**, **"≥ 60s"**).
   - Slouch log updates in place.
3. **Summary Cards & Charts:**
   - Displays *Total Slouches*, *Early warnings*, *Alerts*, *Longest slouch*, *Average length*, *Most common time* (e.g. "3 pm to 4 pm").
   - *Slouches by day* (stacked bar chart) and *Slouches by hour of day* (24 local hourly bins) render cleanly.
4. **Slouch Log & Detail Modal:**
   - List shows local start time, length, level pill, peak lean angle, and Details button.
   - Click any slouch row: modal opens displaying:
     - Moments timeline (`0s started`, `+5s early warning`, `+15s alert`, `+Xs ended`).
     - Mini chart spanning 60s before start to 60s after end with threshold lines and heart rate axis.
     - Technical details collapsible expander.
   - Close button or clicking overlay closes modal.
5. **Unseen Alerts Badge:**
   - Nav bar `Alerts` tab shows a red counter badge when new slouches have completed since the last visit.
   - Opening `#/alerts` clears the badge and stores the timestamp in `localStorage`.
6. **CSV Download:**
   - Click **"Download CSV"**: downloads filtered slouch records.

