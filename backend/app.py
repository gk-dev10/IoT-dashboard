"""
Smart Anti-Stoop Vest — Flask Backend
======================================
REST API (receives data from ESP32) + Web Dashboard (for caregiver/clinician).

Run:
    pip install -r requirements.txt
    python app.py

Server listens on 0.0.0.0:5000 by default — update SERVER_URL in the ESP32
firmware to match this machine's local IP address (e.g. http://192.168.1.100:5000/api/data).
"""

from flask import Flask, request, jsonify, render_template
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), "vest_data.db")


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posture_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            flex_upper REAL,
            flex_lower REAL,
            imu_pitch_deg REAL,
            adxl_tilt_deg REAL,
            is_standing INTEGER,
            bend_detected INTEGER,
            vibration_active INTEGER,
            buzzer_active INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vitals_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            temperature_c REAL,
            humidity_pct REAL,
            heart_rate_bpm INTEGER
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------
@app.route("/api/data", methods=["POST"])
def receive_data():
    """Receives a JSON payload from the ESP32 and writes it to both tables."""
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    now = datetime.utcnow().isoformat()
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO posture_events
               (timestamp, flex_upper, flex_lower, imu_pitch_deg, adxl_tilt_deg,
                is_standing, bend_detected, vibration_active, buzzer_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                payload.get("flex_upper"),
                payload.get("flex_lower"),
                payload.get("imu_pitch_deg"),
                payload.get("adxl_tilt_deg"),
                int(bool(payload.get("is_standing"))),
                int(bool(payload.get("bend_detected"))),
                int(bool(payload.get("vibration_active"))),
                int(bool(payload.get("buzzer_active"))),
            ),
        )
        conn.execute(
            """INSERT INTO vitals_log
               (timestamp, temperature_c, humidity_pct, heart_rate_bpm)
               VALUES (?, ?, ?, ?)""",
            (
                now,
                payload.get("temperature_c"),
                payload.get("humidity_pct"),
                payload.get("heart_rate_bpm"),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"status": "ok", "received_at": now}), 201


@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns the most recent posture state and vitals for the live status widget."""
    conn = get_db()
    posture = conn.execute(
        "SELECT * FROM posture_events ORDER BY id DESC LIMIT 1"
    ).fetchone()
    vitals = conn.execute(
        "SELECT * FROM vitals_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    return jsonify({
        "posture": dict(posture) if posture else None,
        "vitals": dict(vitals) if vitals else None,
    })


@app.route("/api/history", methods=["GET"])
def get_history():
    """Returns historical posture events, optionally filtered by ?limit=N (default 100)."""
    limit = request.args.get("limit", default=100, type=int)
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM posture_events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    vitals_rows = conn.execute(
        "SELECT * FROM vitals_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    return jsonify({
        "posture_events": [dict(r) for r in reversed(rows)],
        "vitals_log": [dict(r) for r in reversed(vitals_rows)],
    })


@app.route("/api/alerts", methods=["GET"])
def get_alerts():
    """Returns only the events where a stoop was actually detected (alert log)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM posture_events WHERE bend_detected = 1 ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Summary numbers for the last 24 hours (used by the Streamlit dashboard)."""
    from datetime import timedelta
    cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    push_interval_s = 5  # ESP32 posts every 5 seconds

    conn = get_db()
    rows = conn.execute(
        "SELECT bend_detected FROM posture_events WHERE timestamp >= ? ORDER BY id ASC",
        (cutoff,),
    ).fetchall()
    hr = conn.execute(
        "SELECT AVG(heart_rate_bpm) AS avg_hr FROM vitals_log "
        "WHERE timestamp >= ? AND heart_rate_bpm > 0",
        (cutoff,),
    ).fetchone()
    conn.close()

    total = len(rows)
    stoop_samples = sum(1 for r in rows if r["bend_detected"])

    # Count separate stoop episodes and the longest one (runs of consecutive bent samples)
    episodes, longest, run = 0, 0, 0
    for r in rows:
        if r["bend_detected"]:
            run += 1
            longest = max(longest, run)
        else:
            if run > 0:
                episodes += 1
            run = 0
    if run > 0:
        episodes += 1

    return jsonify({
        "total_samples": total,
        "stoop_samples": stoop_samples,
        "stoop_episodes": episodes,
        "longest_stoop_seconds": longest * push_interval_s,
        "percent_time_stooped": round(100 * stoop_samples / total, 1) if total else 0,
        "avg_heart_rate_bpm": round(hr["avg_hr"], 1) if hr and hr["avg_hr"] else None,
    })


# ---------------------------------------------------------------------------
# Dashboard (HTML front-end)
# ---------------------------------------------------------------------------
@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_template("dashboard.html")


@app.route("/", methods=["GET"])
def index():
    return dashboard()


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)