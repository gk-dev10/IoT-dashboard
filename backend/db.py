"""Database connection, schema setup, and maintenance for Posture T-Shirt v2."""

import os
import sqlite3
from datetime import datetime, timezone

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "vest_v2.db")


def get_db(db_path=None):
    """Open a SQLite connection with WAL mode and row factory."""
    path = db_path or os.environ.get("VEST_DB_PATH", DEFAULT_DB_PATH)
    # Ensure directory exists
    db_dir = os.path.dirname(os.path.abspath(path))
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path=None, retention_days=None):
    """Initialize database tables, indexes, and prune old telemetry records."""
    if retention_days is None:
        try:
            retention_days = int(os.environ.get("VEST_RETENTION_DAYS", "7"))
        except ValueError:
            retention_days = 7

    conn = get_db(db_path)
    try:
        with conn:
            # 1. Telemetry table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    device_id TEXT,
                    fw TEXT,
                    uptime_s INTEGER,
                    state TEXT,
                    armed INTEGER,
                    muted INTEGER,
                    is_standing INTEGER,
                    moving INTEGER,
                    bend_detected INTEGER,
                    possible_bend INTEGER,
                    bend_duration_ms INTEGER,
                    imu_pitch_deg REAL,
                    imu_roll_deg REAL,
                    imu_says_bent INTEGER,
                    flex_upper REAL,
                    flex_lower REAL,
                    flex_says_bent INTEGER,
                    adxl_tilt_deg REAL,
                    vibration_active INTEGER,
                    buzzer_active INTEGER,
                    led_green INTEGER,
                    led_yellow INTEGER,
                    led_red INTEGER,
                    heart_rate_bpm INTEGER,
                    finger_present INTEGER,
                    temperature_c REAL,
                    humidity_pct REAL,
                    mpu_ok INTEGER,
                    adxl_ok INTEGER,
                    max_ok INTEGER,
                    flex_enabled INTEGER,
                    bend_on_deg REAL,
                    bend_off_deg REAL,
                    vibrate_delay_s REAL,
                    buzzer_delay_s REAL,
                    wifi_rssi INTEGER
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry(ts);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_device ON telemetry(device_id);")

            # 2. Episodes table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT,
                    start_ts TEXT NOT NULL,
                    end_ts TEXT,
                    max_level TEXT,
                    peak_pitch_deg REAL,
                    duration_ms INTEGER
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_start ON episodes(start_ts);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_device ON episodes(device_id);")

            # 3. Commands table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS commands (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_ts TEXT NOT NULL,
                    device_id TEXT,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    sent_ts TEXT
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_commands_status ON commands(status);")

            # Retention pruning: delete records older than retention_days
            if retention_days > 0:
                cutoff = datetime.now(timezone.utc).timestamp() - (retention_days * 86400)
                cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
                conn.execute("DELETE FROM telemetry WHERE ts < ?", (cutoff_iso,))
    finally:
        conn.close()
