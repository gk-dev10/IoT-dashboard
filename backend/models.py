"""Validation rules, data sanitization, and protocol helpers for Posture T-Shirt v2."""

from datetime import datetime, timezone
import json


def get_current_utc_iso():
    """Return timezone-aware ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat()


def validate_command_payload(data):
    """
    Validate incoming command posted from UI.
    Returns (is_valid: bool, error_message: str or None, sanitized_payload: dict).
    """
    if not isinstance(data, dict):
        return False, "Request body must be a JSON object", None

    cmd_type = data.get("type")
    if not cmd_type or not isinstance(cmd_type, str):
        return False, "Command must contain a valid 'type' string", None

    cmd_type = cmd_type.strip().lower()

    if cmd_type == "calibrate":
        return True, None, {"type": "calibrate"}

    elif cmd_type == "mute":
        # seconds can be provided under 'seconds' or 'mute_s'
        sec = data.get("seconds", data.get("mute_s"))
        if sec is None or not isinstance(sec, (int, float)):
            return False, "Mute command requires integer 'seconds'", None
        sec = int(sec)
        if sec < 0 or sec > 86400:
            return False, "Mute seconds must be between 0 and 86400", None
        return True, None, {"type": "mute", "seconds": sec}

    elif cmd_type == "test":
        target = data.get("target")
        if not target or target not in ("buzzer", "vibration", "leds"):
            return False, "Test command target must be one of 'buzzer', 'vibration', 'leds'", None
        return True, None, {"type": "test", "target": target}

    elif cmd_type == "config":
        # Config can have any subset of the four fields:
        # bend_on_deg (5-60), bend_off_deg (2-58, <= bend_on - 2)
        # vibrate_delay_s (1-60), buzzer_delay_s (2-120, > vibrate_delay_s)
        config = {}
        allowed_keys = ("bend_on_deg", "bend_off_deg", "vibrate_delay_s", "buzzer_delay_s")
        has_any = False

        for k in allowed_keys:
            if k in data and data[k] is not None:
                val = data[k]
                if not isinstance(val, (int, float)):
                    return False, f"Config field '{k}' must be numeric", None
                config[k] = float(val)
                has_any = True

        if not has_any:
            return False, "Config command must specify at least one threshold/delay field", None

        bend_on = config.get("bend_on_deg")
        bend_off = config.get("bend_off_deg")
        vib_del = config.get("vibrate_delay_s")
        buz_del = config.get("buzzer_delay_s")

        if bend_on is not None and not (5.0 <= bend_on <= 60.0):
            return False, f"bend_on_deg must be between 5.0 and 60.0 degrees (got {bend_on})", None

        if bend_off is not None and not (2.0 <= bend_off <= 58.0):
            return False, f"bend_off_deg must be between 2.0 and 58.0 degrees (got {bend_off})", None

        if bend_on is not None and bend_off is not None:
            if bend_off > (bend_on - 2.0):
                return False, f"bend_off_deg ({bend_off}) must be at most bend_on_deg - 2 ({bend_on - 2.0})", None

        if vib_del is not None and not (1.0 <= vib_del <= 60.0):
            return False, f"vibrate_delay_s must be between 1.0 and 60.0 seconds (got {vib_del})", None

        if buz_del is not None and not (2.0 <= buz_del <= 120.0):
            return False, f"buzzer_delay_s must be between 2.0 and 120.0 seconds (got {buz_del})", None

        if vib_del is not None and buz_del is not None:
            if buz_del <= vib_del:
                return False, f"buzzer_delay_s ({buz_del}) must be greater than vibrate_delay_s ({vib_del})", None

        return True, None, {"type": "config", "config": config}

    else:
        return False, f"Unknown command type '{cmd_type}'", None


def sanitize_telemetry(payload, now_iso):
    """
    Sanitize and extract telemetry fields.
    Does NOT convert null to 0. Keeps None for SQL NULL.
    """
    if not isinstance(payload, dict):
        payload = {}

    def get_num(key, cast_fn=float):
        v = payload.get(key)
        if v is None:
            return None
        try:
            return cast_fn(v)
        except (ValueError, TypeError):
            return None

    def get_bool(key):
        v = payload.get(key)
        if v is None:
            return None
        return 1 if bool(v) else 0

    def get_str(key, default=""):
        v = payload.get(key)
        if v is None:
            return default
        return str(v)

    return {
        "ts": now_iso,
        "device_id": get_str("device_id", "vest-01"),
        "fw": get_str("fw", "unknown"),
        "uptime_s": get_num("uptime_s", int),
        "state": get_str("state", "UNCALIBRATED").upper(),
        "armed": get_bool("armed"),
        "muted": get_bool("muted"),
        "is_standing": get_bool("is_standing"),
        "moving": get_bool("moving"),
        "bend_detected": get_bool("bend_detected"),
        "possible_bend": get_bool("possible_bend"),
        "bend_duration_ms": get_num("bend_duration_ms", int),
        "imu_pitch_deg": get_num("imu_pitch_deg", float),
        "imu_roll_deg": get_num("imu_roll_deg", float),
        "imu_says_bent": get_bool("imu_says_bent"),
        "flex_upper": get_num("flex_upper", float),
        "flex_lower": get_num("flex_lower", float),
        "flex_says_bent": get_bool("flex_says_bent"),
        "adxl_tilt_deg": get_num("adxl_tilt_deg", float),
        "vibration_active": get_bool("vibration_active"),
        "buzzer_active": get_bool("buzzer_active"),
        "led_green": get_bool("led_green"),
        "led_yellow": get_bool("led_yellow"),
        "led_red": get_bool("led_red"),
        "heart_rate_bpm": get_num("heart_rate_bpm", int),
        "finger_present": get_bool("finger_present"),
        "temperature_c": get_num("temperature_c", float),
        "humidity_pct": get_num("humidity_pct", float),
        "mpu_ok": get_bool("mpu_ok"),
        "adxl_ok": get_bool("adxl_ok"),
        "max_ok": get_bool("max_ok"),
        "flex_enabled": get_bool("flex_enabled"),
        "bend_on_deg": get_num("bend_on_deg", float),
        "bend_off_deg": get_num("bend_off_deg", float),
        "vibrate_delay_s": get_num("vibrate_delay_s", float),
        "buzzer_delay_s": get_num("buzzer_delay_s", float),
        "wifi_rssi": get_num("wifi_rssi", int),
    }
