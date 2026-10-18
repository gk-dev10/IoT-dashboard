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

## 4. Analysis Page Manual Testing Checklist (`#/analysis`)

### State 1: Seeded Data Demonstration
- **Command:**
  ```powershell
  python tools/seed_demo_data.py --minutes 120 --device-id sim-vest-01 --effects --clear-sim
  ```
- **Verification:**
  1. Navigate to `http://localhost:5000/#/analysis`.
  2. Prominent amber `SIMULATED DATA` banner is displayed.
  3. Quality strip shows coverage percentages and bucket count.
  4. Overlay timeline chart displays with tinted posture background bands (Upright green, Warning yellow, Alert red, Sitting blue).
  5. Vitals by Posture Category shows sample sizes `n` for every metric.
  6. Aligned heart rate trace rises after t = 0 during bends.
  7. Automated observations report higher heart rate during bends and changes in temperature.

### State 2: Control Dataset (No Effects)
- **Command:**
  ```powershell
  python tools/seed_demo_data.py --minutes 120 --device-id sim-control --no-effects --clear-sim
  ```
- **Verification:**
  1. Open `http://localhost:5000/#/analysis`.
  2. Observations report *"No clear heart-rate difference between bending and upright"* (< 3 bpm difference).
  3. No posture-to-HR correlation reaches `moderate` (|r| < 0.30).

### State 3: Empty Database / No Telemetry in Range
- **Command:**
  ```powershell
  python -c "import sqlite3; conn = sqlite3.connect('backend/vest_v2.db'); conn.execute('DELETE FROM telemetry'); conn.execute('DELETE FROM episodes'); conn.commit()"
  ```
- **Verification:**
  1. Open `http://localhost:5000/#/analysis`.
  2. Buckets analyzed shows `0`.
  3. Category columns render *"Not enough data (n = 0, need 12)"*.
  4. Insights display fallback: *"Not enough data to draw conclusions yet"*.
  5. No JavaScript errors or NaN values in browser console.

### State 4: Patchy / All-Null Heart Rate
- **Verification:**
  1. When heart rate coverage is under 50 %, a warning chip appears in the quality strip: *"Heart-rate signal is patchy — results are unreliable"*.
  2. An automated insight with level `warning` is displayed first.

### State 5: Constant Values Guard
- **Verification:**
  1. If temperature or heart rate is constant, Pearson correlation does not throw division-by-zero errors.
  2. Scatter plot displays the reason badge: *"No variation in X variable"*.

### State 6: Interactive Controls & Offline Export
- **Verification:**
  1. Click **Range selector** buttons (`5 min`, `15 min`, `1 h`, `6 h`, `24 h`, `All`); data refreshes cleanly.
  2. Toggle **Exclude moving samples (HR)**; heart rate statistics recalculate without page flicker.
  3. Click **Pause / Resume** auto-refresh; ticker halts and resumes.
  4. Click **Export CSV**; browser downloads 5-second bucket CSV file with header.
  5. Click **"How to read this"**; drawer opens on the right side detailing DHT11 and optical sensor limitations.

