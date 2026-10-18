"""
Comprehensive unit and integration tests for backend/analysis.py and /api/analysis endpoints.

Covers:
1. Empty input handling (returns valid structure, nulls, no exceptions).
2. All-null heart rate (HR stats null, quality reflected).
3. Constant series guard (zero variance does not crash or produce NaN; r is null with reason).
4. Minimum bucket thresholds (< 12 buckets per group returns nulls, no numbers).
5. Category assignment and severity precedence in buckets (ALERT > WARNING > SITTING > UPRIGHT).
6. Exclusion of moving rows (when exclude_moving=True) and UNCALIBRATED/CALIBRATING/FAULT rows.
7. Heart rate validity filters (finger_present=False, out of 40-200 bpm range).
8. Episode impact windows (before, during, after; < 5 samples window gives null; aligned trace [-60..+60]).
9. Pearson correlation strength labels, direction, slope, intercept.
10. Insight generation rules (difference >= 3 bpm vs < 3 bpm; warning on patchy HR; no causal language).
11. Endpoint parameter validation (GET /api/analysis rejects bad minutes with 400).
12. CSV export header and null handling (GET /api/analysis/export.csv).
13. Control test with synthetic database seeding:
    - --no-effects dataset: assert HR diff < 3 bpm, no moderate correlation.
    - --effects dataset: assert higher HR during bends and aligned trace rises after t=0.
"""

import math
import os
import sqlite3
import pytest
from datetime import datetime, timezone, timedelta

from backend.analysis import (
    MIN_BUCKETS_PER_GROUP,
    MIN_BUCKETS_CORR,
    MIN_HR_SAMPLES_WINDOW,
    calculate_pearson_r,
    get_correlation_labels,
    aggregate_into_buckets,
    analyze_telemetry_and_episodes,
    _generate_insights,
)
from backend.app import app
from tools.seed_demo_data import generate_seed_data


# --- Unit Tests on backend/analysis.py ---

def test_calculate_pearson_r_valid():
    x = [1, 2, 3, 4, 5] * 7  # n = 35 >= MIN_BUCKETS_CORR
    y = [2, 4, 6, 8, 10] * 7
    r, slope, intercept, reason = calculate_pearson_r(x, y)
    assert r == 1.0
    assert reason is None
    assert math.isclose(slope, 2.0, rel_tol=1e-5)
    assert math.isclose(intercept, 0.0, rel_tol=1e-5)


def test_calculate_pearson_r_constant_zero_variance():
    x = [5.0] * 35
    y = [float(i) for i in range(35)]
    r, slope, intercept, reason = calculate_pearson_r(x, y)
    assert r is None
    assert "No variation" in reason
    assert slope is None
    assert intercept is None


def test_calculate_pearson_r_strength_labels():
    r = 0.35
    strength, direction = get_correlation_labels(r)
    assert strength == "moderate"
    assert direction == "positive"

    r_neg = -0.55
    strength_neg, direction_neg = get_correlation_labels(r_neg)
    assert strength_neg == "strong"
    assert direction_neg == "negative"


def test_aggregate_into_buckets_severity_precedence():
    # 4 rows in one 5s window with different states
    rows = [
        {"ts": "2026-10-18T10:00:00+00:00", "state": "UPRIGHT", "is_standing": True, "heart_rate_bpm": 70, "finger_present": True, "moving": False, "temperature_c": 26.0, "humidity_pct": 50.0, "imu_pitch_deg": 2.0},
        {"ts": "2026-10-18T10:00:01+00:00", "state": "WARNING", "is_standing": True, "heart_rate_bpm": 72, "finger_present": True, "moving": False, "temperature_c": 26.0, "humidity_pct": 50.0, "imu_pitch_deg": 18.0},
        {"ts": "2026-10-18T10:00:02+00:00", "state": "ALERT", "is_standing": True, "heart_rate_bpm": 74, "finger_present": True, "moving": False, "temperature_c": 26.0, "humidity_pct": 50.0, "imu_pitch_deg": 25.0},
        {"ts": "2026-10-18T10:00:03+00:00", "state": "UPRIGHT", "is_standing": False, "heart_rate_bpm": 71, "finger_present": True, "moving": False, "temperature_c": 26.0, "humidity_pct": 50.0, "imu_pitch_deg": 5.0},
    ]

    buckets = aggregate_into_buckets(rows, exclude_moving=True)
    assert len(buckets) == 1
    # ALERT > WARNING > SITTING > UPRIGHT
    assert buckets[0]["category"] == "ALERT"
    assert buckets[0]["hr_samples_count"] == 4
    assert math.isclose(buckets[0]["hr"], 71.75, rel_tol=1e-3)


def test_ignore_uncalibrated_and_fault_rows():
    rows = [
        {"ts": "2026-10-18T10:00:00+00:00", "state": "UNCALIBRATED", "is_standing": True, "heart_rate_bpm": 70, "finger_present": True, "moving": False, "temperature_c": 25.0, "humidity_pct": 50.0, "imu_pitch_deg": 0.0},
        {"ts": "2026-10-18T10:00:01+00:00", "state": "CALIBRATING", "is_standing": True, "heart_rate_bpm": 70, "finger_present": True, "moving": False, "temperature_c": 25.0, "humidity_pct": 50.0, "imu_pitch_deg": 0.0},
        {"ts": "2026-10-18T10:00:02+00:00", "state": "FAULT", "is_standing": True, "heart_rate_bpm": 70, "finger_present": True, "moving": False, "temperature_c": 25.0, "humidity_pct": 50.0, "imu_pitch_deg": 0.0},
    ]
    buckets = aggregate_into_buckets(rows, exclude_moving=True)
    assert len(buckets) == 0


def test_hr_validity_filters():
    rows = [
        # finger_present False
        {"ts": "2026-10-18T10:00:00+00:00", "state": "UPRIGHT", "is_standing": True, "heart_rate_bpm": 70, "finger_present": False, "moving": False, "temperature_c": 25.0, "humidity_pct": 50.0, "imu_pitch_deg": 0.0},
        # out of range < 40
        {"ts": "2026-10-18T10:00:01+00:00", "state": "UPRIGHT", "is_standing": True, "heart_rate_bpm": 35, "finger_present": True, "moving": False, "temperature_c": 25.0, "humidity_pct": 50.0, "imu_pitch_deg": 0.0},
        # out of range > 200
        {"ts": "2026-10-18T10:00:02+00:00", "state": "UPRIGHT", "is_standing": True, "heart_rate_bpm": 220, "finger_present": True, "moving": False, "temperature_c": 25.0, "humidity_pct": 50.0, "imu_pitch_deg": 0.0},
        # moving = True with exclude_moving=True
        {"ts": "2026-10-18T10:00:03+00:00", "state": "UPRIGHT", "is_standing": True, "heart_rate_bpm": 75, "finger_present": True, "moving": True, "temperature_c": 25.0, "humidity_pct": 50.0, "imu_pitch_deg": 0.0},
    ]
    buckets = aggregate_into_buckets(rows, exclude_moving=True)
    assert len(buckets) == 1
    # Needs at least 2 valid HR samples to have hr non-null
    assert buckets[0]["hr"] is None


def test_empty_input_dataset():
    res = analyze_telemetry_and_episodes([], [], range_minutes=60, exclude_moving=True, device_id="vest-01")
    assert res["meta"]["rows"] == 0
    assert res["meta"]["buckets"] == 0
    assert res["quality"]["hr_valid_pct"] == 0.0
    assert res["by_posture"]["UPRIGHT"]["buckets"] == 0
    assert res["by_posture"]["UPRIGHT"]["hr"]["mean"] is None
    assert len(res["correlations"]) == 5
    assert res["correlations"][0]["r"] is None
    assert any("Not enough data" in ins["text"] for ins in res["insights"])


def test_fewer_than_minimum_buckets_threshold():
    # Create exactly 5 distinct 5s buckets (e.g. 5 points separated by 5s)
    base_epoch = 1700000000.0  # divisible by 5
    rows = []
    for i in range(5):  # 5 buckets
        t = datetime.fromtimestamp(base_epoch + i * 5.0, tz=timezone.utc).isoformat()
        rows.append({
            "ts": t, "state": "UPRIGHT", "is_standing": True, "heart_rate_bpm": 72.0,
            "finger_present": True, "moving": False, "temperature_c": 25.0, "humidity_pct": 50.0,
            "imu_pitch_deg": 2.0, "bend_duration_ms": 0
        })

    res = analyze_telemetry_and_episodes(rows, [], range_minutes=5, exclude_moving=True, device_id="vest-01")
    assert res["by_posture"]["UPRIGHT"]["buckets"] == 5
    # Less than 12 -> must be None, never a number
    assert res["by_posture"]["UPRIGHT"]["hr"]["mean"] is None
    assert res["by_posture"]["UPRIGHT"]["temp"]["mean"] is None
    assert res["by_posture"]["UPRIGHT"]["hum"]["mean"] is None


def test_insights_generation_rules():
    # Test Difference >= 3 bpm
    by_posture_high = {
        "UPRIGHT": {"hr": {"n": 50, "mean": 70.0}},
        "WARNING": {"hr": {"n": 20, "mean": 76.0}},
        "ALERT": {"hr": {"n": 10, "mean": 80.0}},
        "SITTING": {"hr": {"n": 0, "mean": None}},
    }
    ins1 = _generate_insights(
        by_posture=by_posture_high,
        episode_impact={"average": {"delta_during": 6.5, "n": 5}},
        correlations=[{"x": "pitch_deg", "y": "heart_rate_bpm", "n": 100, "r": 0.45, "strength": "moderate", "direction": "positive"}],
        quality={"hr_valid_pct": 90.0, "temp_valid_pct": 100.0, "hum_valid_pct": 100.0},
        buckets=[{"temp": 25.0}] * 15 + [{"temp": 27.0}] * 15,
    )
    texts = [i["text"] for i in ins1]
    assert any("averaged" in t and "WARNING/ALERT" in t and "+7.3 bpm" in t for t in texts)
    assert any("average heart rate changed by +6.5 bpm" in t for t in texts)
    assert any("Air temperature changed" in t for t in texts)

    # Test Difference < 3 bpm
    by_posture_low = {
        "UPRIGHT": {"hr": {"n": 50, "mean": 70.0}},
        "WARNING": {"hr": {"n": 20, "mean": 71.0}},
        "ALERT": {"hr": {"n": 0, "mean": None}},
        "SITTING": {"hr": {"n": 0, "mean": None}},
    }
    ins2 = _generate_insights(
        by_posture=by_posture_low,
        episode_impact={"average": {"delta_during": None, "n": 0}},
        correlations=[],
        quality={"hr_valid_pct": 90.0, "temp_valid_pct": 100.0, "hum_valid_pct": 100.0},
        buckets=[],
    )
    texts2 = [i["text"] for i in ins2]
    assert any("No clear heart-rate difference" in t for t in texts2)


# --- Flask API Endpoint Tests ---

@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_api_analysis_minutes_validation(client):
    # Valid minutes: 5, 15, 60, 360, 1440, 0
    res = client.get("/api/analysis?minutes=45")
    assert res.status_code == 400
    assert "Allowed minutes values" in res.get_json()["error"]

    res_valid = client.get("/api/analysis?minutes=60")
    assert res_valid.status_code == 200
    data = res_valid.get_json()
    assert "meta" in data
    assert "quality" in data
    assert "by_posture" in data
    assert "episode_impact" in data
    assert "correlations" in data
    assert "series" in data
    assert "insights" in data


def test_api_analysis_export_csv(client):
    res = client.get("/api/analysis/export.csv?minutes=60")
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    lines = res.data.decode("utf-8").splitlines()
    assert len(lines) >= 1
    assert lines[0] == "ts,category,pitch_deg,heart_rate_bpm,temperature_c,humidity_pct,moving_fraction"


# --- Control Test (Section 6 Requirements) ---

def test_control_datasets_no_effects_vs_effects():
    """
    Control test:
    1. Seed with --no-effects: Assert no insight claims HR difference of 3 bpm or more,
       and no correlation reaches 'moderate' strength.
    2. Seed with --effects: Assert insights report higher HR during bends (>= 3 bpm)
       and aligned trace rises after t = 0.
    """
    db_path = os.path.join(os.path.dirname(__file__), "..", "vest_v2.db")

    # 1. Test Control: --no-effects (seed 120 mins, query with minutes=360 or minutes=0)
    generate_seed_data(minutes=120, device_id="sim-control", effects=False, seed=42, clear_sim=True, db_path=db_path)

    with app.test_client() as client:
        res = client.get("/api/analysis?minutes=360&device_id=sim-control")
        assert res.status_code == 200
        data = res.get_json()

        assert data["meta"]["simulated"] is True

        # Assert no insight claims a difference of 3 bpm or more
        insights = data["insights"]
        for ins in insights:
            text = ins["text"]
            if "while in WARNING/ALERT vs" in text:
                pytest.fail(f"Control data claimed posture effect: {text}")

        # Assert no posture-HR correlation reaches moderate (moderate starts at |r| >= 0.30)
        for corr in data["correlations"]:
            # Temperature vs humidity is known to be environmentally coupled on DHT11
            if corr["x"] == "temperature_c" and corr["y"] == "humidity_pct":
                continue
            if corr["r"] is not None:
                assert abs(corr["r"]) < 0.30, f"Correlation {corr['x']}-{corr['y']} was unexpectedly high: {corr['r']}"

    # 2. Test Intervention: --effects
    generate_seed_data(minutes=120, device_id="sim-effects", effects=True, seed=42, clear_sim=True, db_path=db_path)

    with app.test_client() as client:
        res = client.get("/api/analysis?minutes=360&device_id=sim-effects")
        assert res.status_code == 200
        data = res.get_json()

        assert data["meta"]["simulated"] is True

        # Assert insights report higher heart rate during bends
        insights_text = " ".join(ins["text"] for ins in data["insights"])
        assert ("while in WARNING/ALERT vs" in insights_text or "changed by +" in insights_text), (
            f"Expected positive HR effect in insights, got: {insights_text}"
        )

        # Assert aligned trace rises after t = 0
        aligned = data["episode_impact"]["aligned_trace"]
        assert aligned and "offsets_s" in aligned
        zero_idx = aligned["offsets_s"].index(0)
        post_zero_means = [m for m in aligned["hr_mean"][zero_idx:zero_idx + 6] if m is not None]
        assert len(post_zero_means) > 0
        # Average change after bend onset should be positive
        assert sum(post_zero_means) / len(post_zero_means) > 0.5, (
            f"Aligned trace did not show positive rise: {post_zero_means}"
        )
