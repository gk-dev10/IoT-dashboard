"""Bend episode tracking and lifecycle management."""

from datetime import datetime, timezone


def process_episode_transition(conn, device_id, incoming_state, imu_pitch_deg, bend_duration_ms, incoming_ts):
    """
    Update or transition bend episodes based on current telemetry.
    Returns (episode_opened: bool, episode_closed: bool, open_episode_dict or None).
    """
    cursor = conn.cursor()
    # Find any currently open episode for this device
    cursor.execute("""
        SELECT id, device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms
        FROM episodes
        WHERE end_ts IS NULL AND (device_id = ? OR device_id IS NULL)
        ORDER BY id DESC
        LIMIT 1
    """, (device_id,))
    open_ep = cursor.fetchone()

    is_warning_or_alert = incoming_state in ("WARNING", "ALERT")
    opened = False
    closed = False

    incoming_dt = datetime.fromisoformat(incoming_ts)

    if open_ep:
        ep_id = open_ep["id"]
        start_dt = datetime.fromisoformat(open_ep["start_ts"])
        elapsed_ms = int((incoming_dt - start_dt).total_seconds() * 1000)
        curr_duration = max(elapsed_ms, bend_duration_ms or 0, open_ep["duration_ms"] or 0)

        if not is_warning_or_alert:
            # Episode has concluded
            cursor.execute("""
                UPDATE episodes
                SET end_ts = ?, duration_ms = ?
                WHERE id = ?
            """, (incoming_ts, curr_duration, ep_id))
            conn.commit()
            closed = True
        else:
            # Episode continues: update max_level and peak_pitch_deg
            curr_max_level = open_ep["max_level"]
            if incoming_state == "ALERT" or curr_max_level == "ALERT":
                new_max_level = "ALERT"
            else:
                new_max_level = "WARNING"

            curr_peak = open_ep["peak_pitch_deg"]
            if imu_pitch_deg is not None:
                new_peak = max(curr_peak if curr_peak is not None else -999.0, float(imu_pitch_deg))
            else:
                new_peak = curr_peak

            cursor.execute("""
                UPDATE episodes
                SET max_level = ?, peak_pitch_deg = ?, duration_ms = ?
                WHERE id = ?
            """, (new_max_level, new_peak, curr_duration, ep_id))
            conn.commit()

    else:
        if is_warning_or_alert:
            # Start a new episode
            cursor.execute("""
                INSERT INTO episodes (device_id, start_ts, end_ts, max_level, peak_pitch_deg, duration_ms)
                VALUES (?, ?, NULL, ?, ?, ?)
            """, (
                device_id,
                incoming_ts,
                incoming_state,
                float(imu_pitch_deg) if imu_pitch_deg is not None else 0.0,
                bend_duration_ms or 0
            ))
            conn.commit()
            opened = True

    return opened, closed


def check_and_close_timed_out_episodes(conn, max_gap_seconds=10):
    """Close any open episode if no data has arrived for max_gap_seconds."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, device_id, start_ts, max_level, peak_pitch_deg, duration_ms
        FROM episodes
        WHERE end_ts IS NULL
    """)
    open_eps = cursor.fetchall()

    now = datetime.now(timezone.utc)
    closed_any = False

    for ep in open_eps:
        # Check latest telemetry timestamp for this device
        cursor.execute("""
            SELECT ts FROM telemetry
            WHERE device_id = ?
            ORDER BY id DESC LIMIT 1
        """, (ep["device_id"],))
        last_tel = cursor.fetchone()

        if last_tel:
            try:
                last_dt = datetime.fromisoformat(last_tel["ts"])
                gap = (now - last_dt).total_seconds()
                if gap >= max_gap_seconds:
                    start_dt = datetime.fromisoformat(ep["start_ts"])
                    duration_ms = max(ep["duration_ms"] or 0, int((last_dt - start_dt).total_seconds() * 1000))
                    cursor.execute("""
                        UPDATE episodes
                        SET end_ts = ?, duration_ms = ?
                        WHERE id = ?
                    """, (last_tel["ts"], duration_ms, ep["id"]))
                    closed_any = True
            except Exception:
                pass
        else:
            # No telemetry at all; close with start_ts
            cursor.execute("UPDATE episodes SET end_ts = start_ts, duration_ms = 0 WHERE id = ?", (ep["id"],))
            closed_any = True

    if closed_any:
        conn.commit()
    return closed_any
