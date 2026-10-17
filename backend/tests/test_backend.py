"""Unit tests for Posture T-Shirt v2 backend service."""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone, timedelta

# Set environment variables for testing before importing app
TEST_TOKEN = "test-secret-token"
os.environ["VEST_DEVICE_TOKEN"] = TEST_TOKEN


@pytest.fixture
def client():
    """Create a Flask test client with an isolated temporary SQLite database."""
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
        yield client

    if os.path.exists(temp_db):
        try:
            os.remove(temp_db)
        except Exception:
            pass


def test_health_check(client):
    """Verify /api/health returns 200 ok."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_token_rejection(client):
    """POST /api/data without valid X-Device-Token must return 401."""
    # No header
    resp = client.post("/api/data", json={"device_id": "vest-01"})
    assert resp.status_code == 401

    # Wrong token
    resp = client.post(
        "/api/data",
        headers={"X-Device-Token": "wrong-token"},
        json={"device_id": "vest-01"},
    )
    assert resp.status_code == 401


def test_ingest_valid_and_null_preservation(client):
    """POST /api/data accepts valid payload and keeps nulls without turning them into 0."""
    payload = {
        "device_id": "vest-01",
        "fw": "2.0.0",
        "uptime_s": 120,
        "state": "UPRIGHT",
        "armed": True,
        "muted": False,
        "is_standing": True,
        "moving": False,
        "bend_detected": False,
        "possible_bend": False,
        "bend_duration_ms": 0,
        "imu_pitch_deg": 4.5,
        "imu_roll_deg": -1.2,
        "imu_says_bent": False,
        "flex_upper": None,  # explicitly null
        "flex_lower": None,  # explicitly null
        "flex_says_bent": None,
        "adxl_tilt_deg": 12.0,
        "vibration_active": False,
        "buzzer_active": False,
        "led_green": True,
        "led_yellow": False,
        "led_red": False,
        "heart_rate_bpm": None,  # null reading
        "finger_present": False,
        "temperature_c": 24.5,
        "humidity_pct": 50.0,
        "mpu_ok": True,
        "adxl_ok": True,
        "max_ok": True,
        "flex_enabled": False,
        "bend_on_deg": 20.0,
        "bend_off_deg": 15.0,
        "vibrate_delay_s": 5.0,
        "buzzer_delay_s": 15.0,
        "wifi_rssi": -65,
    }

    resp = client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json=payload,
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "received_at" in data
    assert "commands" not in data  # No pending commands initially

    # Verify via /api/live
    live_resp = client.get("/api/live")
    assert live_resp.status_code == 200
    live_data = live_resp.get_json()
    assert live_data["online"] is True
    assert live_data["seconds_since_last"] is not None
    assert live_data["seconds_since_last"] < 2.0

    t = live_data["telemetry"]
    assert t["device_id"] == "vest-01"
    assert t["imu_pitch_deg"] == 4.5
    assert t["flex_upper"] is None
    assert t["heart_rate_bpm"] is None
    assert t["flex_enabled"] == 0


def test_command_validation_rules(client):
    """Test command validation rejection rules on POST /api/commands."""
    # 1. Calibrate valid
    r = client.post("/api/commands", json={"type": "calibrate"})
    assert r.status_code == 201
    assert r.get_json()["type"] == "calibrate"

    # 2. Mute valid
    r = client.post("/api/commands", json={"type": "mute", "seconds": 60})
    assert r.status_code == 201

    # 3. Mute invalid
    r = client.post("/api/commands", json={"type": "mute", "seconds": -5})
    assert r.status_code == 400

    # 4. Test valid
    r = client.post("/api/commands", json={"type": "test", "target": "buzzer"})
    assert r.status_code == 201

    # 5. Test invalid target
    r = client.post("/api/commands", json={"type": "test", "target": "radio"})
    assert r.status_code == 400

    # 6. Config valid
    r = client.post("/api/commands", json={
        "type": "config",
        "bend_on_deg": 25.0,
        "bend_off_deg": 20.0,
        "vibrate_delay_s": 4.0,
        "buzzer_delay_s": 12.0,
    })
    assert r.status_code == 201

    # 7. Config out of range: bend_on_deg > 60
    r = client.post("/api/commands", json={"type": "config", "bend_on_deg": 75.0})
    assert r.status_code == 400

    # 8. Config invalid: bend_off_deg > bend_on_deg - 2
    r = client.post("/api/commands", json={
        "type": "config",
        "bend_on_deg": 20.0,
        "bend_off_deg": 19.5,
    })
    assert r.status_code == 400

    # 9. Config invalid: buzzer_delay_s <= vibrate_delay_s
    r = client.post("/api/commands", json={
        "type": "config",
        "vibrate_delay_s": 10.0,
        "buzzer_delay_s": 8.0,
    })
    assert r.status_code == 400


def test_command_merging_and_one_shot_delivery(client):
    """Test that multiple pending commands are merged and delivered exactly once."""
    # Post calibrate
    client.post("/api/commands", json={"type": "calibrate"})
    # Post mute 30s
    client.post("/api/commands", json={"type": "mute", "seconds": 30})
    # Post test buzzer
    client.post("/api/commands", json={"type": "test", "target": "buzzer"})
    # Post config
    client.post("/api/commands", json={"type": "config", "bend_on_deg": 22.0, "bend_off_deg": 18.0})

    # Device ingests telemetry
    r1 = client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "UPRIGHT"},
    )
    assert r1.status_code == 201
    resp1 = r1.get_json()
    assert "commands" in resp1
    cmds = resp1["commands"]
    assert cmds["calibrate"] is True
    assert cmds["mute_s"] == 30
    assert cmds["test"] == "buzzer"
    assert cmds["config"] == {"bend_on_deg": 22.0, "bend_off_deg": 18.0}

    # Second ingest: commands must now be gone (one-shot delivery!)
    r2 = client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "UPRIGHT"},
    )
    assert r2.status_code == 201
    resp2 = r2.get_json()
    assert "commands" not in resp2


def test_command_expiration(client):
    """Pending commands older than 60s must expire and not be delivered."""
    from backend import db as db_module

    # Insert a stale command directly with an old timestamp
    conn = db_module.get_db()
    old_time = (datetime.now(timezone.utc) - timedelta(seconds=70)).isoformat()
    conn.execute("""
        INSERT INTO commands (created_ts, device_id, type, payload_json, status, sent_ts)
        VALUES (?, 'vest-01', 'calibrate', '{"type": "calibrate"}', 'pending', NULL)
    """, (old_time,))
    conn.commit()
    conn.close()

    # Device posts data
    r = client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "UPRIGHT"},
    )
    assert r.status_code == 201
    resp = r.get_json()
    # Expired command must NOT be delivered
    assert "commands" not in resp

    # Check status in /api/live
    live_data = client.get("/api/live").get_json()
    cmd = live_data["commands"][0]
    assert cmd["status"] == "expired"


def test_episode_tracking_and_peak_pitch(client):
    """Test that bend episodes open, escalate max level, track peak pitch, and close properly."""
    # 1. Normal upright telemetry
    client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "UPRIGHT", "imu_pitch_deg": 5.0},
    )
    episodes = client.get("/api/episodes").get_json()
    assert len(episodes) == 0

    # 2. Wearer starts bending -> enters WARNING at 22°
    client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "WARNING", "imu_pitch_deg": 22.0, "bend_duration_ms": 5000},
    )
    episodes = client.get("/api/episodes").get_json()
    assert len(episodes) == 1
    assert episodes[0]["end_ts"] is None  # open
    assert episodes[0]["max_level"] == "WARNING"
    assert episodes[0]["peak_pitch_deg"] == 22.0

    # 3. Bending continues -> escalates to ALERT at 28.5°
    client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "ALERT", "imu_pitch_deg": 28.5, "bend_duration_ms": 15000},
    )
    episodes = client.get("/api/episodes").get_json()
    assert len(episodes) == 1
    assert episodes[0]["end_ts"] is None
    assert episodes[0]["max_level"] == "ALERT"
    assert episodes[0]["peak_pitch_deg"] == 28.5

    # 4. Straightens up -> back to UPRIGHT
    client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "UPRIGHT", "imu_pitch_deg": 4.0, "bend_duration_ms": 0},
    )
    episodes = client.get("/api/episodes").get_json()
    assert len(episodes) == 1
    assert episodes[0]["end_ts"] is not None  # closed!
    assert episodes[0]["max_level"] == "ALERT"
    assert episodes[0]["peak_pitch_deg"] == 28.5
    assert episodes[0]["duration_ms"] >= 15000


def test_history_downsampling(client):
    """Test /api/history query and downsampling."""
    # Insert 50 rows
    for i in range(50):
        client.post(
            "/api/data",
            headers={"X-Device-Token": TEST_TOKEN},
            json={"device_id": "vest-01", "state": "UPRIGHT", "imu_pitch_deg": float(i)},
        )

    # Request all
    r = client.get("/api/history?minutes=10&limit=100")
    assert r.status_code == 200
    rows = r.get_json()
    assert len(rows) == 50

    # Request with downsampling limit=10
    r_down = client.get("/api/history?minutes=10&limit=10")
    assert r_down.status_code == 200
    rows_down = r_down.get_json()
    assert len(rows_down) == 10
    # Latest item preserved
    assert rows_down[-1]["imu_pitch_deg"] == 49.0


def test_stats_calculation(client):
    """Test /api/stats calculation on real sample distribution."""
    # Ingest standing upright
    client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "UPRIGHT", "is_standing": True, "heart_rate_bpm": 70},
    )
    # Ingest standing warning
    client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "WARNING", "is_standing": True, "heart_rate_bpm": 80, "bend_duration_ms": 6000},
    )
    # Ingest sitting upright
    client.post(
        "/api/data",
        headers={"X-Device-Token": TEST_TOKEN},
        json={"device_id": "vest-01", "state": "UPRIGHT", "is_standing": False, "heart_rate_bpm": 72},
    )

    stats = client.get("/api/stats?hours=1").get_json()
    assert stats["total_samples"] == 3
    assert stats["percent_time_stooped"] == pytest.approx(33.3, 0.1)
    assert stats["percent_standing"] == pytest.approx(66.7, 0.1)
    assert stats["percent_sitting"] == pytest.approx(33.3, 0.1)
    assert stats["avg_heart_rate_bpm"] == pytest.approx(74.0, 0.1)
