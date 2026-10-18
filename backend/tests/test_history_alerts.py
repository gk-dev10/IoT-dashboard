"""Unit tests for History and Alerts endpoints, calculations, and timezone behavior."""

from datetime import datetime, timedelta, timezone
import io
import json
import os
import tempfile
import pytest
from backend.db import get_db

TEST_TOKEN = "test-secret-token"
os.environ["VEST_DEVICE_TOKEN"] = TEST_TOKEN


@pytest.fixture
def client_and_db():
    """Create Flask test client with clean isolated DB."""
    fd, temp_db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["VEST_DB_PATH"] = temp_db

    from backend import app as backend_module
    backend_module.DB_PATH = temp_db
    backend_module.DEVICE_TOKEN = TEST_TOKEN
    backend_module.init_db(temp_db)

    app = backend_module.app
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client, temp_db

    if os.path.exists(temp_db):
        try:
            os.remove(temp_db)
        except Exception:
            pass


def insert_row(db_path, t_iso, state="UPRIGHT", is_standing=1, pitch=5.0, hr=75.0, temp=24.0, hum=50.0, dev="vest-01"):
    from backend.db import get_db
    conn = get_db(db_path)
    with conn:
        conn.execute("""
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
                ?, ?, '2.1.0-test', 100, ?, 1, 0, ?,
                0, ?, 0, 0,
                ?, 0.0, 0, NULL,
                NULL, 0, 10.0, 0,
                0, 1, 0, 0, ?,
                ?, ?, ?, 1, 1,
                1, 0, 20.0, 15.0,
                5.0, 15.0, -65
            )
        """, (
            t_iso, dev, state, is_standing,
            1 if state in ("WARNING", "ALERT") else 0,
            pitch, hr, 1 if hr is not None else 0, temp, hum
        ))
    conn.close()


def test_bounds_empty_and_populated(client_and_db):
    client, db_path = client_and_db
    # Empty DB
    resp = client.get("/api/history/bounds")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["first_ts"] is None
    assert data["last_ts"] is None
    assert data["total_rows"] == 0
    assert data["devices"] == []
    assert data["retention_days"] == 7

    # Insert rows with simulated device
    insert_row(db_path, "2026-10-18T10:00:00+00:00", dev="sim-vest-01")
    insert_row(db_path, "2026-10-18T10:00:05+00:00", dev="sim-vest-01")
    resp = client.get("/api/history/bounds")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total_rows"] == 2
    assert data["first_ts"] == "2026-10-18T10:00:00+00:00"
    assert data["last_ts"] == "2026-10-18T10:00:05+00:00"
    assert len(data["devices"]) == 1
    assert data["devices"][0]["device_id"] == "sim-vest-01"
    assert data["devices"][0]["simulated"] is True


def test_history_summary_insufficient_data(client_and_db):
    client, db_path = client_and_db
    # Under 12 samples (< 60s) returns null for averages/percents
    for i in range(5):
        insert_row(db_path, f"2026-10-18T10:00:0{i}+00:00", state="UPRIGHT")

    resp = client.get("/api/history/summary?from=2026-10-18T09:00:00Z&to=2026-10-18T11:00:00Z")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["monitored_seconds"] == 5
    assert data["good_posture_percent"] is None
    assert data["avg_heart_rate_bpm"] is None
    assert data["avg_temp_c"] is None


def test_history_summary_known_dataset(client_and_db):
    client, db_path = client_and_db
    # Insert 60 upright, 20 sitting, 10 warning, 10 alert = 100 samples
    for i in range(60):
        insert_row(db_path, f"2026-10-18T10:00:{i:02d}+00:00", state="UPRIGHT", is_standing=1, hr=70.0, temp=22.0, hum=45.0)
    for i in range(20):
        insert_row(db_path, f"2026-10-18T10:01:{i:02d}+00:00", state="UPRIGHT", is_standing=0, hr=65.0, temp=22.0, hum=45.0)
    for i in range(10):
        insert_row(db_path, f"2026-10-18T10:01:{20+i:02d}+00:00", state="WARNING", is_standing=1, hr=80.0, temp=22.0, hum=45.0)
    for i in range(10):
        insert_row(db_path, f"2026-10-18T10:01:{30+i:02d}+00:00", state="ALERT", is_standing=1, hr=85.0, temp=22.0, hum=45.0)

    resp = client.get("/api/history/summary?from=2026-10-18T09:00:00Z&to=2026-10-18T11:00:00Z")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["monitored_seconds"] == 100
    assert d["time_per_category"]["UPRIGHT"] == 60
    assert d["time_per_category"]["SITTING"] == 20
    assert d["time_per_category"]["WARNING"] == 10
    assert d["time_per_category"]["ALERT"] == 10
    # Good posture of standing time: 60 / (60 + 10 + 10) = 75.0%
    assert d["good_posture_percent"] == 75.0
    assert d["avg_temp_c"] == 22.0
    assert d["avg_hum_pct"] == 45.0


def test_history_summary_only_sitting_returns_null_good_posture(client_and_db):
    client, db_path = client_and_db
    # 100 samples of sitting only
    for i in range(100):
        insert_row(db_path, f"2026-10-18T10:00:{i:02d}+00:00", state="UPRIGHT", is_standing=0)

    resp = client.get("/api/history/summary?from=2026-10-18T09:00:00Z&to=2026-10-18T11:00:00Z")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["monitored_seconds"] == 100
    assert d["good_posture_percent"] is None


def test_episodes_backward_compatibility(client_and_db):
    client, db_path = client_and_db
    conn = get_db(db_path)
    conn.execute("""
        INSERT INTO episodes (device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms)
        VALUES ('vest-01', '2026-10-18T10:00:00+00:00', '2026-10-18T10:00:20+00:00', 'ALERT', 25.0, 20000)
    """)
    conn.commit()

    # Call with NO parameters
    resp = client.get("/api/episodes")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["max_level"] == "ALERT"

    # Call with ONLY limit parameter
    resp_limit = client.get("/api/episodes?limit=5")
    assert resp_limit.status_code == 200
    data_limit = resp_limit.get_json()
    assert isinstance(data_limit, list)
    assert len(data_limit) == 1


def test_timezone_handling_days_and_hours(client_and_db):
    client, db_path = client_and_db
    # A reading at 23:50 UTC on 2026-10-17 with tz_offset_minutes=330 (+5:30 India)
    # 23:50 UTC + 5:30 = 05:20 on 2026-10-18!
    for i in range(15):
        insert_row(db_path, f"2026-10-17T23:50:{i:02d}+00:00", state="UPRIGHT")

    # Call /api/history/days with tz_offset_minutes=330
    resp = client.get("/api/history/days?from=2026-10-17T00:00:00Z&to=2026-10-18T23:59:59Z&tz_offset_minutes=330")
    assert resp.status_code == 200
    days_data = resp.get_json()["days"]
    assert len(days_data) == 1
    # Local day must be 2026-10-18, not 2026-10-17!
    assert days_data[0]["date"] == "2026-10-18"


def test_timeline_segments_and_gaps(client_and_db):
    client, db_path = client_and_db
    # Series of 5 UPRIGHT, then 3 WARNING, then gap of 20 seconds, then 5 ALERT
    for i in range(5):
        insert_row(db_path, f"2026-10-18T10:00:0{i}+00:00", state="UPRIGHT")
    for i in range(5, 8):
        insert_row(db_path, f"2026-10-18T10:00:0{i}+00:00", state="WARNING")
    # Gap: skip from 07 to 30s
    for i in range(30, 35):
        insert_row(db_path, f"2026-10-18T10:00:{i}+00:00", state="ALERT")

    resp = client.get("/api/history/timeline?from=2026-10-18T09:59:00Z&to=2026-10-18T10:05:00Z")
    assert resp.status_code == 200
    data = resp.get_json()
    segments = data["segments"]
    # Should have 3 segments: UPRIGHT, WARNING, and ALERT across the gap
    assert len(segments) == 3
    assert segments[0]["cat"] == "UPRIGHT"
    assert segments[1]["cat"] == "WARNING"
    assert segments[2]["cat"] == "ALERT"


def test_sessions_split_at_gap(client_and_db):
    client, db_path = client_and_db
    # Cluster 1: 10:00:00 to 10:00:30 (30s)
    for i in range(30):
        insert_row(db_path, f"2026-10-18T10:00:{i:02d}+00:00")
    # Gap: 2 minutes
    # Cluster 2: 10:02:30 to 10:03:00 (30s)
    for i in range(30):
        insert_row(db_path, f"2026-10-18T10:02:{30+i:02d}+00:00")

    resp = client.get("/api/sessions?from=2026-10-18T09:00:00Z&to=2026-10-18T11:00:00Z&gap_s=60")
    assert resp.status_code == 200
    sessions_data = resp.get_json()
    assert sessions_data["total"] == 2
    assert len(sessions_data["sessions"]) == 2


def test_episodes_filters_and_context(client_and_db):
    client, db_path = client_and_db
    from backend.db import get_db
    conn = get_db(db_path)
    with conn:
        conn.execute("""
            INSERT INTO episodes (id, device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms)
            VALUES (1, 'vest-01', '2026-10-18T10:00:00Z', '2026-10-18T10:00:15Z', 'WARNING', 22.5, 15000),
                   (2, 'vest-01', '2026-10-18T10:05:00Z', '2026-10-18T10:05:40Z', 'ALERT', 28.0, 40000)
        """)
    conn.close()

    # Search endpoint
    resp = client.get("/api/episodes/search?level=ALERT")
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 1
    assert resp.get_json()["episodes"][0]["max_level"] == "ALERT"

    # Filter by duration >= 30s
    resp = client.get("/api/episodes?min_duration_s=30")
    assert resp.status_code == 200
    # Backward compat rich shape when min_duration_s is provided
    assert resp.get_json()["total"] == 1
    assert resp.get_json()["episodes"][0]["id"] == 2

    # Episode detail context
    resp = client.get("/api/episodes/2")
    assert resp.status_code == 200
    det = resp.get_json()
    assert det["id"] == 2
    assert "context_series" in det
    assert "moments" in det


def test_csv_exports(client_and_db):
    client, db_path = client_and_db
    insert_row(db_path, "2026-10-18T10:00:00+00:00", state="UPRIGHT", pitch=4.2, hr=72.0)
    insert_row(db_path, "2026-10-18T10:00:01+00:00", state="ALERT", pitch=25.0, hr=None)

    resp = client.get("/api/history/export.csv?from=2026-10-18T09:00:00Z&to=2026-10-18T11:00:00Z&tz_offset_minutes=330")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    csv_text = resp.data.decode("utf-8")
    lines = csv_text.strip().split("\n")
    # Verify header contains local time and UTC time
    assert "local_time" in lines[0]
    assert "utc_time" in lines[0]
    assert len(lines) == 3 # Header + 2 data rows


def test_invalid_parameters_return_400(client_and_db):
    client, db_path = client_and_db
    # Invalid tz_offset_minutes
    resp = client.get("/api/history/summary?tz_offset_minutes=9999")
    assert resp.status_code == 400

    # Invalid max_points
    resp = client.get("/api/history/timeline?max_points=invalid")
    assert resp.status_code == 400

    # Invalid episode level
    resp = client.get("/api/episodes/search?level=SUPER_CRITICAL")
    assert resp.status_code == 400


def test_episode_warning_to_alert_lifecycle(client_and_db):
    """A bend that goes WARNING then ALERT creates exactly one episode with max_level = 'ALERT'."""
    client, db_path = client_and_db
    conn = get_db(db_path)
    from backend.episodes import process_episode_transition

    # 1. Starts UPRIGHT
    process_episode_transition(conn, "vest-test", "UPRIGHT", 5.0, 0, "2026-10-18T10:00:00+00:00")
    # 2. Enters WARNING
    process_episode_transition(conn, "vest-test", "WARNING", 22.0, 5000, "2026-10-18T10:00:05+00:00")
    # 3. Escalates to ALERT
    process_episode_transition(conn, "vest-test", "ALERT", 26.0, 15000, "2026-10-18T10:00:15+00:00")
    # 4. Returns to UPRIGHT (concluding the episode)
    process_episode_transition(conn, "vest-test", "UPRIGHT", 4.0, 0, "2026-10-18T10:00:20+00:00")

    cursor = conn.cursor()
    cursor.execute("SELECT * FROM episodes WHERE device_id = 'vest-test'")
    eps = cursor.fetchall()
    assert len(eps) == 1, "Exactly one episode should be created across WARNING -> ALERT transition"
    ep = eps[0]
    assert ep["max_level"] == "ALERT"
    assert ep["peak_pitch_deg"] == 26.0
    assert ep["duration_ms"] >= 15000


def test_no_overlapping_episodes_and_duration_bounds(client_and_db):
    """For the same device, no two episodes overlap, and total slouch time <= monitored time."""
    client, db_path = client_and_db
    from tools.seed_demo_data import generate_seed_data
    generate_seed_data(days=2, device_id="sim-vest-01", effects=True, seed=99, clear_sim=True, db_path=db_path)

    conn = get_db(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e1.id, e1.start_ts, e1.end_ts, e2.id, e2.start_ts, e2.end_ts
        FROM episodes e1
        JOIN episodes e2 ON e1.device_id = e2.device_id AND e1.id != e2.id
        WHERE (e1.start_ts < e2.end_ts AND e1.end_ts > e2.start_ts)
    """)
    overlaps = cursor.fetchall()
    assert len(overlaps) == 0, f"Found overlapping episodes: {overlaps}"

    cursor.execute("SELECT SUM(duration_ms) / 1000.0 FROM episodes WHERE device_id = 'sim-vest-01'")
    total_slouch_s = cursor.fetchone()[0] or 0.0
    cursor.execute("SELECT COUNT(*) FROM telemetry WHERE device_id = 'sim-vest-01'")
    monitored_s = cursor.fetchone()[0] or 0

    assert total_slouch_s <= monitored_s, f"Total slouch time {total_slouch_s}s exceeded monitored time {monitored_s}s"
