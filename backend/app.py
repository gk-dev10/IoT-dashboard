"""Smart Posture T-Shirt v2 — Flask Backend Service.

REST API for ESP32 telemetry ingestion, bi-directional commands,
Server-Sent Events streaming, and static hosting for the web dashboard.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import os
import queue
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
for path in (REPO_ROOT, BASE_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from flask import (
    Flask,
    Response,
    jsonify,
    request,
    send_from_directory,
    stream_with_context,
)

from backend.commands import (
    create_command,
    expire_stale_commands,
    get_pending_commands_for_device,
    get_recent_commands,
    mark_commands_sent,
    merge_commands,
)
from backend.db import DEFAULT_DB_PATH, get_db, init_db
from backend.episodes import (
    check_and_close_timed_out_episodes,
    process_episode_transition,
)
from backend.models import (
    get_current_utc_iso,
    sanitize_telemetry,
    validate_command_payload,
)
from backend.sse import sse_manager

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("posture_backend")

# ---------------------------------------------------------------------------
# App & Paths configuration
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(BASE_DIR)
WEB_DIR = os.path.join(REPO_ROOT, "web")

app = Flask(__name__, static_folder=None)

DEVICE_TOKEN = os.environ.get("VEST_DEVICE_TOKEN", "change-me")
DB_PATH = os.environ.get("VEST_DB_PATH", DEFAULT_DB_PATH)
DEBUG_MODE = os.environ.get("VEST_DEBUG", "0").lower() in ("1", "true", "yes")
SERVER_PORT = int(os.environ.get("VEST_PORT", "5000"))


def build_live_payload(conn):
    """Construct the full live state payload for /api/live and SSE telemetry event."""
    check_and_close_timed_out_episodes(conn, max_gap_seconds=10)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()

    telemetry_data = dict(row) if row else None
    online = False
    seconds_since_last = None

    if telemetry_data and telemetry_data.get("ts"):
        try:
            last_dt = datetime.fromisoformat(telemetry_data["ts"])
            seconds_since_last = round(
                max(0.0, (datetime.now(timezone.utc) - last_dt).total_seconds()), 1
            )
            online = seconds_since_last < 5.0
        except Exception:
            online = False

    recent_cmds = get_recent_commands(conn, limit=5)

    return {
        "online": online,
        "seconds_since_last": seconds_since_last,
        "telemetry": telemetry_data,
        "commands": recent_cmds,
    }


# ---------------------------------------------------------------------------
# Static Web Hosting Routes
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
@app.route("/dashboard", methods=["GET"])
@app.route("/dashboard/", methods=["GET"])
def index():
    """Serve the v2 web application dashboard."""
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/<path:path>", methods=["GET"])
def serve_web_assets(path):
    """Serve static assets from web directory."""
    target_file = os.path.join(WEB_DIR, path)
    if os.path.exists(target_file) and not os.path.isdir(target_file):
        return send_from_directory(WEB_DIR, path)
    if path.startswith(("css/", "js/", "vendor/")):
        return jsonify({"error": "File not found"}), 404
    # Default back to index.html for unknown router paths
    return send_from_directory(WEB_DIR, "index.html")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


@app.route("/api/data", methods=["POST"])
def ingest_data():
    """
    Ingest telemetry data from ESP32.
    Validates token, writes telemetry, tracks episodes, and delivers pending commands.
    """
    token = request.headers.get("X-Device-Token")
    if token != DEVICE_TOKEN:
        logger.warning(
            "Device token rejection from %s (provided: %r)",
            request.remote_addr,
            token,
        )
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Invalid or missing JSON body"}), 400

    now_iso = get_current_utc_iso()
    t = sanitize_telemetry(payload, now_iso)

    conn = get_db(DB_PATH)
    commands_to_send = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO telemetry (
                ts, device_id, fw, uptime_s, state, armed, muted, is_standing,
                moving, bend_detected, possible_bend, bend_duration_ms,
                imu_pitch_deg, imu_roll_deg, imu_says_bent, flex_upper,
                flex_lower, flex_says_bent, adxl_tilt_deg, vibration_active,
                buzzer_active, led_green, led_yellow, led_red, heart_rate_bpm,
                finger_present, temperature_c, humidity_pct, mpu_ok, adxl_ok,
                max_ok, flex_enabled, bend_on_deg, bend_off_deg,
                vibrate_delay_s, buzzer_delay_s, wifi_rssi
            ) VALUES (
                :ts, :device_id, :fw, :uptime_s, :state, :armed, :muted, :is_standing,
                :moving, :bend_detected, :possible_bend, :bend_duration_ms,
                :imu_pitch_deg, :imu_roll_deg, :imu_says_bent, :flex_upper,
                :flex_lower, :flex_says_bent, :adxl_tilt_deg, :vibration_active,
                :buzzer_active, :led_green, :led_yellow, :led_red, :heart_rate_bpm,
                :finger_present, :temperature_c, :humidity_pct, :mpu_ok, :adxl_ok,
                :max_ok, :flex_enabled, :bend_on_deg, :bend_off_deg,
                :vibrate_delay_s, :buzzer_delay_s, :wifi_rssi
            )
        """,
            t,
        )
        conn.commit()

        # Update episode tracking
        process_episode_transition(
            conn,
            device_id=t["device_id"],
            incoming_state=t["state"],
            imu_pitch_deg=t["imu_pitch_deg"],
            bend_duration_ms=t["bend_duration_ms"],
            incoming_ts=now_iso,
        )

        # Check and merge pending commands for the vest
        pending = get_pending_commands_for_device(conn, t["device_id"])
        if pending:
            commands_to_send = merge_commands(pending)
            cmd_ids = [cmd["id"] for cmd in pending]
            mark_commands_sent(conn, cmd_ids)
            # Broadcast updated commands to SSE listeners
            sse_manager.broadcast("command", get_recent_commands(conn, limit=5))

        # Log one line per ingest at INFO level
        pitch_str = f"{t['imu_pitch_deg']:.1f}°" if t["imu_pitch_deg"] is not None else "N/A"
        logger.info(
            "Ingest [%s] state=%s pitch=%s standing=%s bend=%s",
            t["device_id"],
            t["state"],
            pitch_str,
            t["is_standing"],
            t["bend_detected"],
        )

        # Broadcast live telemetry event
        live_payload = build_live_payload(conn)
        sse_manager.broadcast("telemetry", live_payload)

    finally:
        conn.close()

    response_data = {"status": "ok", "received_at": now_iso}
    if commands_to_send:
        response_data["commands"] = commands_to_send

    return jsonify(response_data), 201


@app.route("/api/live", methods=["GET"])
def get_live():
    """Return latest telemetry, online status, and recent commands."""
    conn = get_db(DB_PATH)
    try:
        live_data = build_live_payload(conn)
        return jsonify(live_data)
    finally:
        conn.close()


@app.route("/api/stream", methods=["GET"])
def event_stream():
    """Server-Sent Events endpoint streaming telemetry and command events."""
    q = sse_manager.subscribe()

    def generate():
        try:
            # Yield initial live state immediately
            conn = get_db(DB_PATH)
            try:
                init_state = build_live_payload(conn)
            finally:
                conn.close()

            yield f"event: telemetry\ndata: {json.dumps(init_state)}\n\n"

            while True:
                try:
                    # Wait for next event or send heartbeat comment every 15s
                    msg = q.get(timeout=15.0)
                    yield msg
                except queue.Empty:
                    yield ": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            sse_manager.unsubscribe(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.route("/api/history", methods=["GET"])
def get_history():
    """
    Return recent telemetry points in chronological order.
    Query parameters:
      minutes: int (default 10)
      limit: int (default 600)
    """
    try:
        minutes = max(1, min(1440, int(request.args.get("minutes", 10))))
        limit = max(10, min(5000, int(request.args.get("limit", 600))))
    except ValueError:
        return jsonify({"error": "Invalid query parameters"}), 400

    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    conn = get_db(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM telemetry
            WHERE ts >= ?
            ORDER BY id ASC
        """,
            (cutoff,),
        )
        rows = [dict(r) for r in cursor.fetchall()]

        # Downsample if total points exceed limit
        if len(rows) > limit:
            step = len(rows) / float(limit)
            downsampled = [rows[int(i * step)] for i in range(limit)]
            # Ensure the absolute latest point is included
            downsampled[-1] = rows[-1]
            rows = downsampled

        return jsonify(rows)
    finally:
        conn.close()


@app.route("/api/episodes", methods=["GET"])
def get_episodes():
    """Return recent bend episodes (newest first)."""
    try:
        limit = max(1, min(200, int(request.args.get("limit", 50))))
    except ValueError:
        limit = 50

    conn = get_db(DB_PATH)
    try:
        check_and_close_timed_out_episodes(conn, max_gap_seconds=10)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms
            FROM episodes
            ORDER BY id DESC
            LIMIT ?
        """,
            (limit,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify(rows)
    finally:
        conn.close()


@app.route("/api/stats", methods=["GET"])
def get_stats():
    """Aggregated statistics over the specified hours window (default 24)."""
    try:
        hours = max(1, min(720, int(request.args.get("hours", 24))))
    except ValueError:
        hours = 24

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    conn = get_db(DB_PATH)
    try:
        check_and_close_timed_out_episodes(conn, max_gap_seconds=10)
        cursor = conn.cursor()

        # Episodes stats
        cursor.execute(
            """
            SELECT COUNT(*) AS ep_count, MAX(duration_ms) AS max_dur
            FROM episodes
            WHERE start_ts >= ?
        """,
            (cutoff,),
        )
        ep_row = cursor.fetchone()
        episode_count = ep_row["ep_count"] if ep_row else 0
        longest_bend_ms = ep_row["max_dur"] if ep_row and ep_row["max_dur"] else 0

        # Telemetry aggregate stats
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_samples,
                SUM(CASE WHEN state IN ('WARNING', 'ALERT') THEN 1 ELSE 0 END) AS stoop_samples,
                SUM(CASE WHEN is_standing = 1 THEN 1 ELSE 0 END) AS standing_samples,
                SUM(CASE WHEN is_standing = 0 THEN 1 ELSE 0 END) AS sitting_samples,
                AVG(CASE WHEN heart_rate_bpm IS NOT NULL AND heart_rate_bpm > 0 THEN heart_rate_bpm ELSE NULL END) AS avg_hr
            FROM telemetry
            WHERE ts >= ?
        """,
            (cutoff,),
        )
        t_row = cursor.fetchone()

        total = t_row["total_samples"] if t_row else 0
        stoop_samples = t_row["stoop_samples"] if t_row and t_row["stoop_samples"] else 0
        standing_samples = t_row["standing_samples"] if t_row and t_row["standing_samples"] else 0
        sitting_samples = t_row["sitting_samples"] if t_row and t_row["sitting_samples"] else 0
        avg_hr = round(t_row["avg_hr"], 1) if t_row and t_row["avg_hr"] else None

        percent_time_stooped = round(100.0 * stoop_samples / total, 1) if total > 0 else 0.0
        percent_standing = round(100.0 * standing_samples / total, 1) if total > 0 else 0.0
        percent_sitting = round(100.0 * sitting_samples / total, 1) if total > 0 else 0.0

        return jsonify({
            "hours": hours,
            "episode_count": episode_count,
            "longest_bend_ms": longest_bend_ms,
            "longest_bend_s": round(longest_bend_ms / 1000.0, 1),
            "percent_time_stooped": percent_time_stooped,
            "percent_standing": percent_standing,
            "percent_sitting": percent_sitting,
            "avg_heart_rate_bpm": avg_hr,
            "total_samples": total,
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Analysis Endpoints with in-memory cache
# ---------------------------------------------------------------------------
_analysis_cache = {}

@app.route("/api/analysis", methods=["GET"])
def get_analysis():
    """
    Comprehensive posture vs physiological & environmental analysis.
    Query params:
      minutes: int (allowed 5, 15, 60, 360, 1440, or 0 for everything)
      exclude_moving: int/bool (default 1)
      device_id: str (optional, defaults to device with most recent data)
    """
    raw_min = request.args.get("minutes", "60")
    try:
        minutes = int(raw_min)
    except ValueError:
        return jsonify({"error": "Invalid 'minutes' parameter"}), 400

    if minutes not in (5, 15, 60, 360, 1440, 0):
        return jsonify({"error": "Allowed minutes values are 5, 15, 60, 360, 1440, or 0 (all)"}), 400

    exclude_moving = request.args.get("exclude_moving", "1").lower() in ("1", "true", "yes")
    device_id = request.args.get("device_id")

    # In-memory cache check (5s TTL)
    now_epoch = datetime.now(timezone.utc).timestamp()
    cache_key = (minutes, exclude_moving, device_id)
    if cache_key in _analysis_cache:
        cached_ts, cached_data = _analysis_cache[cache_key]
        if now_epoch - cached_ts < 5.0:
            return jsonify(cached_data)

    from backend.analysis import analyze_telemetry_and_episodes

    conn = get_db(DB_PATH)
    try:
        cursor = conn.cursor()

        # If device_id not specified, default to device with most recent data
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        # Determine cutoff timestamp
        if minutes > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
            cursor.execute("""
                SELECT * FROM telemetry
                WHERE device_id = ? AND ts >= ?
                ORDER BY id ASC
            """, (device_id, cutoff))
            rows = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT * FROM episodes
                WHERE device_id = ? AND start_ts >= ? AND end_ts IS NOT NULL
                ORDER BY id ASC
            """, (device_id, cutoff))
            episodes = [dict(r) for r in cursor.fetchall()]
        else:
            cursor.execute("""
                SELECT * FROM telemetry
                WHERE device_id = ?
                ORDER BY id ASC
            """, (device_id,))
            rows = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT * FROM episodes
                WHERE device_id = ? AND end_ts IS NOT NULL
                ORDER BY id ASC
            """, (device_id,))
            episodes = [dict(r) for r in cursor.fetchall()]

        analysis_result = analyze_telemetry_and_episodes(
            rows=rows,
            episodes=episodes,
            range_minutes=minutes,
            exclude_moving=exclude_moving,
            device_id=device_id
        )

        _analysis_cache[cache_key] = (now_epoch, analysis_result)
        return jsonify(analysis_result)

    finally:
        conn.close()


@app.route("/api/analysis/export.csv", methods=["GET"])
def export_analysis_csv():
    """
    Export 5-second bucket table as CSV.
    Columns: ts, category, pitch_deg, heart_rate_bpm, temperature_c, humidity_pct, moving_fraction
    """
    raw_min = request.args.get("minutes", "60")
    try:
        minutes = int(raw_min)
    except ValueError:
        return jsonify({"error": "Invalid 'minutes' parameter"}), 400

    if minutes not in (5, 15, 60, 360, 1440, 0):
        return jsonify({"error": "Allowed minutes values are 5, 15, 60, 360, 1440, or 0 (all)"}), 400

    exclude_moving = request.args.get("exclude_moving", "1").lower() in ("1", "true", "yes")
    device_id = request.args.get("device_id")

    from backend.analysis import aggregate_into_buckets

    conn = get_db(DB_PATH)
    try:
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        if minutes > 0:
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
            cursor.execute("SELECT * FROM telemetry WHERE device_id = ? AND ts >= ? ORDER BY id ASC", (device_id, cutoff))
        else:
            cursor.execute("SELECT * FROM telemetry WHERE device_id = ? ORDER BY id ASC", (device_id,))
        rows = [dict(r) for r in cursor.fetchall()]

        buckets = aggregate_into_buckets(rows, exclude_moving=exclude_moving)

        import io
        import csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ts", "category", "pitch_deg", "heart_rate_bpm", "temperature_c", "humidity_pct", "moving_fraction"])

        for b in buckets:
            writer.writerow([
                b["ts"],
                b["category"],
                round(b["pitch"], 1) if b["pitch"] is not None else "",
                round(b["hr"], 1) if b["hr"] is not None else "",
                round(b["temp"], 1) if b["temp"] is not None else "",
                round(b["hum"], 1) if b["hum"] is not None else "",
                b["moving_fraction"] if b.get("moving_fraction") is not None else "",
            ])

        csv_content = output.getvalue()
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=posture_analysis_{device_id}_{minutes}m.csv"}
        )
    finally:
        conn.close()


@app.route("/api/commands", methods=["POST"])
def post_command():
    """
    Receive and queue a command from the UI.
    Allowed formats:
      {"type": "calibrate"}
      {"type": "mute", "seconds": 60}
      {"type": "test", "target": "buzzer"}
      {"type": "config", "bend_on_deg": 20, ...}
    """
    data = request.get_json(silent=True)
    is_valid, err_msg, sanitized = validate_command_payload(data)
    if not is_valid:
        return jsonify({"error": err_msg}), 400

    device_id = (data.get("device_id") or "vest-01").strip()
    cmd_type = sanitized["type"]

    conn = get_db(DB_PATH)
    try:
        cmd_record = create_command(conn, device_id, cmd_type, sanitized)
        # Notify SSE subscribers that a new command was created
        sse_manager.broadcast("command", get_recent_commands(conn, limit=5))
        return jsonify(cmd_record), 201
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Backward Compatibility Shims
# ---------------------------------------------------------------------------
@app.route("/api/status", methods=["GET"])
def legacy_status():
    """Shim for legacy status call."""
    conn = get_db(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM telemetry ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        t = dict(row) if row else None
        return jsonify({
            "posture": t,
            "vitals": {
                "temperature_c": t.get("temperature_c") if t else None,
                "humidity_pct": t.get("humidity_pct") if t else None,
                "heart_rate_bpm": t.get("heart_rate_bpm") if t else None,
            }
            if t
            else None,
        })
    finally:
        conn.close()


@app.route("/api/alerts", methods=["GET"])
def legacy_alerts():
    """Shim for legacy alerts call."""
    conn = get_db(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM telemetry
            WHERE bend_detected = 1
            ORDER BY id DESC LIMIT 50
        """)
        rows = [dict(r) for r in cursor.fetchall()]
        return jsonify(rows)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Server Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db(DB_PATH)
    logger.info("Database initialized at %s", DB_PATH)
    logger.info(
        "Starting Flask server on 0.0.0.0:%d (debug=%s)",
        SERVER_PORT,
        DEBUG_MODE,
    )
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=DEBUG_MODE, threaded=True)