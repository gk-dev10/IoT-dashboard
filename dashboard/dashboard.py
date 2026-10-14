
"""
Smart Anti-Stoop Vest — Streamlit Dashboard
=============================================
Displays live posture, sensor-specific readings, physiological data,
statistics, historical charts, and alerts.

The dashboard reads data exclusively from the Flask API.

Run from the dashboard/ folder:
    pip install -r requirements.txt
    streamlit run dashboard.py

Flask must already be running at http://localhost:5000
or at the URL configured through VEST_API_URL.
"""

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_API = os.environ.get(
    "VEST_API_URL",
    "http://localhost:5000",
)

st.set_page_config(
    page_title="Smart Anti-Stoop Vest",
    page_icon="🧍",
    layout="wide",
)

# ---------------- Sidebar ----------------

st.sidebar.title("Settings")

api_url = st.sidebar.text_input(
    "Flask API URL",
    DEFAULT_API,
).rstrip("/")

refresh_s = st.sidebar.slider(
    "Auto-refresh (seconds)",
    min_value=2,
    max_value=30,
    value=5,
)

history_n = st.sidebar.slider(
    "History points to plot",
    min_value=20,
    max_value=300,
    value=60,
)

st_autorefresh(
    interval=refresh_s * 1000,
    key="auto_refresh",
)


# ============================================================
# API HELPERS
# ============================================================

def api_get(path, **params):
    """GET JSON from Flask. Return None if the request fails."""
    try:
        response = requests.get(
            f"{api_url}{path}",
            params=params,
            timeout=3,
        )
        response.raise_for_status()
        return response.json()

    except (requests.RequestException, ValueError):
        return None


def flatten_dict(data, prefix=""):
    """Flatten nested dictionaries into dotted field names."""
    result = {}

    if not isinstance(data, dict):
        return result

    for key, value in data.items():
        field = f"{prefix}.{key}" if prefix else str(key)

        if isinstance(value, dict):
            if value:
                result.update(flatten_dict(value, field))
            else:
                result[field] = {}

        else:
            result[field] = value

    return result


def collect_fields(data):
    """
    Collect fields from flat or nested API responses.

    Supports structures such as:
        {
            "flex_upper": 10,
            "posture": {"bend_detected": False},
            "vitals": {"heart_rate_bpm": 75}
        }
    """
    result = {}

    if not isinstance(data, dict):
        return result

    for key, value in data.items():
        if isinstance(value, dict):
            nested = collect_fields(value)

            for nested_key, nested_value in nested.items():
                result[nested_key] = nested_value

                # Preserve the full path when keys are nested.
                result[f"{key}.{nested_key}"] = nested_value

        elif isinstance(value, list):
            result[key] = value

        else:
            result[key] = value

    return result


def get_field(data, field, default=None):
    """
    Find a field in flat or nested data.

    Supports exact names and dotted paths.
    """
    if not isinstance(data, dict):
        return default

    if field in data:
        return data[field]

    current = data

    for part in field.split("."):
        if not isinstance(current, dict) or part not in current:
            current = None
            break

        current = current[part]

    if current is not None:
        return current

    # Also search nested dictionaries for an unqualified field name.
    for value in data.values():
        if isinstance(value, dict):
            found = get_field(value, field, None)

            if found is not None:
                return found

    return default


def show_value(value, unit="", decimals=None):
    """Format sensor values without displaying misleading zeroes as missing."""
    if value is None:
        return "—"

    if isinstance(value, bool):
        return "Yes" if value else "No"

    if isinstance(value, (int, float)):
        if decimals is not None:
            return f"{value:.{decimals}f}{unit}"

        return f"{value}{unit}"

    return str(value)


def show_sensor_card(container, label, value, unit="", decimals=None):
    """Render one sensor reading as a metric card."""
    container.metric(
        label,
        show_value(value, unit, decimals),
    )


def display_all_fields(data, title="Received Data"):
    """Display all returned fields in a readable table."""
    st.markdown(f"**{title}**")

    if data is None:
        st.info("No data available.")
        return

    if isinstance(data, dict):
        if not data:
            st.info("No fields returned.")
            return

        rows = []

        for field, value in flatten_dict(data).items():
            if isinstance(value, list):
                display_value = str(value)
            elif value is None:
                display_value = "N/A"
            else:
                display_value = str(value)

            rows.append({
                "Field": field,
                "Value": display_value,
            })

        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )

    elif isinstance(data, list):
        if not data:
            st.info("No records available.")
            return

        if all(isinstance(item, dict) for item in data):
            frame = pd.json_normalize(data, sep=".")
        else:
            frame = pd.DataFrame({"Value": data})

        st.dataframe(
            frame,
            use_container_width=True,
            hide_index=True,
        )

    else:
        st.write(data)


# ============================================================
# HEADER AND LIVE STATUS
# ============================================================

st.title("🧍 Smart Anti-Stoop Vest")
st.caption(
    "Caregiver dashboard · Live posture monitoring · "
    "Sensor diagnostics · Physiological trends"
)

status = api_get("/api/status")

if status is None:
    st.error(
        f"Cannot reach Flask at {api_url}. "
        "Check that python app.py is running."
    )
    st.stop()

if not isinstance(status, dict):
    st.error("/api/status must return a JSON object.")
    st.stop()

posture = status.get("posture", {})
vitals = status.get("vitals", {})

if not isinstance(posture, dict):
    posture = {}

if not isinstance(vitals, dict):
    vitals = {}

# Combine flat and nested responses for sensor-specific display.
sensor_data = collect_fields(status)

# Give explicit nested sections a chance to supply missing fields.
sensor_data.update(collect_fields(posture))
sensor_data.update(collect_fields(vitals))

# Support a direct, flat sensor payload as well.
sensor_data.update({
    key: value
    for key, value in status.items()
    if not isinstance(value, (dict, list))
})

# ---------------- Current status cards ----------------

bend_detected = get_field(sensor_data, "bend_detected")
is_standing = get_field(sensor_data, "is_standing")
heart_rate = get_field(sensor_data, "heart_rate_bpm")
temperature = get_field(sensor_data, "temperature_c")
humidity = get_field(sensor_data, "humidity_pct")

c1, c2, c3, c4 = st.columns(4)

if bend_detected is None:
    c1.metric("Posture", "—")
elif bend_detected:
    c1.metric("Posture", "ALERT — Stooping")
else:
    c1.metric("Posture", "OK")

if is_standing is None:
    c2.metric("Activity", "—")
else:
    c2.metric(
        "Activity",
        "Standing" if is_standing else "Sitting / Lying",
    )

c3.metric(
    "Heart rate",
    show_value(heart_rate, " bpm"),
)

c4.metric(
    "Skin-side temperature",
    show_value(temperature, " °C", 1),
)

last_timestamp = (
    get_field(sensor_data, "timestamp")
    or get_field(sensor_data, "updated_at")
    or "Not provided by API"
)

st.caption(f"Last update: {last_timestamp}")


# ============================================================
# INDIVIDUAL SENSOR DETAILS
# ============================================================

st.header("🔬 Individual Sensor Details")

st.caption(
    "Each section displays readings from the corresponding sensor. "
    "Unavailable values are shown as —."
)

# ---------------- 1. Flex sensors ----------------

with st.container(border=True):
    st.subheader("1. Flex Sensors")
    st.caption(
        "Upper-back and lower-back bending measurements · "
        "GPIO 34 and GPIO 35"
    )

    flex1, flex2 = st.columns(2)

    show_sensor_card(
        flex1,
        "Upper Flex — Baseline Delta",
        get_field(sensor_data, "flex_upper"),
        " ADC",
        1,
    )

    show_sensor_card(
        flex2,
        "Lower Flex — Baseline Delta",
        get_field(sensor_data, "flex_lower"),
        " ADC",
        1,
    )

    st.info(
        "These are the differences between the current ADC readings "
        "and the calibrated baselines. They are not raw ADC values."
    )

# ---------------- 2. MPU-compatible IMU ----------------

with st.container(border=True):
    st.subheader("2. MPU-Compatible IMU")
    st.caption("I²C SDA: GPIO 21 · SCL: GPIO 22")

    imu1, imu2 = st.columns(2)

    show_sensor_card(
        imu1,
        "Back Pitch Angle",
        get_field(sensor_data, "imu_pitch_deg"),
        "°",
        2,
    )

    imu_value = get_field(sensor_data, "imu_pitch_deg")

    if isinstance(imu_value, (int, float)):
        imu_state = (
            "Possible bend"
            if imu_value > 20
            else "Below bend threshold"
        )
    else:
        imu_state = "Unavailable"

    imu2.metric("IMU Threshold Interpretation", imu_state)

    st.caption(
        "The configured IMU bend threshold is 20°. "
        "Final posture detection also depends on flex readings "
        "and the standing classification."
    )

# ---------------- 3. ADXL345 ----------------

with st.container(border=True):
    st.subheader("3. ADXL345 Accelerometer")
    st.caption("I²C SDA: GPIO 21 · SCL: GPIO 22")

    adxl1, adxl2 = st.columns(2)

    adxl_value = get_field(sensor_data, "adxl_tilt_deg")

    show_sensor_card(
        adxl1,
        "Tilt Angle",
        adxl_value,
        "°",
        2,
    )

    if isinstance(adxl_value, (int, float)):
        adxl_state = (
            "Upright by configured threshold"
            if adxl_value < 25
            else "Outside upright threshold"
        )
    else:
        adxl_state = "Unavailable"

    adxl2.metric("Tilt Interpretation", adxl_state)

    st.caption(
        "The ESP32 classifies standing when ADXL345 tilt is below "
        "25°. Verify the sensor orientation during calibration."
    )

# ---------------- 4. DHT11 ----------------

with st.container(border=True):
    st.subheader("4. DHT11 — Environmental Readings")
    st.caption("Data pin: GPIO 4")

    dht1, dht2 = st.columns(2)

    show_sensor_card(
        dht1,
        "Temperature",
        get_field(sensor_data, "temperature_c"),
        " °C",
        1,
    )

    show_sensor_card(
        dht2,
        "Humidity",
        get_field(sensor_data, "humidity_pct"),
        " %",
        1,
    )

# ---------------- 5. MAX3010x ----------------

with st.container(border=True):
    st.subheader("5. MAX3010x — Heart Rate")
    st.caption("I²C SDA: GPIO 21 · SCL: GPIO 22")

    hr1, hr2 = st.columns(2)

    show_sensor_card(
        hr1,
        "Average Heart Rate",
        get_field(sensor_data, "heart_rate_bpm"),
        " bpm",
    )

    hr_value = get_field(sensor_data, "heart_rate_bpm")

    if isinstance(hr_value, (int, float)) and hr_value > 0:
        hr_state = "Reading available"
    elif hr_value == 0:
        hr_state = "No valid average yet"
    else:
        hr_state = "Unavailable"

    hr2.metric("Reading Status", hr_state)

    st.info(
        "The current ESP32 payload sends the averaged heart rate. "
        "Raw IR values, finger detection and instantaneous BPM "
        "are not included in the JSON payload."
    )

# ---------------- 6. Posture detection ----------------

with st.container(border=True):
    st.subheader("6. Posture Detection Logic")

    p1, p2 = st.columns(2)

    show_sensor_card(
        p1,
        "Standing Classification",
        get_field(sensor_data, "is_standing"),
    )

    show_sensor_card(
        p2,
        "Bend Detected",
        get_field(sensor_data, "bend_detected"),
    )

    st.caption(
        "A bend is detected when the flex threshold and IMU threshold "
        "are exceeded while the vest classifies the user as standing."
    )

# ---------------- 7. Actuators ----------------

with st.container(border=True):
    st.subheader("7. Feedback Actuators")

    a1, a2 = st.columns(2)

    vibration = get_field(sensor_data, "vibration_active")
    buzzer = get_field(sensor_data, "buzzer_active")

    show_sensor_card(
        a1,
        "Vibration Motor — GPIO 25",
        vibration,
    )

    show_sensor_card(
        a2,
        "Buzzer — GPIO 26",
        buzzer,
    )

    led1, led2, led3 = st.columns(3)

    led1.metric("Red LED — GPIO 27", "Configured")
    led2.metric("Green LED — GPIO 14", "Configured")
    led3.metric("Blue LED — GPIO 12", "Configured")

    st.caption(
        "RGB LED pins are configured on the ESP32, but LED color "
        "and PWM intensity are not currently sent to Flask. "
        "Their current states cannot be determined from this payload."
    )


# ============================================================
# ALL RECEIVED STATUS FIELDS
# ============================================================

with st.expander("📋 Complete API Status — All Fields", expanded=False):
    display_all_fields(status, "Full /api/status Response")

    st.caption(
        "Includes the fields exposed by Flask, whether nested or flat."
    )


# ============================================================
# 24-HOUR STATISTICS
# ============================================================

st.header("📊 24-Hour Summary")

stats = api_get("/api/stats")

if isinstance(stats, dict):
    s1, s2, s3, s4 = st.columns(4)

    s1.metric(
        "Stoop Episodes",
        stats.get("stoop_episodes", "—"),
    )

    longest = stats.get("longest_stoop_seconds")
    s2.metric(
        "Longest Stoop",
        f"{longest} s" if longest is not None else "—",
    )

    percent = stats.get("percent_time_stooped")
    s3.metric(
        "Time Stooped",
        f"{percent} %" if percent is not None else "—",
    )

    avg_hr = stats.get("avg_heart_rate_bpm")
    s4.metric(
        "Average Heart Rate",
        f"{avg_hr} bpm" if avg_hr is not None else "—",
    )

    with st.expander("View all statistics fields"):
        display_all_fields(stats, "Complete Statistics Response")

elif stats is None:
    st.warning("Could not retrieve /api/stats.")


# ============================================================
# HISTORY AND CHARTS
# ============================================================

st.header("📈 Historical Trends")

history = api_get("/api/history", limit=history_n)

if isinstance(history, dict):
    posture_events = history.get("posture_events", [])
    vitals_log = history.get("vitals_log", [])

    with st.expander("All posture history records"):
        display_all_fields(posture_events, "Posture History")

    with st.expander("All vitals history records"):
        display_all_fields(vitals_log, "Vitals History")

    left, right = st.columns(2)

    # ---------------- Posture chart ----------------

    with left:
        st.subheader("Posture Trend")

        if isinstance(posture_events, list) and posture_events:
            pe = pd.json_normalize(posture_events, sep=".")

            if {"timestamp", "imu_pitch_deg"}.issubset(pe.columns):
                pe["timestamp"] = pd.to_datetime(
                    pe["timestamp"],
                    errors="coerce",
                    utc=True,
                )

                pe["imu_pitch_deg"] = pd.to_numeric(
                    pe["imu_pitch_deg"],
                    errors="coerce",
                )

                pe = pe.dropna(
                    subset=["timestamp", "imu_pitch_deg"]
                )

                if not pe.empty:
                    fig = px.line(
                        pe,
                        x="timestamp",
                        y="imu_pitch_deg",
                        labels={
                            "timestamp": "Time (UTC)",
                            "imu_pitch_deg": "Back pitch (degrees)",
                        },
                    )

                    fig.add_hline(
                        y=20,
                        line_dash="dash",
                        line_color="red",
                        annotation_text="IMU threshold",
                    )

                    st.plotly_chart(
                        fig,
                        use_container_width=True,
                    )
                else:
                    st.info("No valid posture measurements to plot.")
            else:
                st.info(
                    "Posture history must contain timestamp and "
                    "imu_pitch_deg."
                )
        else:
            st.info("No posture history records available.")

    # ---------------- Vitals chart ----------------

    with right:
        st.subheader("Vitals Trend")

        if isinstance(vitals_log, list) and vitals_log:
            vl = pd.json_normalize(vitals_log, sep=".")

            if "timestamp" in vl.columns:
                vl["timestamp"] = pd.to_datetime(
                    vl["timestamp"],
                    errors="coerce",
                    utc=True,
                )

                vital_columns = [
                    column
                    for column in [
                        "heart_rate_bpm",
                        "temperature_c",
                        "humidity_pct",
                    ]
                    if column in vl.columns
                ]

                for column in vital_columns:
                    vl[column] = pd.to_numeric(
                        vl[column],
                        errors="coerce",
                    )

                vl = vl.dropna(subset=["timestamp"])

                if not vl.empty and vital_columns:
                    fig2 = px.line(
                        vl,
                        x="timestamp",
                        y=vital_columns,
                        labels={
                            "timestamp": "Time (UTC)",
                            "value": "Reading",
                            "variable": "Measurement",
                            "heart_rate_bpm": "Heart Rate (bpm)",
                            "temperature_c": "Temperature (°C)",
                            "humidity_pct": "Humidity (%)",
                        },
                    )

                    st.plotly_chart(
                        fig2,
                        use_container_width=True,
                    )
                else:
                    st.info("No valid vitals measurements to plot.")
            else:
                st.info("Vitals history has no timestamp field.")
        else:
            st.info("No vitals history records available.")

elif history is None:
    st.warning("Could not retrieve /api/history.")


# ============================================================
# ALERT LOG
# ============================================================

st.header("🚨 Recent Alerts")

alerts = api_get("/api/alerts")

if isinstance(alerts, list) and alerts:
    with st.expander("All alert fields", expanded=False):
        display_all_fields(alerts, "Complete Alert Records")

    df = pd.json_normalize(alerts, sep=".")

    required_columns = [
        "timestamp",
        "imu_pitch_deg",
        "vibration_active",
        "buzzer_active",
    ]

    for column in required_columns:
        if column not in df.columns:
            df[column] = None

    df = df[required_columns].copy()

    df.columns = [
        "Time (UTC)",
        "Back Pitch (deg)",
        "Vibration",
        "Buzzer",
    ]

    def format_boolean(value):
        if value is None or pd.isna(value):
            return "N/A"

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized in ("true", "1", "yes"):
                return "Yes"

            if normalized in ("false", "0", "no"):
                return "No"

            return value

        if isinstance(value, (bool, int)):
            return "Yes" if bool(value) else "No"

        return str(value)

    df["Vibration"] = df["Vibration"].apply(format_boolean)
    df["Buzzer"] = df["Buzzer"].apply(format_boolean)

    st.dataframe(
        df.head(15),
        use_container_width=True,
        hide_index=True,
    )

elif alerts is None:
    st.warning("Could not retrieve /api/alerts.")

else:
    st.info("No stoop alerts recorded yet.")


# ============================================================
# FOOTER
# ============================================================

with st.expander("API Information"):
    st.markdown(
        """
        | Endpoint | Purpose |
        |---|---|
        | `/api/status` | Current sensor readings and posture |
        | `/api/stats` | Aggregated statistics |
        | `/api/history` | Historical posture and vitals |
        | `/api/alerts` | Recorded stoop alerts |

        The ESP32 sends its measurements to `POST /api/data`.
        This dashboard reads from the Flask GET endpoints above.
        """
    )

    st.caption(
        "Sensor availability and history depend on what the Flask "
        "backend stores and exposes."
    )
