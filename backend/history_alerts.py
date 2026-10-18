"""
History and Alerts processing module for Posture T-Shirt.

Calculates:
- Bounds & device metadata
- History summary & time shares
- Posture segments & downsampled timeline
- Day-by-day local time aggregation
- Continuous monitoring sessions (gap thresholding)
- Raw readings pagination
- Episode search, filtering, and detailed slouch context window
- Alerts summary (by day and by 24h local hour of day)
- CSV exports for history and episodes
"""

from datetime import datetime, timedelta, timezone
import math
import statistics

# Severity order for posture buckets / points
SEVERITY_ORDER = {"ALERT": 4, "WARNING": 3, "SITTING": 2, "UPRIGHT": 1, "UNCALIBRATED": 0, "CALIBRATING": 0, "FAULT": 0}


def _get_val(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        val = obj[key]
        return val if val is not None else default
    except Exception:
        return default

def parse_iso(ts_str):
    """Parse ISO-8601 string to timezone-aware UTC datetime."""
    if not ts_str:
        return None
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def to_local_iso(dt_utc, tz_offset_minutes=0):
    """Convert UTC datetime to local ISO string with offset."""
    if not dt_utc:
        return None
    local_tz = timezone(timedelta(minutes=tz_offset_minutes))
    return dt_utc.astimezone(local_tz).isoformat()


def get_history_bounds(conn):
    """
    Returns bounds of all recorded telemetry and device list.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts, COUNT(*) AS total_rows FROM telemetry")
    row = cursor.fetchone()

    cursor.execute("""
        SELECT device_id, MIN(ts) AS first_seen, MAX(ts) AS last_seen, COUNT(*) AS count
        FROM telemetry
        WHERE device_id IS NOT NULL AND device_id != ''
        GROUP BY device_id
        ORDER BY last_seen DESC
    """)
    dev_rows = cursor.fetchall()

    devices = []
    for d in dev_rows:
        dev_id = d["device_id"]
        devices.append({
            "device_id": dev_id,
            "first_seen": d["first_seen"],
            "last_seen": d["last_seen"],
            "count": d["count"],
            "simulated": bool(dev_id and dev_id.startswith("sim-")),
        })

    return {
        "first_ts": row["first_ts"] if row and row["first_ts"] else None,
        "last_ts": row["last_ts"] if row and row["last_ts"] else None,
        "total_rows": row["total_rows"] if row and row["total_rows"] else 0,
        "devices": devices,
        "retention_days": 7,
    }


def compute_history_summary(telemetry_rows, episode_rows, sessions_count=0):
    """
    Compute summary metrics for the range.
    Returns null (not 0) for stats without enough data (< 12 samples / 60 seconds).
    """
    monitored_seconds = len(telemetry_rows) # At 1 Hz
    if monitored_seconds < 12:
        return {
            "monitored_seconds": monitored_seconds,
            "monitored_time_text": f"{monitored_seconds}s",
            "time_per_category": {"UPRIGHT": 0, "WARNING": 0, "ALERT": 0, "SITTING": 0},
            "percent_per_category": {"UPRIGHT": 0.0, "WARNING": 0.0, "ALERT": 0.0, "SITTING": 0.0},
            "good_posture_percent": None,
            "slouch_count": len(episode_rows),
            "longest_slouch_s": None,
            "avg_slouch_length_s": None,
            "avg_heart_rate_bpm": None,
            "avg_temperature_c": None,
            "avg_temp_c": None,
            "avg_humidity_pct": None,
            "avg_hum_pct": None,
            "sessions_count": sessions_count,
        }

    cat_counts = {"UPRIGHT": 0, "WARNING": 0, "ALERT": 0, "SITTING": 0}
    for r in telemetry_rows:
        st = _get_val(r, "state")
        is_std = bool(_get_val(r, "is_standing"))
        if not is_std:
            cat = "SITTING"
        elif st in ("WARNING", "ALERT"):
            cat = st
        else:
            cat = "UPRIGHT"
        cat_counts[cat] += 1

    total_valid_cat = sum(cat_counts.values()) or 1
    pct_cat = {c: round((cnt / total_valid_cat) * 100.0, 1) for c, cnt in cat_counts.items()}
    # Good posture is non-slouching time (UPRIGHT + SITTING) as a fraction of monitored time
    good_posture_pct = round(((cat_counts["UPRIGHT"] + cat_counts["SITTING"]) / total_valid_cat) * 100.0, 1)

    # Episodes / slouches metrics
    slouch_count = len(episode_rows)
    durations_s = [
        round((ep["duration_ms"] or 0) / 1000.0, 1)
        for ep in episode_rows
        if _get_val(ep, "duration_ms") is not None
    ]
    longest_slouch = max(durations_s) if durations_s else None
    avg_slouch = round(statistics.mean(durations_s), 1) if durations_s else None

    # Vitals
    hr_samples = [
        float(r["heart_rate_bpm"])
        for r in telemetry_rows
        if _get_val(r, "heart_rate_bpm") is not None
        and bool(_get_val(r, "finger_present"))
        and 40 <= _get_val(r, "heart_rate_bpm") <= 200
    ]
    avg_hr = round(statistics.mean(hr_samples), 1) if len(hr_samples) >= 12 else None

    temps = [float(r["temperature_c"]) for r in telemetry_rows if _get_val(r, "temperature_c") is not None]
    avg_temp = round(statistics.mean(temps), 1) if len(temps) >= 12 else None

    hums = [float(r["humidity_pct"]) for r in telemetry_rows if _get_val(r, "humidity_pct") is not None]
    avg_hum = round(statistics.mean(hums), 1) if len(hums) >= 12 else None

    return {
        "monitored_seconds": monitored_seconds,
        "monitored_time_text": f"{monitored_seconds // 60} min" if monitored_seconds >= 60 else f"{monitored_seconds}s",
        "time_per_category": cat_counts,
        "percent_per_category": pct_cat,
        "good_posture_percent": good_posture_pct,
        "slouch_count": slouch_count,
        "longest_slouch_s": longest_slouch,
        "avg_slouch_length_s": avg_slouch,
        "avg_heart_rate_bpm": avg_hr,
        "avg_temperature_c": avg_temp,
        "avg_temp_c": avg_temp,
        "avg_humidity_pct": avg_hum,
        "avg_hum_pct": avg_hum,
        "sessions_count": sessions_count,
    }


def compute_posture_segments(telemetry_rows, max_gap_s=10):
    """
    Compute run-length-encoded posture segments: [{start, end, cat}].
    Gaps > max_gap_s are not part of any segment.
    """
    if not telemetry_rows:
        return []

    segments = []
    current_cat = None
    seg_start = None
    prev_dt = None

    for r in telemetry_rows:
        dt = parse_iso(_get_val(r, "ts"))
        if not dt:
            continue

        st = _get_val(r, "state")
        is_std = bool(_get_val(r, "is_standing"))
        if not is_std:
            cat = "SITTING"
        elif st in ("WARNING", "ALERT"):
            cat = st
        else:
            cat = "UPRIGHT"

        if prev_dt is None:
            # First row
            seg_start = dt
            current_cat = cat
            prev_dt = dt
            continue

        gap = (dt - prev_dt).total_seconds()
        if gap > max_gap_s or cat != current_cat:
            # End current segment
            segments.append({
                "start": seg_start.isoformat(),
                "end": prev_dt.isoformat(),
                "cat": current_cat,
                "seconds": round((prev_dt - seg_start).total_seconds()) + 1,
            })
            seg_start = dt
            current_cat = cat

        prev_dt = dt

    if seg_start and prev_dt:
        segments.append({
            "start": seg_start.isoformat(),
            "end": prev_dt.isoformat(),
            "cat": current_cat,
            "seconds": round((prev_dt - seg_start).total_seconds()) + 1,
        })

    return segments


def compute_timeline_series(telemetry_rows, max_points=800, max_gap_s=10):
    """
    Downsample series for charts into max_points.
    Assigns highest severity category per bucket.
    Inserts None (gaps) when timestamp distance > max_gap_s.
    """
    if not telemetry_rows:
        return [], 1

    total_rows = len(telemetry_rows)
    if total_rows <= max_points:
        points = []
        prev_dt = None
        for r in telemetry_rows:
            dt = parse_iso(_get_val(r, "ts"))
            if not dt:
                continue
            if prev_dt and (dt - prev_dt).total_seconds() > max_gap_s:
                # Add gap break marker
                points.append({"t": (prev_dt + timedelta(seconds=1)).isoformat(), "pitch": None, "hr": None, "temp": None, "hum": None, "cat": None})

            st = _get_val(r, "state")
            is_std = bool(_get_val(r, "is_standing"))
            if not is_std:
                cat = "SITTING"
            elif st in ("WARNING", "ALERT"):
                cat = st
            else:
                cat = "UPRIGHT"

            hr = _get_val(r, "heart_rate_bpm")
            fp = bool(_get_val(r, "finger_present"))
            valid_hr = float(hr) if (hr is not None and fp and 40 <= hr <= 200) else None

            points.append({
                "t": dt.isoformat(),
                "pitch": round(float(r["imu_pitch_deg"]), 1) if _get_val(r, "imu_pitch_deg") is not None else None,
                "hr": round(valid_hr, 1) if valid_hr is not None else None,
                "temp": round(float(r["temperature_c"]), 1) if _get_val(r, "temperature_c") is not None else None,
                "hum": round(float(r["humidity_pct"]), 1) if _get_val(r, "humidity_pct") is not None else None,
                "cat": cat,
            })
            prev_dt = dt
        return points, 1

    # Chunk downsampling
    step = total_rows / float(max_points)
    resolution_s = max(1, round(step))
    points = []
    prev_dt = None

    for i in range(max_points):
        start_idx = int(i * step)
        end_idx = min(total_rows, int((i + 1) * step))
        chunk = telemetry_rows[start_idx:end_idx]
        if not chunk:
            continue

        chunk_first_dt = parse_iso(_get_val(chunk[0], "ts"))
        if not chunk_first_dt:
            continue

        if prev_dt and (chunk_first_dt - prev_dt).total_seconds() > max(max_gap_s, resolution_s * 2):
            points.append({"t": (prev_dt + timedelta(seconds=resolution_s)).isoformat(), "pitch": None, "hr": None, "temp": None, "hum": None, "cat": None})

        # Highest severity in chunk
        def get_row_cat(r):
            st = _get_val(r, "state")
            if not bool(_get_val(r, "is_standing")):
                return "SITTING"
            if st in ("WARNING", "ALERT"):
                return st
            return "UPRIGHT"

        highest_cat = max(chunk, key=lambda c: SEVERITY_ORDER.get(get_row_cat(c), 0))
        cat = get_row_cat(highest_cat)

        def avg_key(k, hr_filter=False):
            vals = []
            for r in chunk:
                v = _get_val(r, k)
                if v is None:
                    continue
                if hr_filter:
                    if not bool(_get_val(r, "finger_present")) or not (40 <= v <= 200):
                        continue
                vals.append(float(v))
            return round(statistics.mean(vals), 1) if vals else None

        points.append({
            "t": chunk_first_dt.isoformat(),
            "pitch": avg_key("imu_pitch_deg"),
            "hr": avg_key("heart_rate_bpm", hr_filter=True),
            "temp": avg_key("temperature_c"),
            "hum": avg_key("humidity_pct"),
            "cat": cat,
        })
        prev_dt = parse_iso(_get_val(chunk[-1], "ts")) or chunk_first_dt

    return points, resolution_s


def compute_local_days(telemetry_rows, episode_rows, tz_offset_minutes=0, sessions=[]):
    """
    Aggregate data by viewer's local calendar day.
    """
    days_dict = {}
    local_tz = timezone(timedelta(minutes=tz_offset_minutes))

    for r in telemetry_rows:
        dt_utc = parse_iso(_get_val(r, "ts"))
        if not dt_utc:
            continue
        dt_local = dt_utc.astimezone(local_tz)
        day_str = dt_local.strftime("%Y-%m-%d")

        if day_str not in days_dict:
            days_dict[day_str] = {
                "date": day_str,
                "rows": [],
            }
        days_dict[day_str]["rows"].append(r)

    # Map episodes to local day of their start_ts
    episodes_by_day = {}
    for ep in episode_rows:
        ep_dt = parse_iso(_get_val(ep, "start_ts"))
        if not ep_dt:
            continue
        ep_local = ep_dt.astimezone(local_tz)
        day_str = ep_local.strftime("%Y-%m-%d")
        episodes_by_day.setdefault(day_str, []).append(ep)

    # Map sessions to local day of their start
    sessions_by_day = {}
    for sess in sessions:
        s_dt = parse_iso(sess.get("start"))
        if not s_dt:
            continue
        s_local = s_dt.astimezone(local_tz)
        day_str = s_local.strftime("%Y-%m-%d")
        sessions_by_day.setdefault(day_str, []).append(sess)

    result = []
    # Sorted by date ascending
    for day_str in sorted(days_dict.keys()):
        d_rows = days_dict[day_str]["rows"]
        d_eps = episodes_by_day.get(day_str, [])
        d_sess = sessions_by_day.get(day_str, [])

        monitored_s = len(d_rows)
        cat_counts = {"UPRIGHT": 0, "WARNING": 0, "ALERT": 0, "SITTING": 0}
        for r in d_rows:
            st = _get_val(r, "state")
            if not bool(_get_val(r, "is_standing")):
                cat_counts["SITTING"] += 1
            elif st in ("WARNING", "ALERT"):
                cat_counts[st] += 1
            else:
                cat_counts["UPRIGHT"] += 1

        total_cat = sum(cat_counts.values()) or 1
        pct_good = round((cat_counts["UPRIGHT"] / total_cat) * 100.0, 1)

        durations_s = [
            round((ep["duration_ms"] or 0) / 1000.0, 1)
            for ep in d_eps
            if _get_val(ep, "duration_ms") is not None
        ]
        longest_slouch = max(durations_s) if durations_s else None

        hr_vals = [
            float(r["heart_rate_bpm"])
            for r in d_rows
            if _get_val(r, "heart_rate_bpm") is not None
            and bool(_get_val(r, "finger_present"))
            and 40 <= _get_val(r, "heart_rate_bpm") <= 200
        ]
        avg_hr = round(statistics.mean(hr_vals), 1) if len(hr_vals) >= 12 else None

        result.append({
            "date": day_str,
            "monitored_seconds": monitored_s,
            "monitored_time_text": f"{monitored_s // 60} min" if monitored_s >= 60 else f"{monitored_s}s",
            "good_posture_percent": pct_good,
            "slouch_count": len(d_eps),
            "longest_slouch_s": longest_slouch,
            "avg_heart_rate_bpm": avg_hr,
            "sessions_count": len(d_sess),
            "posture_share": {c: round((cnt / total_cat) * 100.0, 1) for c, cnt in cat_counts.items()},
        })

    return result


def compute_sessions(telemetry_rows, episode_rows, gap_s=60, tz_offset_minutes=0):
    """
    Find continuous monitoring sessions where gap between readings <= gap_s.
    """
    if not telemetry_rows:
        return []

    sessions = []
    current_chunk = []
    prev_dt = None

    for r in telemetry_rows:
        dt = parse_iso(_get_val(r, "ts"))
        if not dt:
            continue

        if prev_dt is None:
            current_chunk = [r]
            prev_dt = dt
            continue

        gap = (dt - prev_dt).total_seconds()
        if gap > gap_s:
            # Finalize session
            sess = _build_single_session(current_chunk, episode_rows)
            if sess:
                sessions.append(sess)
            current_chunk = [r]
        else:
            current_chunk.append(r)

        prev_dt = dt

    if current_chunk:
        sess = _build_single_session(current_chunk, episode_rows)
        if sess:
            sessions.append(sess)

    # Return newest first
    sessions.reverse()
    return sessions


def _build_single_session(chunk, all_episodes):
    if not chunk:
        return None
    start_dt = parse_iso(_get_val(chunk[0], "ts"))
    end_dt = parse_iso(_get_val(chunk[-1], "ts"))
    if not start_dt or not end_dt:
        return None

    dur_s = max(1, round((end_dt - start_dt).total_seconds()))

    upright_cnt = sum(
        1 for r in chunk
        if bool(_get_val(r, "is_standing")) and _get_val(r, "state") not in ("WARNING", "ALERT")
    )
    good_pct = round((upright_cnt / len(chunk)) * 100.0, 1)

    # Find episodes within this session window
    start_ts_iso = start_dt.isoformat()
    end_ts_iso = end_dt.isoformat()
    sess_eps = [
        ep for ep in all_episodes
        if _get_val(ep, "start_ts") and start_ts_iso <= ep["start_ts"] <= end_ts_iso
    ]

    hr_vals = [
        float(r["heart_rate_bpm"])
        for r in chunk
        if _get_val(r, "heart_rate_bpm") is not None
        and bool(_get_val(r, "finger_present"))
        and 40 <= _get_val(r, "heart_rate_bpm") <= 200
    ]
    avg_hr = round(statistics.mean(hr_vals), 1) if len(hr_vals) >= 12 else None

    return {
        "id": start_ts_iso,
        "start": start_ts_iso,
        "end": end_ts_iso,
        "duration_s": dur_s,
        "duration_text": f"{dur_s // 60} min" if dur_s >= 60 else f"{dur_s}s",
        "good_posture_percent": good_pct,
        "slouch_count": len(sess_eps),
        "avg_heart_rate_bpm": avg_hr,
    }


def compute_alerts_summary(episode_rows, tz_offset_minutes=0):
    """
    Compute aggregate statistics for the Alerts view:
    - Counts of warning, alert, total slouch time, longest, average.
    - Slouches per local day.
    - Slouches per local hour of day (24 bins: 0..23).
    - Most frequent hour string (e.g. "3 pm to 4 pm").
    """
    local_tz = timezone(timedelta(minutes=tz_offset_minutes))
    total_slouches = len(episode_rows)

    warn_count = sum(1 for ep in episode_rows if _get_val(ep, "max_level") == "WARNING")
    alert_count = sum(1 for ep in episode_rows if _get_val(ep, "max_level") == "ALERT")

    durations_s = [
        round((ep["duration_ms"] or 0) / 1000.0, 1)
        for ep in episode_rows
        if _get_val(ep, "duration_ms") is not None
    ]
    total_slouch_time_s = round(sum(durations_s), 1)
    longest_slouch_s = max(durations_s) if durations_s else None
    avg_length_s = round(statistics.mean(durations_s), 1) if durations_s else None

    # Slouches per local day (stacked warning vs alert)
    days_map = {}
    # Slouches per local hour of day (24 bins)
    hourly_bins = [0] * 24

    for ep in episode_rows:
        dt_utc = parse_iso(_get_val(ep, "start_ts"))
        if not dt_utc:
            continue
        dt_local = dt_utc.astimezone(local_tz)

        day_str = dt_local.strftime("%Y-%m-%d")
        if day_str not in days_map:
            days_map[day_str] = {"date": day_str, "warning": 0, "alert": 0, "total": 0}
        level = _get_val(ep, "max_level") or "WARNING"
        if level == "ALERT":
            days_map[day_str]["alert"] += 1
        else:
            days_map[day_str]["warning"] += 1
        days_map[day_str]["total"] += 1

        hour = dt_local.hour
        hourly_bins[hour] += 1

    per_day_list = [days_map[k] for k in sorted(days_map.keys())]

    # Most frequent hour (requires >= 3 slouches to show conclusion)
    most_frequent_hour_text = None
    if total_slouches >= 3:
        max_hour_count = max(hourly_bins)
        if max_hour_count > 0:
            top_hour = hourly_bins.index(max_hour_count)
            # Format to human readable e.g. "3 pm to 4 pm"
            def fmt_hour(h):
                if h == 0: return "12 am"
                if h < 12: return f"{h} am"
                if h == 12: return "12 pm"
                return f"{h - 12} pm"
            most_frequent_hour_text = f"{fmt_hour(top_hour)} to {fmt_hour((top_hour + 1) % 24)}"

    return {
        "slouch_count": total_slouches,
        "warning_count": warn_count,
        "alert_count": alert_count,
        "total_slouch_time_s": total_slouch_time_s,
        "longest_slouch_s": longest_slouch_s,
        "avg_length_s": avg_length_s,
        "slouches_per_day": per_day_list,
        "slouches_per_hour": hourly_bins,
        "most_frequent_hour": most_frequent_hour_text,
    }


def compute_episode_detail_context(conn, ep_id, window_seconds=60):
    """
    Fetch single episode with -60s before start to +60s after end context.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM episodes WHERE id = ?", (ep_id,))
    ep = cursor.fetchone()
    if not ep:
        return None

    ep_dict = dict(ep)
    start_dt = parse_iso(ep_dict.get("start_ts"))
    end_dt = parse_iso(ep_dict.get("end_ts")) or start_dt

    if not start_dt:
        return ep_dict

    t_before = (start_dt - timedelta(seconds=window_seconds)).isoformat()
    t_after = (end_dt + timedelta(seconds=window_seconds)).isoformat()

    dev_id = ep_dict.get("device_id")
    if dev_id:
        cursor.execute("""
            SELECT ts, imu_pitch_deg, heart_rate_bpm, finger_present, state, is_standing,
                   vibration_active, buzzer_active, muted, bend_duration_ms
            FROM telemetry
            WHERE device_id = ? AND ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (dev_id, t_before, t_after))
    else:
        cursor.execute("""
            SELECT ts, imu_pitch_deg, heart_rate_bpm, finger_present, state, is_standing,
                   vibration_active, buzzer_active, muted, bend_duration_ms
            FROM telemetry
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts ASC
        """, (t_before, t_after))

    rows = cursor.fetchall()
    context_series = []
    first_warn_s = None
    first_alert_s = None
    was_muted_during = False

    for r in rows:
        dt = parse_iso(r["ts"])
        if not dt:
            continue
        rel_s = round((dt - start_dt).total_seconds(), 1)
        st = r["state"]
        is_std = bool(r["is_standing"])
        cat = "SITTING" if not is_std else (st if st in ("WARNING", "ALERT") else "UPRIGHT")

        hr = r["heart_rate_bpm"]
        fp = bool(r["finger_present"])
        valid_hr = float(hr) if (hr is not None and fp and 40 <= hr <= 200) else None

        muted = bool(r["muted"])
        if start_dt <= dt <= end_dt and muted:
            was_muted_during = True

        if rel_s >= 0 and st in ("WARNING", "ALERT") and first_warn_s is None:
            first_warn_s = rel_s
        if rel_s >= 0 and st == "ALERT" and first_alert_s is None:
            first_alert_s = rel_s

        context_series.append({
            "t": dt.isoformat(),
            "offset_s": rel_s,
            "pitch": round(float(r["imu_pitch_deg"]), 1) if r["imu_pitch_deg"] is not None else None,
            "hr": round(valid_hr, 1) if valid_hr is not None else None,
            "cat": cat,
            "vibration": bool(r["vibration_active"]),
            "buzzer": bool(r["buzzer_active"]),
            "muted": muted,
        })

    ep_dict["context_series"] = context_series
    ep_dict["moments"] = {
        "early_warning_s": first_warn_s,
        "alert_s": first_alert_s,
        "duration_s": round((ep_dict.get("duration_ms") or 0) / 1000.0, 1),
        "muted_during": was_muted_during,
    }
    return ep_dict


def paginate_readings(conn, device_id, from_iso, to_iso, tz_offset_minutes=0, limit=50, offset=0, order="desc"):
    """
    Paginated raw readings for the History view.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM telemetry
        WHERE device_id = ? AND ts >= ? AND ts <= ?
    """, (device_id, from_iso, to_iso))
    total_count = cursor.fetchone()["total"]

    order_sql = f"ORDER BY ts {order.upper()}"
    cursor.execute(f"""
        SELECT *
        FROM telemetry
        WHERE device_id = ? AND ts >= ? AND ts <= ?
        {order_sql}
        LIMIT ? OFFSET ?
    """, (device_id, from_iso, to_iso, limit, offset))

    rows = cursor.fetchall()
    result_rows = []
    local_tz = timezone(timedelta(minutes=tz_offset_minutes))

    for r in rows:
        d = dict(r)
        dt = parse_iso(d.get("ts"))
        local_ts_str = dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S") if dt else ""
        d["local_time"] = local_ts_str

        st = d.get("state")
        is_std = bool(d.get("is_standing"))
        cat = "SITTING" if not is_std else (st if st in ("WARNING", "ALERT") else "UPRIGHT")
        d["posture_category"] = cat

        # Format pitch and hr nicely
        pitch = d.get("imu_pitch_deg")
        d["lean_angle"] = round(float(pitch), 1) if pitch is not None else None

        hr = d.get("heart_rate_bpm")
        fp = bool(d.get("finger_present"))
        d["heart_rate"] = int(hr) if (hr is not None and fp and 40 <= hr <= 200) else None

        result_rows.append(d)

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "order": order,
        "rows": result_rows,
    }


def export_history_csv(telemetry_rows, tz_offset_minutes=0, resolution="auto"):
    """
    Export telemetry rows as CSV with both local and UTC time columns.
    Header row, empty cells for nulls, local time column plus UTC time column.
    Columns: local_time, utc_time, posture, lean_angle, standing, heart_rate, temperature, humidity
    """
    import io
    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "local_time", "utc_time", "posture", "lean_angle", "standing",
        "heart_rate", "temperature", "humidity"
    ])

    if not telemetry_rows:
        return output.getvalue()

    local_tz = timezone(timedelta(minutes=tz_offset_minutes))

    # Downsampling if resolution is 5 or 60
    rows = telemetry_rows
    if resolution in ("5", "60"):
        res_s = int(resolution)
        bucketed_rows = []
        cur_bucket = []
        bucket_start_epoch = None
        for r in rows:
            dt = parse_iso(r["ts"])
            if not dt: continue
            epoch = dt.timestamp()
            b_epoch = math.floor(epoch / res_s) * res_s
            if bucket_start_epoch is None:
                bucket_start_epoch = b_epoch
                cur_bucket = [r]
            elif b_epoch == bucket_start_epoch:
                cur_bucket.append(r)
            else:
                # Emit average
                rep = cur_bucket[len(cur_bucket) // 2]
                bucketed_rows.append(rep)
                bucket_start_epoch = b_epoch
                cur_bucket = [r]
        if cur_bucket:
            bucketed_rows.append(cur_bucket[len(cur_bucket) // 2])
        rows = bucketed_rows

    for r in rows:
        dt = parse_iso(r["ts"])
        local_time_str = dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S") if dt else ""
        utc_time_str = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""

        st = r["state"]
        is_std = bool(r["is_standing"])
        cat = "SITTING" if not is_std else (st if st in ("WARNING", "ALERT") else "UPRIGHT")

        pitch = _get_val(r, "imu_pitch_deg")
        lean_angle = f"{pitch:.1f}" if pitch is not None else ""

        standing_str = "Standing" if is_std else "Sitting"

        hr = _get_val(r, "heart_rate_bpm")
        fp = bool(_get_val(r, "finger_present"))
        hr_str = f"{int(hr)}" if (hr is not None and fp and 40 <= hr <= 200) else ""

        temp = _get_val(r, "temperature_c")
        temp_str = f"{temp:.1f}" if temp is not None else ""

        hum = _get_val(r, "humidity_pct")
        hum_str = f"{hum:.1f}" if hum is not None else ""

        writer.writerow([
            local_time_str, utc_time_str, cat, lean_angle, standing_str,
            hr_str, temp_str, hum_str
        ])

    return output.getvalue()


def export_episodes_csv(episode_rows, tz_offset_minutes=0):
    """
    Export filtered slouch episodes as CSV.
    Columns: id, device_id, start_local, start_utc, end_local, end_utc, duration_s, max_level, peak_lean_angle
    """
    import io
    import csv

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "device_id", "start_local", "start_utc", "end_local", "end_utc",
        "duration_s", "max_level", "peak_lean_angle"
    ])

    local_tz = timezone(timedelta(minutes=tz_offset_minutes))

    for ep in episode_rows:
        s_dt = parse_iso(ep["start_ts"])
        e_dt = parse_iso(_get_val(ep, "end_ts"))

        s_loc = s_dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S") if s_dt else ""
        s_utc = s_dt.strftime("%Y-%m-%d %H:%M:%S") if s_dt else ""

        e_loc = e_dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S") if e_dt else ""
        e_utc = e_dt.strftime("%Y-%m-%d %H:%M:%S") if e_dt else ""

        dur_s = round((_get_val(ep, "duration_ms") or 0) / 1000.0, 1)
        peak = f"{ep['peak_pitch_deg']:.1f}" if _get_val(ep, "peak_pitch_deg") is not None else ""

        writer.writerow([
            _get_val(ep, "id"), _get_val(ep, "device_id"), s_loc, s_utc, e_loc, e_utc,
            dur_s, _get_val(ep, "max_level"), peak
        ])

    return output.getvalue()

