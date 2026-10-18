# Smart Posture T-Shirt (v2 Telemetry & Web Platform)

A wearable posture-monitoring system built with an ESP32 microcontroller, SQLite database, Flask REST API with Server-Sent Events (SSE), and a modern dark clinical-tech web dashboard.

---

## 1. Quick Start (Windows PowerShell)

### Prerequisites
- Python 3.10+ installed and available on PATH.
- Network access between your Windows laptop and the ESP32 (same Wi-Fi or mobile hotspot).

### Step 1: Set Up Python Virtual Environment
Open PowerShell in the project root:
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install runtime dependencies
pip install -r backend/requirements.txt

# (Optional) Install development and testing dependencies
pip install -r requirements-dev.txt
```

### Step 2: Start the Backend Server
```powershell
python backend/app.py
```
- By default, the server initializes a fresh SQLite database at `backend/vest_v2.db` in WAL mode.
- The server binds to `0.0.0.0:5000` (listening on all local network adapters).
- Open `http://localhost:5000` in your browser.

---

## 2. Connecting the Physical ESP32 Wearable

### Finding Your Laptop's Local IP Address
In PowerShell, run:
```powershell
ipconfig
```
Look for the **IPv4 Address** under your active Wi-Fi adapter (e.g. `192.168.1.105` or `10.84.42.215`).

### Firmware Configuration
In your ESP32 Arduino sketch (`firmware/antiStoopVest.ino`), set:
```c
const char *SERVER_URL = "http://<YOUR-LAPTOP-IP>:5000/api/data";
```
*Example:* `http://192.168.1.105:5000/api/data`

### Windows Firewall Configuration Note
If the ESP32 cannot reach your laptop (prints `HTTP error: connection refused` or times out):
1. Open **Windows Defender Firewall with Advanced Security**.
2. Click **Inbound Rules** → **New Rule**.
3. Choose **Port** → **TCP** → Specific local ports: `5000`.
4. Select **Allow the connection** and apply to **Private** networks.
5. Name it `Flask IoT Posture Port 5000` and save.

---

## 3. Running the Hardware Simulator

If the physical ESP32 is not powered on or available, use the built-in hardware simulator to demo all features:

```powershell
# Run full posture demo cycle (calibrate -> upright -> stoop alert -> recover -> sit)
python tools/simulate_vest.py --scenario demo

# Or run natural human idle sway
python tools/simulate_vest.py --scenario idle
```

### Available Simulator Arguments
- `--url`: Backend ingest URL (default: `http://localhost:5000/api/data`).
- `--token`: Device authentication token (default: `change-me`).
- `--interval`: Push interval in seconds (default: `1.0`).
- `--scenario`: Simulation scenario (`demo` or `idle`).
- `--device-id`: Device identifier (default: `vest-01`).

The simulator receives commands from the server in real time:
- **Calibrate:** Enters `CALIBRATING` for 2 seconds, then arms the posture sensors.
- **Mute:** Silences alarms for the requested duration.
- **Actuator Test:** Runs 2-second bursts on the buzzer, vibration motor, or status LEDs.
- **Config:** Dynamically updates bend-on, bend-off, and timing thresholds.

---

## 4. Seeding Demo Data

You can seed synthetic multi-day posture, physiological, and alert data directly into the SQLite database:

```powershell
# Seed 3 days of realistic daytime sessions with posture effects on heart rate
python tools/seed_demo_data.py --days 3 --effects --clear-sim

# Or seed a specific duration in minutes without posture effects (control data)
python tools/seed_demo_data.py --minutes 120 --no-effects --clear-sim
```

### Available Seed Arguments:
- `--days N`: Number of days of daytime monitoring sessions (default: 1).
- `--minutes N`: Total minutes of continuous recording (overrides `--days`).
- `--effects / --no-effects`: Simulate posture impact on heart rate.
- `--clear-sim`: Clean existing data for `sim-` devices before seeding.
- `--device-id`: Device ID to assign (default: `sim-vest-01`).

---

## 5. Web Platform Pages

- **Live View (`#/live`)**: Real-time biofeedback display, 3D body orientation visualizer, heart rate monitor, temperature & humidity, and bidirectional device command control (calibrate, mute, buzzer/vib test, angle thresholds).
- **Analysis (`#/analysis`)**: Posture versus heart rate, ambient temperature, and humidity correlation analysis with scatter plots, posture time-share, and event-aligned average response.
- **History (`#/history`)**: Historical monitoring review across custom ranges or presets (Today, Yesterday, Last 7 days, All available). Features a horizontal hero timeline strip with drag-to-zoom and vitals overlay, summary metrics, day-by-day aggregates, continuous monitoring sessions, paginated raw readings table, and CSV export.
- **Alerts (`#/alerts`)**: Log and audit of every posture warning and slouch alert. Features real-time live alert banner during ongoing slouches, summary cards, two charts (slouches by day and by hour of day in viewer local timezone), slouch log table, context drawer with [-60s .. +60s] surrounding readings chart and trigger moments, and CSV export.

---

## 6. Running Automated Tests

Run the test suite with `pytest`:
```powershell
python -m pytest backend/tests/ -v
```

## 5. Environment Variables

The backend supports configuration via environment variables:

| Variable | Description | Default |
|---|---|---|
| `VEST_DEVICE_TOKEN` | Required `X-Device-Token` header for ESP32 authentication | `change-me` |
| `VEST_DB_PATH` | SQLite database file location | `backend/vest_v2.db` |
| `VEST_PORT` | Port for the Flask HTTP and SSE server | `5000` |
| `VEST_DEBUG` | Flask debug mode (`1` for true, `0` for false) | `0` (off) |
| `VEST_RETENTION_DAYS` | Telemetry retention window (days) pruned on startup | `7` |

---

## 6. Project Architecture

- **`backend/`**: Flask service running SQLite WAL mode, SSE streaming queue, bi-directional command dispatch, and bend episode lifecycle tracking.
  - `app.py`: Entrypoint and HTTP routing.
  - `db.py`: SQLite connection, WAL pragmas, retention pruning.
  - `commands.py`: Merging, expiration (>60s), and one-shot delivery logic.
  - `episodes.py`: Automatic bend episode tracking and duration calculation.
  - `models.py`: Strict command validation and telemetry sanitization.
  - `sse.py`: Thread-safe Server-Sent Events pub/sub broadcaster.
  - `tests/`: Pytest unit test suite.
- **`web/`**: Zero-build vanilla HTML5, CSS3, and ES modules. Completely offline-capable (vendored Chart.js).
  - `index.html`: Main application shell with hash router (`#/live`).
  - `css/styles.css`: Dark clinical-tech theme matching shirt LEDs.
  - `js/`: Modular reactive client architecture (`api.js`, `store.js`, `views/live.js`, `components/*.js`).
  - `vendor/`: Vendored Chart.js 4.4.1 UMD minified library.
- **`tools/`**: `simulate_vest.py` hardware kinematics simulator.
- **`docs/`**: `PROTOCOL.md` (device communication protocol), `DECISIONS.md` (technical choices), `TESTING.md` (manual verification checklist).
- **`dashboard/`**: Legacy Streamlit dashboard (preserved untouched).
- **`firmware/`**: ESP32 Arduino sketch (preserved untouched).
