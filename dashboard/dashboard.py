"""
Smart Anti-Stoop Vest — Streamlit Dashboard
===========================================
Presentation layer. Reads everything from the Flask API (never touches the DB).

Run (from the dashboard/ folder):
    pip install -r requirements.txt
    streamlit run dashboard.py

Flask must already be running (default http://localhost:5000).
"""

import os
import pandas as pd
import plotly.express as px
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

DEFAULT_API = os.environ.get("VEST_API_URL", "http://localhost:5000")

st.set_page_config(page_title="Smart Anti-Stoop Vest", page_icon="🧍", layout="wide")

# ---------------- Sidebar ----------------
st.sidebar.title("Settings")
api_url = st.sidebar.text_input("Flask API URL", DEFAULT_API)
refresh_s = st.sidebar.slider("Auto-refresh (seconds)", 2, 30, 5)
history_n = st.sidebar.slider("History points to plot", 20, 300, 60)
st_autorefresh(interval=refresh_s * 1000, key="auto_refresh")


def api_get(path, **params):
    """GET helper — returns parsed JSON or None if Flask is unreachable."""
    try:
        r = requests.get(f"{api_url}{path}", params=params, timeout=3)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return None


# ---------------- Header ----------------
st.title("🧍 Smart Anti-Stoop Vest — Caregiver Dashboard")
st.caption("Live posture monitoring and physiological trends")

status = api_get("/api/status")
if status is None:
    st.error(f"Cannot reach the Flask server at {api_url}. Is `python app.py` running?")
    st.stop()

posture = status.get("posture")
vitals = status.get("vitals")

if not posture:
    st.info("Connected to Flask, but no data received from the vest yet.")
    st.stop()

# ---------------- Live status cards ----------------
c1, c2, c3, c4 = st.columns(4)

if posture["bend_detected"]:
    c1.metric("Posture", "ALERT — Stooping")
else:
    c1.metric("Posture", "OK")

c2.metric("Activity", "Standing / Walking" if posture["is_standing"] else "Sitting / Lying")

hr = vitals.get("heart_rate_bpm") if vitals else None
c3.metric("Heart rate", f"{hr} bpm" if hr else "—")

temp = vitals.get("temperature_c") if vitals else None
c4.metric("Skin-side temp", f"{temp:.1f} °C" if temp is not None else "—")

st.caption(f"Last update (UTC): {posture['timestamp']}")

# ---------------- 24-hour summary ----------------
stats = api_get("/api/stats")
if stats:
    st.subheader("Last 24 hours")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Stoop episodes", stats["stoop_episodes"])
    s2.metric("Longest stoop", f"{stats['longest_stoop_seconds']} s")
    s3.metric("Time stooped", f"{stats['percent_time_stooped']} %")
    avg_hr = stats["avg_heart_rate_bpm"]
    s4.metric("Avg heart rate", f"{avg_hr} bpm" if avg_hr else "—")

# ---------------- Charts ----------------
history = api_get("/api/history", limit=history_n)
if history:
    pe = pd.DataFrame(history["posture_events"])
    vl = pd.DataFrame(history["vitals_log"])

    left, right = st.columns(2)

    with left:
        st.subheader("Posture trend")
        if not pe.empty:
            pe["timestamp"] = pd.to_datetime(pe["timestamp"])
            fig = px.line(pe, x="timestamp", y="imu_pitch_deg",
                          labels={"imu_pitch_deg": "Back pitch (deg)", "timestamp": ""})
            fig.add_hline(y=20, line_dash="dash", line_color="red",
                          annotation_text="stoop threshold")
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Vitals trend")
        if not vl.empty:
            vl["timestamp"] = pd.to_datetime(vl["timestamp"])
            fig2 = px.line(vl, x="timestamp", y=["heart_rate_bpm", "temperature_c"],
                           labels={"value": "Value", "timestamp": "", "variable": ""})
            st.plotly_chart(fig2, use_container_width=True)

# ---------------- Alert log ----------------
st.subheader("Recent alerts")
alerts = api_get("/api/alerts")
if alerts:
    df = pd.DataFrame(alerts)[
        ["timestamp", "imu_pitch_deg", "vibration_active", "buzzer_active"]
    ]
    df.columns = ["Time (UTC)", "Back pitch (deg)", "Vibration", "Buzzer"]
    df["Vibration"] = df["Vibration"].map({1: "Yes", 0: "No"})
    df["Buzzer"] = df["Buzzer"].map({1: "Yes", 0: "No"})
    st.dataframe(df.head(15), use_container_width=True, hide_index=True)
else:
    st.write("No stoop alerts recorded yet.")