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
- `--device-id`: Device identifier (default: `sim-vest-01`).
- `--effects` / `--no-effects`: Enable physiological HR & DHT11 kinematics (default: on).

The simulator receives commands from the server in real time:
- **Calibrate:** Enters `CALIBRATING` for 2 seconds, then arms the posture sensors.
- **Mute:** Silences alarms for the requested duration.
- **Actuator Test:** Runs 2-second bursts on the buzzer, vibration motor, or status LEDs.
- **Config:** Dynamically updates bend-on, bend-off, and timing thresholds.

---

## 4. Seeding Demo Data & Posture-Vitals Analysis

The platform features an **Analysis** page (`http://localhost:5000/#/analysis`) correlating posture state against heart rate, near-body air temperature, and humidity using 5-second bucket means, strict sample size transparency, and honest sensor limitation reporting.

### Seeding Synthetic History
To populate the database directly with realistic demo history:

```powershell
# Seed 120 minutes of physiological posture effects (sim-vest-01)
python tools/seed_demo_data.py --minutes 120 --effects --clear-sim

# Or seed control data without posture-heart rate effects
python tools/seed_demo_data.py --minutes 120 --no-effects --clear-sim
```

### Seeding Arguments
- `--minutes`: Minutes of history to generate ending at current timestamp (default: `120`).
- `--device-id`: Device ID tag (default: `sim-vest-01`, automatically triggers `SIMULATED DATA` banner).
- `--effects` / `--no-effects`: Simulate posture impact on vitals vs control independent series (default: `--effects`).
- `--seed`: Deterministic random number seed (default: `42`).
- `--clear-sim`: Clean existing rows for `sim-` devices before insertion.

### Opening the Analysis Dashboard
1. Start the backend (`python backend/app.py`).
2. Navigate to `http://localhost:5000/#/analysis` (or click **Analysis** in the top navigation bar).
3. Use the segmented range selector (`5 min`, `15 min`, `1 h`, `6 h`, `24 h`, `All`), toggle movement exclusion, inspect the hero overlay chart with posture bands, view the aligned trace during bends, and click **Export CSV** to download 5-second bucket aggregates.

---

## 4. Running Automated Tests

Run the test suite with `pytest`:
```powershell
python -m pytest backend/tests/ -v
```

---

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
