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
    parser.add_argument("--minutes", type=int, default=None, help="Number of minutes of history to generate (overrides --days if specified)")
    parser.add_argument("--days", type=int, default=1, help="Number of days of history to generate with multi-session daytime schedule (default 1)")
    parser.add_argument("--device-id", default="sim-vest-01", help="Device ID to tag telemetry with")
    parser.add_argument("--effects", dest="effects", action="store_true", default=True, help="Simulate posture impact on HR")
    parser.add_argument("--no-effects", dest="effects", action="store_false", help="Generate posture and HR independently (control data)")
    parser.add_argument("--seed", type=int, default=42, help="Random number generator seed")
    parser.add_argument("--clear-sim", action="store_true", help="Delete existing telemetry and episodes for sim- devices")
    parser.add_argument("--tz-offset-minutes", type=int, default=330, help="Local timezone offset in minutes (default 330 for UTC+5:30)")
    parser.add_argument("--db-path", default=None, help="Database file path override")
    return parser.parse_args()


def generate_seed_data(minutes=None, days=1, device_id="sim-vest-01", effects=True, seed=42, clear_sim=False, tz_offset_minutes=330, db_path=None):
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

            telemetry_rows = []
            episodes = []

            now_dt = datetime.now(timezone.utc)
            tz_delta = timedelta(minutes=tz_offset_minutes)

            # Determine session intervals: list of (session_start_dt, session_duration_s)
            session_intervals = []
            if minutes is not None:
                total_s = max(60, minutes * 60)
                session_intervals.append((now_dt - timedelta(seconds=total_s), total_s))
            else:
                num_days = max(1, days)
                local_now = now_dt + tz_delta
                local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)

                for d in range(num_days - 1, -1, -1):
                    day_local_base = local_midnight - timedelta(days=d)
                    schedule_hours = [9.5, 13.0, 16.5]
                    if d == 0:
                        # For today, schedule daytime sessions that have already occurred
                        for h in schedule_hours:
                            s_start_local = day_local_base + timedelta(hours=h) + timedelta(minutes=random.randint(-15, 15))
                            dur_s = random.randint(25, 60) * 60
                            s_start_utc = s_start_local - tz_delta
                            if s_start_utc + timedelta(seconds=dur_s) < now_dt:
                                session_intervals.append((s_start_utc, dur_s))
                            elif s_start_utc < now_dt:
                                cur_dur = int((now_dt - s_start_utc).total_seconds())
                                if cur_dur > 60:
                                    session_intervals.append((s_start_utc, cur_dur))
                        # Always ensure there is a recent session ending right now
                        recent_dur = min(45 * 60, 3600)
                        recent_start = now_dt - timedelta(seconds=recent_dur)
                        if not session_intervals or session_intervals[-1][0] + timedelta(seconds=session_intervals[-1][1]) < recent_start:
                            session_intervals.append((recent_start, recent_dur))
                    else:
                        for h in schedule_hours:
                            s_start_local = day_local_base + timedelta(hours=h) + timedelta(minutes=random.randint(-20, 20))
                            dur_s = random.randint(30, 80) * 60
                            s_start_utc = s_start_local - tz_delta
                            session_intervals.append((s_start_utc, dur_s))

            # Baseline parameters
            bend_on_deg = 20.0
            bend_off_deg = 15.0
            vibrate_delay_s = 5.0
            buzzer_delay_s = 15.0

            hr_baseline = 72.0
            temp_baseline = 24.5
            hum_baseline = 52.0

            for session_idx, (sess_start, sess_dur) in enumerate(session_intervals):
                current_episode = None
                slouch_prob_mod = 0.8 + 0.5 * (session_idx % 3)

                for s in range(sess_dur):
                    t_dt = sess_start + timedelta(seconds=s)
                    t_iso = t_dt.isoformat()
                    cycle_s = s % 150
                    cycle_idx = s // 150

                    # Deterministically decide whether this cycle has a slouch event
                    # This prevents random per-second flickering between states
                    has_slouch = (((cycle_idx * 17 + session_idx * 11) % 100) / 100.0) < (0.85 * slouch_prob_mod)

                    # 1. Posture state & kinematics
                    if cycle_s < 70 or not has_slouch:
                        # Upright standing or sitting
                        is_standing = (s % 300) < 180
                        moving = random.random() < 0.10
                        adxl_tilt = 8.0 + (random.random() - 0.5) * 2.0 if is_standing else 45.0
                        imu_pitch = 3.5 + (random.random() - 0.5) * 2.0
                        state = "UPRIGHT"
                        bend_duration_ms = 0

                    elif cycle_s < 105:
                        # Determine slouch duration for this cycle:
                        # Short warning slouch (duration 10s: corrected before buzzer) vs long alert slouch (duration 35s)
                        is_short_slouch = (cycle_idx % 3) == 0
                        slouch_max_dur = 11 if is_short_slouch else 35
                        bend_elapsed = cycle_s - 70

                        if bend_elapsed < slouch_max_dur:
                            is_standing = True
                            moving = False
                            bend_duration_ms = bend_elapsed * 1000

                            progress = min(1.0, bend_elapsed / 12.0)
                            target_pitch = 20.0 + progress * 8.0 + (random.random() - 0.5) * 1.5
                            imu_pitch = target_pitch
                            adxl_tilt = 10.0

                            if bend_elapsed >= buzzer_delay_s:
                                state = "ALERT"
                            elif bend_elapsed >= vibrate_delay_s:
                                state = "WARNING"
                            else:
                                state = "UPRIGHT"
                        else:
                            # Promptly straightened up!
                            is_standing = True
                            moving = False
                            imu_pitch = 3.5 + (random.random() - 0.5) * 1.5
                            adxl_tilt = 8.0
                            state = "UPRIGHT"
                            bend_duration_ms = 0
                    else:
                        # Sitting upright
                        is_standing = False
                        moving = random.random() < 0.08
                        adxl_tilt = 48.0 + (random.random() - 0.5) * 2.0
                        imu_pitch = 4.0 + (random.random() - 0.5) * 1.5
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
                        if cycle_s >= 70 and cycle_s < 105:
                            bend_time = cycle_s - 70
                            rise = min(1.0, bend_time / 10.0)
                            posture_hr_offset = 4.0 + rise * 5.0
                        elif cycle_s >= 105:
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

                # Close dangling episode if session ended while bent
                if current_episode is not None:
                    current_episode["end_ts"] = t_iso
                    episodes.append(current_episode)
                    current_episode = None

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
        days=args.days,
        device_id=args.device_id,
        effects=args.effects,
        seed=args.seed,
        clear_sim=args.clear_sim,
        tz_offset_minutes=args.tz_offset_minutes,
        db_path=args.db_path,
    )
