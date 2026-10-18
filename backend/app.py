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
    """
    Return recent bend episodes (newest first).
    Supports backward compatibility:
    - If called without rich query params (just limit or none), returns plain array of episodes.
    - If called with rich query params (from, to, level, min_duration_s, search=1), returns {total, episodes}.
    """
    from_iso = request.args.get("from")
    to_iso = request.args.get("to")
    level = request.args.get("level")
    min_duration_s = request.args.get("min_duration_s")
    device_id = request.args.get("device_id")
    order = request.args.get("order", "desc").lower()
    is_search = request.args.get("search") in ("1", "true") or any([from_iso, to_iso, level, min_duration_s])

    try:
        limit = max(1, min(500, int(request.args.get("limit", 50))))
    except ValueError:
        return jsonify({"error": "Invalid 'limit' parameter"}), 400

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "Invalid 'offset' parameter"}), 400

    min_dur_ms = None
    if min_duration_s is not None:
        try:
            min_dur_ms = int(float(min_duration_s) * 1000)
        except ValueError:
            return jsonify({"error": "Invalid 'min_duration_s' parameter"}), 400

    if order not in ("asc", "desc"):
        return jsonify({"error": "Invalid 'order' parameter. Must be 'asc' or 'desc'"}), 400

    if level and level not in ("ALL", "WARNING", "ALERT", "BOTH"):
        return jsonify({"error": "Invalid 'level' parameter"}), 400

    conn = get_db(DB_PATH)
    try:
        check_and_close_timed_out_episodes(conn, max_gap_seconds=10)
        cursor = conn.cursor()

        # Build query
        clauses = []
        params = []

        if device_id:
            clauses.append("device_id = ?")
            params.append(device_id)

        if from_iso:
            clauses.append("start_ts >= ?")
            params.append(from_iso)

        if to_iso:
            clauses.append("start_ts <= ?")
            params.append(to_iso)

        if level in ("WARNING", "ALERT"):
            clauses.append("max_level = ?")
            params.append(level)
        elif level == "BOTH":
            clauses.append("max_level IN ('WARNING', 'ALERT')")

        if min_dur_ms is not None:
            clauses.append("duration_ms >= ?")
            params.append(min_dur_ms)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        # Total count
        cursor.execute(f"SELECT COUNT(*) AS total FROM episodes {where_sql}", tuple(params))
        total_count = cursor.fetchone()["total"]

        # Fetch page
        order_sql = f"ORDER BY start_ts {order.upper()}"
        cursor.execute(f"""
            SELECT id, device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms
            FROM episodes
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
        """, tuple(params + [limit, offset]))

        episodes = [dict(r) for r in cursor.fetchall()]

        if is_search:
            return jsonify({
                "total": total_count,
                "limit": limit,
                "offset": offset,
                "episodes": episodes,
            })
        else:
            return jsonify(episodes)
    finally:
        conn.close()


@app.route("/api/episodes/search", methods=["GET"])
def search_episodes():
    """Explicit rich episodes search returning {total, episodes}."""
    from_iso = request.args.get("from")
    to_iso = request.args.get("to")
    level = request.args.get("level")
    min_duration_s = request.args.get("min_duration_s")
    device_id = request.args.get("device_id")
    order = request.args.get("order", "desc").lower()

    try:
        limit = max(1, min(500, int(request.args.get("limit", 50))))
    except ValueError:
        return jsonify({"error": "Invalid 'limit' parameter"}), 400

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "Invalid 'offset' parameter"}), 400

    min_dur_ms = None
    if min_duration_s is not None:
        try:
            min_dur_ms = int(float(min_duration_s) * 1000)
        except ValueError:
            return jsonify({"error": "Invalid 'min_duration_s' parameter"}), 400

    if order not in ("asc", "desc"):
        return jsonify({"error": "Invalid 'order' parameter. Must be 'asc' or 'desc'"}), 400

    if level and level not in ("ALL", "WARNING", "ALERT", "BOTH"):
        return jsonify({"error": "Invalid 'level' parameter"}), 400

    conn = get_db(DB_PATH)
    try:
        check_and_close_timed_out_episodes(conn, max_gap_seconds=10)
        cursor = conn.cursor()

        clauses = []
        params = []

        if device_id:
            clauses.append("device_id = ?")
            params.append(device_id)

        if from_iso:
            clauses.append("start_ts >= ?")
            params.append(from_iso)

        if to_iso:
            clauses.append("start_ts <= ?")
            params.append(to_iso)

        if level in ("WARNING", "ALERT"):
            clauses.append("max_level = ?")
            params.append(level)
        elif level == "BOTH":
            clauses.append("max_level IN ('WARNING', 'ALERT')")

        if min_dur_ms is not None:
            clauses.append("duration_ms >= ?")
            params.append(min_dur_ms)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        cursor.execute(f"SELECT COUNT(*) AS total FROM episodes {where_sql}", tuple(params))
        total_count = cursor.fetchone()["total"]

        order_sql = f"ORDER BY start_ts {order.upper()}"
        cursor.execute(f"""
            SELECT id, device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms
            FROM episodes
            {where_sql}
            {order_sql}
            LIMIT ? OFFSET ?
        """, tuple(params + [limit, offset]))

        episodes = [dict(r) for r in cursor.fetchall()]
        return jsonify({
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "episodes": episodes,
        })
    finally:
        conn.close()


@app.route("/api/episodes/<int:ep_id>", methods=["GET"])
def get_episode_detail(ep_id):
    """Return single slouch episode with surrounding context series [-60s .. +60s]."""
    from backend.history_alerts import compute_episode_detail_context

    conn = get_db(DB_PATH)
    try:
        detail = compute_episode_detail_context(conn, ep_id, window_seconds=60)
        if not detail:
            return jsonify({"error": "Episode not found"}), 404
        return jsonify(detail)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# History and Alerts Endpoints
# ---------------------------------------------------------------------------
def _parse_common_history_params():
    """Extract and validate from, to, device_id, tz_offset_minutes."""
    from_iso = request.args.get("from")
    to_iso = request.args.get("to")
    device_id = request.args.get("device_id")
    tz_str = request.args.get("tz_offset_minutes", "0")

    try:
        tz_offset_minutes = int(tz_str)
        if tz_offset_minutes < -840 or tz_offset_minutes > 840:
            return None, "Invalid tz_offset_minutes (must be between -840 and +840)"
    except ValueError:
        return None, "tz_offset_minutes must be an integer"

    # Default to last 24 hours if not specified
    now = datetime.now(timezone.utc)
    if not to_iso:
        to_iso = now.isoformat()
    if not from_iso:
        from_iso = (now - timedelta(hours=24)).isoformat()

    return {
        "from_iso": from_iso,
        "to_iso": to_iso,
        "device_id": device_id,
        "tz_offset_minutes": tz_offset_minutes,
    }, None


@app.route("/api/history/bounds", methods=["GET"])
def api_history_bounds():
    """First and last timestamp, device list, and retention setting."""
    from backend.history_alerts import get_history_bounds

    conn = get_db(DB_PATH)
    try:
        bounds = get_history_bounds(conn)
        return jsonify(bounds)
    finally:
        conn.close()


@app.route("/api/history/summary", methods=["GET"])
def api_history_summary():
    """Summary metrics over time range."""
    params, err = _parse_common_history_params()
    if err:
        return jsonify({"error": err}), 400

    from backend.history_alerts import compute_history_summary, compute_sessions

    conn = get_db(DB_PATH)
    try:
        device_id = params["device_id"]
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        cursor.execute("""
            SELECT ts, state, is_standing, heart_rate_bpm, finger_present, temperature_c, humidity_pct
            FROM telemetry
            WHERE device_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        telemetry_rows = cursor.fetchall()

        cursor.execute("""
            SELECT id, duration_ms, start_ts, end_ts, max_level
            FROM episodes
            WHERE device_id = ? AND start_ts >= ? AND start_ts <= ?
            ORDER BY start_ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        episode_rows = cursor.fetchall()

        # Count continuous sessions
        sessions = compute_sessions(telemetry_rows, episode_rows, gap_s=60, tz_offset_minutes=params["tz_offset_minutes"])
        summary = compute_history_summary(telemetry_rows, episode_rows, sessions_count=len(sessions))
        summary["device_id"] = device_id
        return jsonify(summary)
    finally:
        conn.close()


@app.route("/api/history/timeline", methods=["GET"])
def api_history_timeline():
    """Downsampled series and run-length-encoded posture segments."""
    params, err = _parse_common_history_params()
    if err:
        return jsonify({"error": err}), 400

    try:
        max_points = max(10, min(5000, int(request.args.get("max_points", 800))))
    except ValueError:
        return jsonify({"error": "Invalid max_points parameter"}), 400

    from backend.history_alerts import compute_posture_segments, compute_timeline_series

    conn = get_db(DB_PATH)
    try:
        device_id = params["device_id"]
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        cursor.execute("""
            SELECT ts, imu_pitch_deg, heart_rate_bpm, finger_present, temperature_c, humidity_pct, state, is_standing
            FROM telemetry
            WHERE device_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        telemetry_rows = cursor.fetchall()

        segments = compute_posture_segments(telemetry_rows, max_gap_s=10)
        series, resolution_s = compute_timeline_series(telemetry_rows, max_points=max_points)

        return jsonify({
            "device_id": device_id,
            "resolution_s": resolution_s,
            "series": series,
            "segments": segments,
            "point_count": len(series),
        })
    finally:
        conn.close()


@app.route("/api/history/days", methods=["GET"])
def api_history_days():
    """One row per local day in the range."""
    params, err = _parse_common_history_params()
    if err:
        return jsonify({"error": err}), 400

    from backend.history_alerts import compute_local_days, compute_sessions

    conn = get_db(DB_PATH)
    try:
        device_id = params["device_id"]
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        cursor.execute("""
            SELECT ts, state, is_standing, heart_rate_bpm, finger_present
            FROM telemetry
            WHERE device_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        telemetry_rows = cursor.fetchall()

        cursor.execute("""
            SELECT id, duration_ms, start_ts, end_ts, max_level
            FROM episodes
            WHERE device_id = ? AND start_ts >= ? AND start_ts <= ?
            ORDER BY start_ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        episode_rows = cursor.fetchall()

        sessions = compute_sessions(telemetry_rows, episode_rows, gap_s=60, tz_offset_minutes=params["tz_offset_minutes"])
        days = compute_local_days(telemetry_rows, episode_rows, tz_offset_minutes=params["tz_offset_minutes"], sessions=sessions)

        return jsonify({
            "device_id": device_id,
            "tz_offset_minutes": params["tz_offset_minutes"],
            "days": days,
        })
    finally:
        conn.close()


@app.route("/api/sessions", methods=["GET"])
def api_sessions():
    """Continuous stretches of monitoring with gap <= gap_s."""
    params, err = _parse_common_history_params()
    if err:
        return jsonify({"error": err}), 400

    try:
        gap_s = max(10, min(600, int(request.args.get("gap_s", 60))))
    except ValueError:
        return jsonify({"error": "Invalid gap_s parameter"}), 400

    try:
        limit = max(1, min(200, int(request.args.get("limit", 50))))
    except ValueError:
        return jsonify({"error": "Invalid limit parameter"}), 400

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "Invalid offset parameter"}), 400

    from backend.history_alerts import compute_sessions

    conn = get_db(DB_PATH)
    try:
        device_id = params["device_id"]
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        cursor.execute("""
            SELECT ts, state, is_standing, heart_rate_bpm, finger_present
            FROM telemetry
            WHERE device_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        telemetry_rows = cursor.fetchall()

        cursor.execute("""
            SELECT id, duration_ms, start_ts, end_ts, max_level
            FROM episodes
            WHERE device_id = ? AND start_ts >= ? AND start_ts <= ?
            ORDER BY start_ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        episode_rows = cursor.fetchall()

        all_sessions = compute_sessions(telemetry_rows, episode_rows, gap_s=gap_s, tz_offset_minutes=params["tz_offset_minutes"])
        total_count = len(all_sessions)
        paged_sessions = all_sessions[offset : offset + limit]

        return jsonify({
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "sessions": paged_sessions,
        })
    finally:
        conn.close()


@app.route("/api/history/readings", methods=["GET"])
def api_history_readings():
    """Raw readings paginated."""
    params, err = _parse_common_history_params()
    if err:
        return jsonify({"error": err}), 400

    try:
        limit = max(1, min(500, int(request.args.get("limit", 50))))
    except ValueError:
        return jsonify({"error": "Invalid limit parameter"}), 400

    try:
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        return jsonify({"error": "Invalid offset parameter"}), 400

    order = request.args.get("order", "desc").lower()
    if order not in ("asc", "desc"):
        return jsonify({"error": "Invalid order parameter (must be 'asc' or 'desc')"}), 400

    from backend.history_alerts import paginate_readings

    conn = get_db(DB_PATH)
    try:
        device_id = params["device_id"]
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        res = paginate_readings(
            conn,
            device_id=device_id,
            from_iso=params["from_iso"],
            to_iso=params["to_iso"],
            tz_offset_minutes=params["tz_offset_minutes"],
            limit=limit,
            offset=offset,
            order=order,
        )
        return jsonify(res)
    finally:
        conn.close()


@app.route("/api/alerts/summary", methods=["GET"])
def api_alerts_summary():
    """Summary of slouches for range (counts, longest, 24h hourly bins, per-day)."""
    params, err = _parse_common_history_params()
    if err:
        return jsonify({"error": err}), 400

    from backend.history_alerts import compute_alerts_summary

    conn = get_db(DB_PATH)
    try:
        device_id = params["device_id"]
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        cursor.execute("""
            SELECT id, device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms
            FROM episodes
            WHERE device_id = ? AND start_ts >= ? AND start_ts <= ?
            ORDER BY start_ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        episode_rows = cursor.fetchall()

        summary = compute_alerts_summary(episode_rows, tz_offset_minutes=params["tz_offset_minutes"])
        summary["device_id"] = device_id
        return jsonify(summary)
    finally:
        conn.close()


@app.route("/api/history/export.csv", methods=["GET"])
def api_history_export_csv():
    """Export history readings as CSV with both local and UTC time columns."""
    params, err = _parse_common_history_params()
    if err:
        return jsonify({"error": err}), 400

    resolution = request.args.get("resolution", "auto")
    if resolution not in ("auto", "1", "5", "60"):
        return jsonify({"error": "Invalid resolution (must be 'auto', '1', '5', or '60')"}), 400

    from backend.history_alerts import export_history_csv

    conn = get_db(DB_PATH)
    try:
        device_id = params["device_id"]
        cursor = conn.cursor()
        if not device_id:
            cursor.execute("SELECT device_id FROM telemetry ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            device_id = row["device_id"] if row and row["device_id"] else "vest-01"

        cursor.execute("""
            SELECT * FROM telemetry
            WHERE device_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (device_id, params["from_iso"], params["to_iso"]))
        rows = cursor.fetchall()

        csv_content = export_history_csv(rows, tz_offset_minutes=params["tz_offset_minutes"], resolution=resolution)
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=posture_history_{device_id}.csv"},
        )
    finally:
        conn.close()


@app.route("/api/episodes/export.csv", methods=["GET"])
def api_episodes_export_csv():
    """Export filtered slouch episodes as CSV."""
    from_iso = request.args.get("from")
    to_iso = request.args.get("to")
    level = request.args.get("level")
    min_duration_s = request.args.get("min_duration_s")
    device_id = request.args.get("device_id")
    order = request.args.get("order", "desc").lower()
    tz_str = request.args.get("tz_offset_minutes", "0")

    try:
        tz_offset_minutes = int(tz_str)
    except ValueError:
        tz_offset_minutes = 0

    min_dur_ms = None
    if min_duration_s is not None:
        try:
            min_dur_ms = int(float(min_duration_s) * 1000)
        except ValueError:
            return jsonify({"error": "Invalid 'min_duration_s' parameter"}), 400

    from backend.history_alerts import export_episodes_csv

    conn = get_db(DB_PATH)
    try:
        cursor = conn.cursor()
        clauses = []
        params = []

        if device_id:
            clauses.append("device_id = ?")
            params.append(device_id)
        if from_iso:
            clauses.append("start_ts >= ?")
            params.append(from_iso)
        if to_iso:
            clauses.append("start_ts <= ?")
            params.append(to_iso)
        if level in ("WARNING", "ALERT"):
            clauses.append("max_level = ?")
            params.append(level)
        elif level == "BOTH":
            clauses.append("max_level IN ('WARNING', 'ALERT')")
        if min_dur_ms is not None:
            clauses.append("duration_ms >= ?")
            params.append(min_dur_ms)

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        order_sql = f"ORDER BY start_ts {order.upper() if order in ('asc', 'desc') else 'DESC'}"

        cursor.execute(f"SELECT * FROM episodes {where_sql} {order_sql}", tuple(params))
        episodes = cursor.fetchall()

        csv_content = export_episodes_csv(episodes, tz_offset_minutes=tz_offset_minutes)
        return Response(
            csv_content,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=slouch_alerts.csv"},
        )
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