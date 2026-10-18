# Device Protocol Specification: Smart Posture T-Shirt (v2)

This document serves as the single source of truth for communication between the ESP32 Wearable Posture T-shirt and the Telemetry Backend Server.

---

## 1. Vest → Server: `POST /api/data`

- **HTTP Method:** `POST`
- **Path:** `/api/data`
- **Headers:**
  - `Content-Type: application/json`
  - `X-Device-Token: <token>` (Validated against server `VEST_DEVICE_TOKEN`; default `change-me`)
- **Frequency:** Sent approximately once per second (~1 Hz).
- **Null Handling:** Any sensor field can be `null` when the sensor has no valid reading. **`null` signifies "no data"; the server and UI must never convert `null` to `0`.**

### Payload Fields

| Field | Type | Description |
|---|---|---|
| `device_id` | string | Device identifier, e.g. `"vest-01"` |
| `fw` | string | Firmware version string, e.g. `"2.0.0"` |
| `uptime_s` | int | Device seconds elapsed since boot |
| `state` | string | One of: `UNCALIBRATED`, `CALIBRATING`, `FAULT`, `UPRIGHT`, `WARNING`, `ALERT` |
| `armed` | bool | `true` after a successful calibration this session; `false` otherwise |
| `muted` | bool | `true` if buzzer and vibration alerts are silenced |
| `is_standing` | bool | `true` = standing; `false` = sitting or lying down |
| `moving` | bool | `true` if wearer is moving (angles may be less reliable) |
| `bend_detected` | bool | `true` when confirmed forward bend (standing + pitch > threshold) |
| `possible_bend` | bool | `true` when only one bend sensor agrees (e.g. flex or IMU alone) |
| `bend_duration_ms` | int | Duration in milliseconds of the current confirmed bend |
| `imu_pitch_deg` | float \| null | Trunk forward pitch from calibrated upright. **Signed: positive = leaning forward, negative = leaning backward** |
| `imu_roll_deg` | float \| null | Sideways lean angle: positive = leaning right, negative = leaning left |
| `imu_says_bent` | bool | `true` if back-mounted IMU alone exceeds bend threshold |
| `flex_upper` | float \| null | Upper back flex change from baseline (ADC units); `null` if not fitted |
| `flex_lower` | float \| null | Lower back flex change from baseline (ADC units); `null` if not fitted |
| `flex_says_bent` | bool \| null | `true` if flex sensors alone detect bend; `null` if flex is not fitted |
| `adxl_tilt_deg` | float \| null | Thigh tilt from standing pose (~0° standing, ~90° sitting); `null` if fault |
| `vibration_active` | bool | `true` if vibration motor is currently enabled/pulsing |
| `buzzer_active` | bool | `true` if buzzer is currently enabled/pulsing |
| `led_green` | bool | `true` if green status LED is illuminated |
| `led_yellow` | bool | `true` if yellow status LED is illuminated |
| `led_red` | bool | `true` if red status LED is illuminated |
| `heart_rate_bpm` | int \| null | Heart rate in beats per minute; `null` if no valid reading or no finger |
| `finger_present` | bool | `true` if pulse sensor has skin contact |
| `temperature_c` | float \| null | Air temperature near the body in °C; `null` if sensor fault (label "Air temp" in UI) |
| `humidity_pct` | float \| null | Relative humidity near the body in %; `null` if sensor fault |
| `mpu_ok` | bool | `true` if MPU IMU sensor is communicating and healthy |
| `adxl_ok` | bool | `true` if ADXL345 thigh accelerometer is communicating and healthy |
| `max_ok` | bool | `true` if MAX30102/MAX30105 pulse sensor is communicating and healthy |
| `flex_enabled` | bool | `false` if flex sensors are not fitted / disabled |
| `bend_on_deg` | float | Configured angle threshold to trigger bend detection (degrees) |
| `bend_off_deg` | float | Configured hysteresis recovery angle threshold (degrees) |
| `vibrate_delay_s` | float | Configured continuous bend duration before vibration starts (seconds) |
| `buzzer_delay_s` | float | Configured continuous bend duration before buzzer starts (seconds) |
| `wifi_rssi` | int | Wi-Fi Received Signal Strength Indication (dBm) |

---

## 2. Server → Vest: Response to `POST /api/data`

- **Status Code:** `200 OK` or `201 Created`
- **Format:** JSON
- **One-Shot Command Delivery:** Commands are optional and delivered **exactly once**. Once returned in a response, the backend marks them as `sent`.

### Response Payload Schema

```json
{
  "status": "ok",
  "received_at": "2026-10-18T10:00:00+00:00",
  "commands": {
    "calibrate": true,
    "mute_s": 60,
    "test": "buzzer",
    "config": {
      "bend_on_deg": 20.0,
      "bend_off_deg": 15.0,
      "vibrate_delay_s": 5.0,
      "buzzer_delay_s": 15.0
    }
  }
}
```

### Command Specification & Rules
1. **Omission:** If no commands are pending for the device, the `"commands"` key must be omitted completely from the JSON response:
   ```json
   {
     "status": "ok",
     "received_at": "2026-10-18T10:00:00+00:00"
   }
   ```
2. **Merging Pending Commands:**
   - `calibrate`: `true` if any pending calibrate command exists.
   - `mute_s`: integer seconds from the latest mute command (`0` = un-mute).
   - `test`: latest test target (`"buzzer"`, `"vibration"`, or `"leds"`).
   - `config`: merged dictionary containing the latest value for each field (`bend_on_deg`, `bend_off_deg`, `vibrate_delay_s`, `buzzer_delay_s`).
3. **Threshold Validation Rules (enforced server-side when UI posts command):**
   - `bend_on_deg`: 5 to 60 degrees.
   - `bend_off_deg`: 2 to 58 degrees, and must satisfy: `bend_off_deg <= bend_on_deg - 2`.
   - `vibrate_delay_s`: 1 to 60 seconds.
   - `buzzer_delay_s`: 2 to 120 seconds, and must satisfy: `buzzer_delay_s > vibrate_delay_s`.
4. **Command Expiration:**
   - Any pending command not delivered within 60 seconds of creation is marked `expired` and discarded.
5. **Security / Authentication:**
   - Compare `X-Device-Token` header with `VEST_DEVICE_TOKEN` (default: `change-me`).
   - If missing or invalid, return `401 Unauthorized` (`{"error": "Unauthorized"}`) without recording data.

---

## 3. Server API: History and Alerts Endpoints

*Note: The hardware and ESP32 device wire protocol remains unchanged. The following REST endpoints serve the frontend web client.*

### History Endpoints:
- `GET /api/history/bounds`: Returns overall first and last timestamps, device list with simulated flags, and retention setting (`7` days).
- `GET /api/history/summary`: Accepts `from`, `to`, `device_id`, `tz_offset_minutes`. Returns monitored time, percent per category, slouch count, longest slouch, average heart rate, temperature, humidity, and session count. Returns `null` if fewer than 12 samples (< 60s) exist.
- `GET /api/history/timeline`: Returns downsampled series (max `max_points`, default 800) preserving highest severity category (`ALERT` > `WARNING` > `SITTING` > `UPRIGHT`), plus run-length-encoded `segments` list (`[{start, end, cat}]`). Never interpolates across gaps > 10s.
- `GET /api/history/days`: Returns one record per local day according to `tz_offset_minutes`, including monitored duration, percent good posture, slouch count, longest slouch, and average heart rate.
- `GET /api/sessions`: Continuous stretches of monitoring where reading gap <= `gap_s` (default 60). Newest first with `limit` and `offset`.
- `GET /api/history/readings`: Raw readings table paginated (`limit`, `offset`, `order`).
- `GET /api/history/export.csv`: CSV export of time range with both local time and UTC time columns (`resolution`: `auto`, `1`, `5`, `60`).

### Alerts Endpoints:
- `GET /api/episodes`: Extended with optional query parameters `from`, `to`, `level` (`WARNING`, `ALERT`, `BOTH`), `min_duration_s`, `order`, `limit`, `offset`. Returns backward-compatible plain array if called without search filters, or `{total, limit, offset, episodes}` when search parameters are present.
- `GET /api/episodes/search`: Explicit rich search endpoint returning `{total, limit, offset, episodes}`.
- `GET /api/episodes/<id>`: Returns single slouch episode with surrounding context series (60s before start to 60s after end), moments (`early_warning_s`, `alert_s`, `duration_s`), and whether alerts were muted.
- `GET /api/alerts/summary`: Aggregate slouch counts, total duration, longest slouch, average duration, slouches per local day, 24 hourly bins in local time, and most frequent hour of day.
- `GET /api/episodes/export.csv`: Filtered slouch episodes CSV.

