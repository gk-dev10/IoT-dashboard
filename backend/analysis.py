"""
Analysis Engine for Smart Posture T-Shirt.

Calculates aggregated statistical metrics, posture vs vitals breakdowns,
episode impacts, and conservative, honest insights on 5-second bucketed data.
"""

from datetime import datetime, timezone
import math
import statistics

# Minimum data thresholds (Constants defined as requirements)
MIN_BUCKETS_PER_GROUP = 12       # ~1 minute of 5s buckets to summarize a group
MIN_BUCKETS_CORR = 30            # Minimum buckets for correlation calculation
MIN_HR_SAMPLES_WINDOW = 5        # Minimum valid HR samples in before/during/after windows


def parse_iso(ts_str):
    """Parse ISO-8601 string to datetime object."""
    if not ts_str:
        return None
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def calculate_pearson_r(x_vals, y_vals):
    """
    Calculate Pearson correlation coefficient r, slope, and intercept.
    Guards against zero variance and constant series.
    Returns (r, slope, intercept, reason).
    """
    n = len(x_vals)
    if n < MIN_BUCKETS_CORR:
        return None, None, None, f"n = {n}, need {MIN_BUCKETS_CORR}"

    try:
        var_x = statistics.variance(x_vals)
        var_y = statistics.variance(y_vals)
    except Exception:
        return None, None, None, "Insufficient data variance"

    if var_x <= 1e-9:
        return None, None, None, "No variation in X variable"
    if var_y <= 1e-9:
        return None, None, None, "No variation in Y variable"

    try:
        r = statistics.correlation(x_vals, y_vals)
    except Exception:
        # Fallback calculation if statistics.correlation fails
        mean_x = statistics.mean(x_vals)
        mean_y = statistics.mean(y_vals)
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals))
        den = math.sqrt(sum((x - mean_x) ** 2 for x in x_vals) * sum((y - mean_y) ** 2 for y in y_vals))
        if den == 0:
            return None, None, None, "Zero denominator in correlation"
        r = num / den

    # Guard for float precision bounds
    r = max(-1.0, min(1.0, r))

    # Least squares linear regression slope and intercept
    mean_x = statistics.mean(x_vals)
    mean_y = statistics.mean(y_vals)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_vals, y_vals)) / sum((x - mean_x) ** 2 for x in x_vals)
    intercept = mean_y - slope * mean_x

    return r, slope, intercept, None


def get_correlation_labels(r):
    """Return strength and direction labels for Pearson r."""
    if r is None:
        return None, None
    direction = "positive" if r >= 0 else "negative"
    abs_r = abs(r)
    if abs_r < 0.10:
        strength = "negligible"
    elif abs_r < 0.30:
        strength = "weak"
    elif abs_r <= 0.50:
        strength = "moderate"
    else:
        strength = "strong"
    return strength, direction


def summarize_metric(values):
    """
    Compute mean, median, sd, min, max, n for a list of bucketed values.
    Returns dict or null if n < MIN_BUCKETS_PER_GROUP.
    """
    n = len(values)
    if n < MIN_BUCKETS_PER_GROUP:
        return {"n": n, "mean": None, "median": None, "sd": None, "min": None, "max": None}

    mean_val = statistics.mean(values)
    median_val = statistics.median(values)
    sd_val = statistics.stdev(values) if n > 1 else 0.0
    min_val = min(values)
    max_val = max(values)

    return {
        "n": n,
        "mean": round(mean_val, 1),
        "median": round(median_val, 1),
        "sd": round(sd_val, 1),
        "min": round(min_val, 1),
        "max": round(max_val, 1),
    }


def aggregate_into_buckets(rows, exclude_moving=True):
    """
    Group rows into 5-second buckets based on timestamps.
    Returns list of bucket dicts.
    """
    if not rows:
        return []

    # Sort rows by timestamp ascending
    parsed_rows = []
    for r in rows:
        dt = parse_iso(r.get("ts"))
        if dt:
            parsed_rows.append((dt.timestamp(), dt, r))
    parsed_rows.sort(key=lambda x: x[0])

    if not parsed_rows:
        return []

    buckets = []
    current_bucket_start = None
    current_rows = []

    for epoch, dt, r in parsed_rows:
        bucket_index = int(epoch // 5)
        bucket_start_epoch = bucket_index * 5.0

        if current_bucket_start is None:
            current_bucket_start = bucket_start_epoch
            current_rows = [r]
        elif bucket_start_epoch == current_bucket_start:
            current_rows.append(r)
        else:
            # Finalize previous bucket
            b = _finalize_bucket(current_bucket_start, current_rows, exclude_moving)
            if b:
                buckets.append(b)
            current_bucket_start = bucket_start_epoch
            current_rows = [r]

    if current_rows:
        b = _finalize_bucket(current_bucket_start, current_rows, exclude_moving)
        if b:
            buckets.append(b)

    return buckets


def _finalize_bucket(bucket_start_epoch, rows, exclude_moving):
    """Compute 5-second bucket summary."""
    # 1. State filter: ignore UNCALIBRATED, CALIBRATING, FAULT
    valid_state_rows = [r for r in rows if r.get("state") not in ("UNCALIBRATED", "CALIBRATING", "FAULT")]
    if not valid_state_rows:
        return None

    # 2. Posture Category with highest severity present: ALERT > WARNING > SITTING > UPRIGHT
    has_alert = any(r.get("state") == "ALERT" and bool(r.get("is_standing")) for r in valid_state_rows)
    has_warning = any(r.get("state") == "WARNING" and bool(r.get("is_standing")) for r in valid_state_rows)
    has_sitting = any(not bool(r.get("is_standing")) for r in valid_state_rows)

    if has_alert:
        category = "ALERT"
    elif has_warning:
        category = "WARNING"
    elif has_sitting:
        category = "SITTING"
    else:
        category = "UPRIGHT"

    # 3. Valid HR samples
    hr_samples = []
    for r in valid_state_rows:
        hr = r.get("heart_rate_bpm")
        fp = bool(r.get("finger_present"))
        moving = bool(r.get("moving"))

        if exclude_moving and moving:
            continue
        if hr is not None and fp and 40 <= hr <= 200:
            hr_samples.append(float(hr))

    # A bucket is valid for HR if it contains at least 2 valid HR samples
    mean_hr = statistics.mean(hr_samples) if len(hr_samples) >= 2 else None
    hr_sample_count = len(hr_samples)

    # 4. Temperature and humidity
    temps = [float(r["temperature_c"]) for r in valid_state_rows if r.get("temperature_c") is not None]
    hums = [float(r["humidity_pct"]) for r in valid_state_rows if r.get("humidity_pct") is not None]
    pitches = [float(r["imu_pitch_deg"]) for r in valid_state_rows if r.get("imu_pitch_deg") is not None]
    bend_durs = [float(r.get("bend_duration_ms", 0) or 0) / 1000.0 for r in valid_state_rows]

    mean_temp = statistics.mean(temps) if temps else None
    mean_hum = statistics.mean(hums) if hums else None
    mean_pitch = statistics.mean(pitches) if pitches else None
    mean_bend_dur = statistics.mean(bend_durs) if bend_durs else 0.0

    moving_count = sum(1 for r in valid_state_rows if bool(r.get("moving")))
    moving_fraction = moving_count / len(valid_state_rows)

    bucket_dt = datetime.fromtimestamp(bucket_start_epoch, tz=timezone.utc)

    return {
        "epoch": bucket_start_epoch,
        "ts": bucket_dt.isoformat(),
        "category": category,
        "hr": mean_hr,
        "hr_samples_count": hr_sample_count,
        "temp": mean_temp,
        "hum": mean_hum,
        "pitch": mean_pitch,
        "bend_duration_s": mean_bend_dur,
        "moving_fraction": round(moving_fraction, 2),
        "raw_count": len(rows),
    }


def analyze_telemetry_and_episodes(rows, episodes, range_minutes=60, exclude_moving=True, device_id="vest-01"):
    """
    Full statistical analysis engine adhering strictly to definitions and honesty rules.
    """
    total_raw_rows = len(rows)
    is_simulated = bool(device_id and str(device_id).startswith("sim-"))

    # Quality counters across all raw rows
    if total_raw_rows > 0:
        hr_valid_raw = sum(1 for r in rows if r.get("heart_rate_bpm") is not None and bool(r.get("finger_present")) and 40 <= r.get("heart_rate_bpm") <= 200)
        temp_valid_raw = sum(1 for r in rows if r.get("temperature_c") is not None)
        hum_valid_raw = sum(1 for r in rows if r.get("humidity_pct") is not None)
        moving_raw = sum(1 for r in rows if bool(r.get("moving")))
        uncal_raw = sum(1 for r in rows if r.get("state") in ("UNCALIBRATED", "CALIBRATING", "FAULT"))

        quality = {
            "hr_valid_pct": round(100.0 * hr_valid_raw / total_raw_rows, 1),
            "temp_valid_pct": round(100.0 * temp_valid_raw / total_raw_rows, 1),
            "hum_valid_pct": round(100.0 * hum_valid_raw / total_raw_rows, 1),
            "moving_pct": round(100.0 * moving_raw / total_raw_rows, 1),
            "uncalibrated_pct": round(100.0 * uncal_raw / total_raw_rows, 1),
        }
        range_start = rows[0].get("ts") if rows else None
        range_end = rows[-1].get("ts") if rows else None
    else:
        quality = {
            "hr_valid_pct": 0.0, "temp_valid_pct": 0.0, "hum_valid_pct": 0.0,
            "moving_pct": 0.0, "uncalibrated_pct": 0.0,
        }
        range_start = None
        range_end = None

    buckets = aggregate_into_buckets(rows, exclude_moving=exclude_moving)
    total_buckets = len(buckets)

    meta = {
        "device_id": device_id,
        "simulated": is_simulated,
        "range_start": range_start,
        "range_end": range_end,
        "minutes": range_minutes,
        "rows": total_raw_rows,
        "buckets": total_buckets,
        "exclude_moving": exclude_moving,
        "thresholds": {
            "min_buckets_group": MIN_BUCKETS_PER_GROUP,
            "min_buckets_corr": MIN_BUCKETS_CORR,
            "min_hr_samples_window": MIN_HR_SAMPLES_WINDOW,
        },
    }

    # Group buckets by posture category
    cats = ["UPRIGHT", "WARNING", "ALERT", "SITTING"]
    cat_buckets = {c: [] for c in cats}
    for b in buckets:
        if b["category"] in cat_buckets:
            cat_buckets[b["category"]].append(b)

    # Time shares (%)
    time_share = {}
    for c in cats:
        cnt = len(cat_buckets[c])
        pct = round(100.0 * cnt / total_buckets, 1) if total_buckets > 0 else 0.0
        time_share[c] = pct

    # Breakdown by posture
    by_posture = {}
    for c in cats:
        b_list = cat_buckets[c]
        b_count = len(b_list)
        b_sec = b_count * 5

        hr_vals = [b["hr"] for b in b_list if b["hr"] is not None]
        temp_vals = [b["temp"] for b in b_list if b["temp"] is not None]
        hum_vals = [b["hum"] for b in b_list if b["hum"] is not None]

        by_posture[c] = {
            "buckets": b_count,
            "seconds": b_sec,
            "hr": summarize_metric(hr_vals),
            "temp": summarize_metric(temp_vals),
            "hum": summarize_metric(hum_vals),
        }

    # Episode impact analysis
    episode_impact = _analyze_episode_impact(buckets, episodes, rows, exclude_moving)

    # Correlations
    correlations = _analyze_correlations(buckets)

    # Downsampled series for overlay chart (max 800 points)
    series = _build_series(buckets, max_points=800)

    # Generate conservative insights server-side
    insights = _generate_insights(by_posture, episode_impact, correlations, quality, buckets)

    return {
        "meta": meta,
        "quality": quality,
        "time_share": time_share,
        "by_posture": by_posture,
        "episode_impact": episode_impact,
        "correlations": correlations,
        "series": series,
        "insights": insights,
    }


def _analyze_episode_impact(buckets, episodes, raw_rows, exclude_moving):
    """
    Analyze heart rate around closed episodes.
    - Window before: 60s before episode start (only UPRIGHT buckets)
    - Window during: episode start to episode end
    - Window after: 60s after episode end
    Window requires >= MIN_HR_SAMPLES_WINDOW valid HR samples.
    """
    per_episode = []
    used_episodes = []

    # Map raw rows with valid HR for fast window count/average
    valid_raw_hr = []
    for r in raw_rows:
        hr = r.get("heart_rate_bpm")
        fp = bool(r.get("finger_present"))
        mv = bool(r.get("moving"))
        dt = parse_iso(r.get("ts"))
        if dt and hr is not None and fp and 40 <= hr <= 200:
            if not (exclude_moving and mv):
                valid_raw_hr.append((dt.timestamp(), float(hr), r.get("state"), bool(r.get("is_standing"))))

    # Buckets indexed by epoch for aligned trace
    bucket_map = {b["epoch"]: b for b in buckets}

    for ep in episodes:
        start_dt = parse_iso(ep.get("start_ts"))
        end_dt = parse_iso(ep.get("end_ts"))
        if not start_dt or not end_dt:
            continue

        start_epoch = start_dt.timestamp()
        end_epoch = end_dt.timestamp()

        # Before window: [start - 60s, start) -> must be upright standing
        before_samples = [hr for ep_t, hr, st, is_std in valid_raw_hr if (start_epoch - 60.0 <= ep_t < start_epoch) and is_std and st == "UPRIGHT"]
        during_samples = [hr for ep_t, hr, st, is_std in valid_raw_hr if start_epoch <= ep_t <= end_epoch]
        after_samples = [hr for ep_t, hr, st, is_std in valid_raw_hr if end_epoch < ep_t <= end_epoch + 60.0]

        hr_before = round(statistics.mean(before_samples), 1) if len(before_samples) >= MIN_HR_SAMPLES_WINDOW else None
        hr_during = round(statistics.mean(during_samples), 1) if len(during_samples) >= MIN_HR_SAMPLES_WINDOW else None
        hr_after = round(statistics.mean(after_samples), 1) if len(after_samples) >= MIN_HR_SAMPLES_WINDOW else None

        delta_during = round(hr_during - hr_before, 1) if (hr_before is not None and hr_during is not None) else None

        ep_record = {
            "start_ts": ep.get("start_ts"),
            "duration_ms": ep.get("duration_ms"),
            "max_level": ep.get("max_level"),
            "peak_pitch_deg": ep.get("peak_pitch_deg"),
            "hr_before": hr_before,
            "hr_during": hr_during,
            "hr_after": hr_after,
            "delta_during": delta_during,
            "_start_epoch": start_epoch,
            "_hr_before": hr_before,
        }
        per_episode.append(ep_record)

        if hr_before is not None and hr_during is not None:
            used_episodes.append(ep_record)

    # Average delta during
    if len(used_episodes) >= 3:
        avg_delta = round(statistics.mean([e["delta_during"] for e in used_episodes]), 1)
        average_summary = {"delta_during": avg_delta, "n": len(used_episodes)}
    else:
        average_summary = {"delta_during": None, "n": len(used_episodes)}

    # Aligned trace: 5s bins from -60s to +60s relative to start
    # Bin center or bin start: offset = -60, -55, ..., +60
    offsets_s = list(range(-60, 65, 5))
    aligned_hr_mean = []
    aligned_n = []

    for off in offsets_s:
        bin_deltas = []
        for ep in used_episodes:
            base_hr = ep["_hr_before"]
            ep_start = ep["_start_epoch"]
            # Look up bucket near ep_start + off
            target_epoch = (int((ep_start + off) // 5)) * 5.0
            b = bucket_map.get(target_epoch)
            if b and b["hr"] is not None:
                bin_deltas.append(b["hr"] - base_hr)

        if len(bin_deltas) >= 3:
            aligned_hr_mean.append(round(statistics.mean(bin_deltas), 1))
            aligned_n.append(len(bin_deltas))
        else:
            aligned_hr_mean.append(None)
            aligned_n.append(len(bin_deltas))

    # Strip internal keys
    clean_per_ep = []
    for e in per_episode:
        clean_e = {k: v for k, v in e.items() if not k.startswith("_")}
        clean_per_ep.append(clean_e)

    return {
        "episodes_considered": len(per_episode),
        "episodes_used": len(used_episodes),
        "per_episode": clean_per_ep,
        "average": average_summary,
        "aligned_trace": {
            "offsets_s": offsets_s,
            "hr_mean": aligned_hr_mean,
            "n": aligned_n,
        },
    }


def _analyze_correlations(buckets):
    """
    Compute correlations in exact required order:
    1. pitch_deg vs heart_rate_bpm
    2. bend_duration_s vs heart_rate_bpm (only buckets where bending)
    3. temperature_c vs heart_rate_bpm
    4. humidity_pct vs heart_rate_bpm
    5. temperature_c vs humidity_pct
    """
    pairs_def = [
        ("pitch_deg", "heart_rate_bpm", "pitch", "hr", False),
        ("bend_duration_s", "heart_rate_bpm", "bend_duration_s", "hr", True),
        ("temperature_c", "heart_rate_bpm", "temp", "hr", False),
        ("humidity_pct", "heart_rate_bpm", "hum", "hr", False),
        ("temperature_c", "humidity_pct", "temp", "hum", False),
    ]

    results = []

    for x_name, y_name, x_key, y_key, only_bending in pairs_def:
        x_vals = []
        y_vals = []

        for b in buckets:
            if only_bending and b.get("bend_duration_s", 0) <= 0:
                continue
            xv = b.get(x_key)
            yv = b.get(y_key)
            if xv is not None and yv is not None:
                x_vals.append(float(xv))
                y_vals.append(float(yv))

        n = len(x_vals)
        r, slope, intercept, reason = calculate_pearson_r(x_vals, y_vals)
        strength, direction = get_correlation_labels(r)

        record = {
            "x": x_name,
            "y": y_name,
            "n": n,
            "r": round(r, 2) if r is not None else None,
            "strength": strength,
            "direction": direction,
            "slope": round(slope, 3) if slope is not None else None,
            "intercept": round(intercept, 2) if intercept is not None else None,
        }
        if reason:
            record["reason"] = reason

        results.append(record)

    return results


def _build_series(buckets, max_points=800):
    """Build series list for overlay chart, downsampled if needed."""
    if not buckets:
        return []

    if len(buckets) <= max_points:
        return [
            {
                "t": b["ts"],
                "pitch": round(b["pitch"], 1) if b["pitch"] is not None else None,
                "hr": round(b["hr"], 1) if b["hr"] is not None else None,
                "temp": round(b["temp"], 1) if b["temp"] is not None else None,
                "hum": round(b["hum"], 1) if b["hum"] is not None else None,
                "cat": b["category"],
            }
            for b in buckets
        ]

    # Downsampling / chunk merging keeping highest severity category
    step = len(buckets) / float(max_points)
    sampled = []
    severity_order = {"ALERT": 4, "WARNING": 3, "SITTING": 2, "UPRIGHT": 1}

    for i in range(max_points):
        start_idx = int(i * step)
        end_idx = min(len(buckets), int((i + 1) * step))
        chunk = buckets[start_idx:end_idx]
        if not chunk:
            continue

        # Highest severity in chunk
        highest_cat = max(chunk, key=lambda c: severity_order.get(c["category"], 0))["category"]

        # Means across chunk
        def chunk_avg(key):
            vals = [c[key] for c in chunk if c[key] is not None]
            return round(statistics.mean(vals), 1) if vals else None

        sampled.append({
            "t": chunk[0]["ts"],
            "pitch": chunk_avg("pitch"),
            "hr": chunk_avg("hr"),
            "temp": chunk_avg("temp"),
            "hum": chunk_avg("hum"),
            "cat": highest_cat,
        })

    return sampled


def _generate_insights(by_posture, episode_impact, correlations, quality, buckets):
    """
    Generate conservative server-side insights following strict rules:
    1. Posture difference: UPRIGHT vs (WARNING or ALERT combined)
    2. Sitting: SITTING vs UPRIGHT
    3. Episode effect: average.delta_during
    4. Correlations: |r| >= 0.30 and n >= MIN_BUCKETS_CORR
    5. Environment: Temp change >= 1.0 C across range
    6. Data quality: HR coverage < 50%
    7. Fallback: Not enough data
    """
    insights = []

    # Rule 6: Data quality warning first if HR coverage < 50% (only if we have data)
    if quality.get("hr_valid_pct", 0) < 50.0 and len(buckets) > 0:
        insights.append({
            "level": "warning",
            "text": f"Heart-rate signal is patchy ({quality['hr_valid_pct']}% valid coverage) — physiological trends may be unreliable.",
            "n": quality.get("hr_valid_pct"),
        })

    # Rule 1: Posture difference (WARNING/ALERT combined vs UPRIGHT)
    upright_b = by_posture["UPRIGHT"]
    warn_b = by_posture["WARNING"]
    alert_b = by_posture["ALERT"]

    # Combine valid HR buckets for warning and alert
    upright_hr_n = upright_b["hr"]["n"]
    stoop_hr_n = warn_b["hr"]["n"] + alert_b["hr"]["n"]

    if upright_hr_n >= MIN_BUCKETS_PER_GROUP and stoop_hr_n >= MIN_BUCKETS_PER_GROUP:
        # Calculate combined mean HR for warning + alert
        # Weighted mean by bucket counts
        w_hr_sum = (warn_b["hr"]["mean"] * warn_b["hr"]["n"] if warn_b["hr"]["mean"] else 0.0) + \
                   (alert_b["hr"]["mean"] * alert_b["hr"]["n"] if alert_b["hr"]["mean"] else 0.0)
        stoop_mean_hr = w_hr_sum / stoop_hr_n
        upright_mean_hr = upright_b["hr"]["mean"]
        diff = stoop_mean_hr - upright_mean_hr

        if abs(diff) >= 3.0:
            direction_str = f"+{diff:.1f}" if diff > 0 else f"{diff:.1f}"
            insights.append({
                "level": "info",
                "text": f"Heart rate averaged {stoop_mean_hr:.1f} bpm while in WARNING/ALERT vs {upright_mean_hr:.1f} bpm upright ({direction_str} bpm, n = {stoop_hr_n} and {upright_hr_n} buckets). Correlation is not causation.",
                "n": stoop_hr_n + upright_hr_n,
            })
        else:
            diff_str = f"+{diff:.1f}" if diff > 0 else f"{diff:.1f}"
            insights.append({
                "level": "info",
                "text": f"No clear heart-rate difference between bending and upright ({diff_str} bpm, n = {stoop_hr_n} and {upright_hr_n} buckets). Small differences are within normal variation.",
                "n": stoop_hr_n + upright_hr_n,
            })

    # Rule 2: Sitting vs Upright
    sit_b = by_posture["SITTING"]
    sit_hr_n = sit_b["hr"]["n"]
    if upright_hr_n >= MIN_BUCKETS_PER_GROUP and sit_hr_n >= MIN_BUCKETS_PER_GROUP:
        sit_mean = sit_b["hr"]["mean"]
        up_mean = upright_b["hr"]["mean"]
        diff_sit = sit_mean - up_mean

        if abs(diff_sit) >= 3.0:
            diff_str = f"+{diff_sit:.1f}" if diff_sit > 0 else f"{diff_sit:.1f}"
            insights.append({
                "level": "info",
                "text": f"Heart rate averaged {sit_mean:.1f} bpm while sitting vs {up_mean:.1f} bpm upright ({diff_str} bpm, n = {sit_hr_n} and {upright_hr_n} buckets).",
                "n": sit_hr_n + upright_hr_n,
            })
        else:
            diff_str = f"+{diff_sit:.1f}" if diff_sit > 0 else f"{diff_sit:.1f}"
            insights.append({
                "level": "info",
                "text": f"No clear heart-rate difference between sitting and upright ({diff_str} bpm, n = {sit_hr_n} and {upright_hr_n} buckets).",
                "n": sit_hr_n + upright_hr_n,
            })

    # Rule 3: Episode effect
    avg_delta = episode_impact["average"]["delta_during"]
    used_eps_n = episode_impact["average"]["n"]
    if avg_delta is not None and used_eps_n >= 3:
        sign_str = f"+{avg_delta:.1f}" if avg_delta > 0 else f"{avg_delta:.1f}"
        insights.append({
            "level": "info",
            "text": f"On average heart rate changed by {sign_str} bpm during bends (n = {used_eps_n} episodes).",
            "n": used_eps_n,
        })

    # Rule 4: Correlations (|r| >= 0.30 and n >= MIN_BUCKETS_CORR)
    meaningful_corrs = [c for c in correlations if c["r"] is not None and abs(c["r"]) >= 0.30 and c["n"] >= MIN_BUCKETS_CORR]
    if meaningful_corrs:
        for c in meaningful_corrs:
            x_label = "pitch" if "pitch" in c["x"] else ("bend duration" if "bend" in c["x"] else ("air temperature" if "temp" in c["x"] else "humidity"))
            y_label = "heart rate" if "heart" in c["y"] else ("humidity" if "hum" in c["y"] else c["y"])
            dir_str = "moved together" if c["direction"] == "positive" else "moved in opposite directions"
            insights.append({
                "level": "info",
                "text": f"{x_label.capitalize()} and {y_label} {dir_str} (r = {c['r']:.2f}, {c['strength']}, n = {c['n']} buckets). Correlation is not causation.",
                "n": c["n"],
            })
    else:
        # Check if all HR pairs are below 0.10
        hr_corrs = [c for c in correlations if "heart_rate" in c["y"] and c["r"] is not None and c["n"] >= MIN_BUCKETS_CORR]
        if hr_corrs and all(abs(c["r"]) < 0.10 for c in hr_corrs):
            insights.append({
                "level": "info",
                "text": "No meaningful relationship found between posture angles and heart rate in this time range (all |r| < 0.10).",
                "n": sum(c["n"] for c in hr_corrs),
            })

    # Rule 5: Environment change >= 1.0 C across range
    temps = [b["temp"] for b in buckets if b["temp"] is not None]
    if len(temps) >= MIN_BUCKETS_PER_GROUP:
        start_temp = statistics.mean(temps[:MIN_BUCKETS_PER_GROUP])
        end_temp = statistics.mean(temps[-MIN_BUCKETS_PER_GROUP:])
        temp_delta = end_temp - start_temp
        if abs(temp_delta) >= 1.0:
            insights.append({
                "level": "info",
                "text": f"Air temperature changed from {start_temp:.1f} to {end_temp:.1f} °C over the range (coarse DHT11 air sensor).",
                "n": len(temps),
            })

    # Rule 7: Fallback if empty
    if not insights:
        insights.append({
            "level": "info",
            "text": "Not enough data to draw conclusions yet. Collect at least 5 minutes with several bends.",
            "n": len(buckets),
        })

    return insights
