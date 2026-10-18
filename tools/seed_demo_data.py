#!/usr/bin/env python3
"""
Seed synthetic demo telemetry and episode data directly into SQLite.

Supports:
- --minutes (default 120)
- --device-id (default sim-vest-01)
- --effects / --no-effects (default effects on)
- --seed (default 42)
- --clear-sim (delete existing rows for sim- devices first)
"""

import argparse
from datetime import datetime, timedelta, timezone
import math
import os
import random
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from backend.db import DEFAULT_DB_PATH, get_db, init_db


def parse_args():
    parser = argparse.ArgumentParser(description="Seed synthetic posture & vitals demo data")
    parser.add_argument("--minutes", type=int, default=120, help="Number of minutes of history to generate")
    parser.add_argument("--device-id", default="sim-vest-01", help="Device ID to tag telemetry with")
    parser.add_argument("--effects", dest="effects", action="store_true", default=True, help="Simulate posture impact on HR")
    parser.add_argument("--no-effects", dest="effects", action="store_false", help="Generate posture and HR independently (control data)")
    parser.add_argument("--seed", type=int, default=42, help="Random number generator seed")
    parser.add_argument("--clear-sim", action="store_true", help="Delete existing telemetry and episodes for sim- devices")
    parser.add_argument("--db-path", default=None, help="Database file path override")
    return parser.parse_args()


def generate_seed_data(minutes=120, device_id="sim-vest-01", effects=True, seed=42, clear_sim=False, db_path=None):
    random.seed(seed)
    db = db_path or os.environ.get("VEST_DB_PATH", DEFAULT_DB_PATH)
    init_db(db)
    conn = get_db(db)

    try:
        with conn:
            if clear_sim:
                conn.execute("DELETE FROM telemetry WHERE device_id LIKE 'sim-%'")
                conn.execute("DELETE FROM episodes WHERE device_id LIKE 'sim-%'")
            elif device_id:
                conn.execute("DELETE FROM telemetry WHERE device_id = ?", (device_id,))
                conn.execute("DELETE FROM episodes WHERE device_id = ?", (device_id,))

            total_seconds = max(60, minutes * 60)
            now_dt = datetime.now(timezone.utc)
            start_dt = now_dt - timedelta(seconds=total_seconds)

            telemetry_rows = []
            episodes = []

            # Baseline state
            hr_baseline = 72.0
            temp_baseline = 24.5
            hum_baseline = 52.0

            bend_on_deg = 20.0
            bend_off_deg = 15.0
            vibrate_delay_s = 5.0
            buzzer_delay_s = 15.0

            # State machine tracking
            current_episode = None

            # Generate cycle of postures (approx 120s per complete cycle)
            for s in range(total_seconds):
                t_dt = start_dt + timedelta(seconds=s)
                t_iso = t_dt.isoformat()
                cycle_s = s % 120

                # 1. Posture state & kinematics
                if cycle_s < 50:
                    # Upright standing
                    is_standing = True
                    moving = random.random() < 0.12
                    adxl_tilt = 8.0 + (random.random() - 0.5) * 2.0
                    imu_pitch = 3.5 + (random.random() - 0.5) * 2.0
                    state = "UPRIGHT"
                    bend_duration_ms = 0

                elif cycle_s < 80:
                    # Forward bend episode (lasts 30s)
                    is_standing = True
                    moving = False
                    bend_elapsed = cycle_s - 50
                    bend_duration_ms = bend_elapsed * 1000

                    # Ramps up smoothly
                    progress = min(1.0, bend_elapsed / 12.0)
                    target_pitch = 20.0 + progress * 7.5 + (random.random() - 0.5) * 1.5
                    imu_pitch = target_pitch
                    adxl_tilt = 12.0 + (random.random() - 0.5) * 2.0

                    if bend_elapsed >= buzzer_delay_s:
                        state = "ALERT"
                    elif bend_elapsed >= vibrate_delay_s:
                        state = "WARNING"
                    else:
                        state = "UPRIGHT"

                else:
                    # Sitting posture (40s)
                    is_standing = False
                    moving = random.random() < 0.08
                    adxl_tilt = 84.0 + (random.random() - 0.5) * 2.0
                    imu_pitch = 6.0 + (random.random() - 0.5) * 2.0
                    state = "UPRIGHT"
                    bend_duration_ms = 0

                # 2. Episode boundaries
                if state in ("WARNING", "ALERT"):
                    if current_episode is None:
                        current_episode = {
                            "device_id": device_id,
                            "start_ts": t_iso,
                            "end_ts": None,
                            "max_level": state,
                            "peak_pitch_deg": imu_pitch,
                            "duration_ms": bend_duration_ms,
                        }
                    else:
                        if state == "ALERT":
                            current_episode["max_level"] = "ALERT"
                        current_episode["peak_pitch_deg"] = max(current_episode["peak_pitch_deg"], imu_pitch)
                        current_episode["duration_ms"] = bend_duration_ms
                else:
                    if current_episode is not None:
                        current_episode["end_ts"] = t_iso
                        episodes.append(current_episode)
                        current_episode = None

                # 3. Environmental DHT11 readings
                # Temperature drifts +1 C per hour with 0.5 C quantization
                hour_fraction = s / 3600.0
                raw_temp = temp_baseline + hour_fraction * 1.1 + (random.random() - 0.5) * 0.3
                temp_c = round(raw_temp * 2.0) / 2.0  # 0.5 C resolution

                # Humidity moves slightly opposite with 1% quantization, updated every 5s
                raw_hum = hum_baseline - hour_fraction * 1.5 + (random.random() - 0.5) * 0.8
                hum_pct = float(round(raw_hum))

                # 4. Heart Rate dynamics
                # Base random walk
                hr_walk = math.sin(s / 60.0) * 2.0 + (random.random() - 0.5) * 2.0

                if effects:
                    # With effects:
                    # +4 to +10 bpm during bends (rising over ~10s)
                    # -3 to -6 bpm while sitting
                    posture_hr_offset = 0.0
                    if cycle_s >= 50 and cycle_s < 80:
                        bend_time = cycle_s - 50
                        rise = min(1.0, bend_time / 10.0)
                        posture_hr_offset = 4.0 + rise * 5.0
                    elif cycle_s >= 80:
                        posture_hr_offset = -4.5

                    # Extra noise if moving
                    move_noise = (random.random() - 0.5) * 5.0 if moving else 0.0
                    calculated_hr = int(round(hr_baseline + hr_walk + posture_hr_offset + move_noise))
                else:
                    # Without effects (control dataset):
                    # Heart rate generated completely independent of posture
                    move_noise = (random.random() - 0.5) * 3.0 if moving else 0.0
                    calculated_hr = int(round(hr_baseline + hr_walk + move_noise))

                # About 10% null or finger off
                finger_present = random.random() > 0.10
                heart_rate_bpm = calculated_hr if finger_present else None

                # Actuators
                vib_active = state in ("WARNING", "ALERT")
                buz_active = state == "ALERT"
                led_green = state == "UPRIGHT"
                led_yellow = state == "WARNING"
                led_red = state == "ALERT"

                telemetry_rows.append((
                    t_iso, device_id, "2.1.0-sim", s, state, 1, 0,
                    1 if is_standing else 0,
                    1 if moving else 0,
                    1 if state in ("WARNING", "ALERT") else 0,
                    0, bend_duration_ms,
                    round(imu_pitch, 2), 0.5,
                    1 if imu_pitch >= bend_on_deg else 0,
                    None, None, None,
                    round(adxl_tilt, 2),
                    1 if vib_active else 0,
                    1 if buz_active else 0,
                    1 if led_green else 0,
                    1 if led_yellow else 0,
                    1 if led_red else 0,
                    heart_rate_bpm,
                    1 if finger_present else 0,
                    temp_c, hum_pct,
                    1, 1, 1, 0,
                    bend_on_deg, bend_off_deg,
                    vibrate_delay_s, buzzer_delay_s,
                    -60
                ))

            # Close dangling episode if any
            if current_episode is not None:
                current_episode["end_ts"] = now_dt.isoformat()
                episodes.append(current_episode)

            # Insert batch telemetry
            conn.executemany("""
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
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?
                )
            """, telemetry_rows)

            # Insert batch episodes
            for ep in episodes:
                conn.execute("""
                    INSERT INTO episodes (device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    ep["device_id"], ep["start_ts"], ep["end_ts"], ep["max_level"],
                    round(ep["peak_pitch_deg"], 2), ep["duration_ms"]
                ))

        print(f"Successfully seeded {len(telemetry_rows)} telemetry rows and {len(episodes)} episodes for device '{device_id}' (effects={'ON' if effects else 'OFF'}).")

    finally:
        conn.close()


if __name__ == "__main__":
    args = parse_args()
    generate_seed_data(
        minutes=args.minutes,
        device_id=args.device_id,
        effects=args.effects,
        seed=args.seed,
        clear_sim=args.clear_sim,
        db_path=args.db_path,
    )
