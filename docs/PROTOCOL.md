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
