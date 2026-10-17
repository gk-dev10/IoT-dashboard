"""Command management: queuing, expiration, merging for device response, and history."""

import json
from datetime import datetime, timezone
from backend.models import get_current_utc_iso


def create_command(conn, device_id, cmd_type, payload):
    """Insert a new pending command into the database."""
    now_iso = get_current_utc_iso()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO commands (created_ts, device_id, type, payload_json, status, sent_ts)
        VALUES (?, ?, ?, ?, 'pending', NULL)
    """, (now_iso, device_id or "vest-01", cmd_type, json.dumps(payload)))
    cmd_id = cursor.lastrowid
    conn.commit()

    return {
        "id": cmd_id,
        "created_ts": now_iso,
        "device_id": device_id or "vest-01",
        "type": cmd_type,
        "payload": payload,
        "status": "pending",
        "sent_ts": None,
    }


def expire_stale_commands(conn, max_age_seconds=60):
    """Mark any pending commands older than max_age_seconds as expired."""
    now = datetime.now(timezone.utc).timestamp()
    cutoff_ts = now - max_age_seconds

    cursor = conn.cursor()
    # Fetch pending commands to inspect timestamp
    cursor.execute("SELECT id, created_ts FROM commands WHERE status = 'pending'")
    rows = cursor.fetchall()

    expired_ids = []
    for r in rows:
        try:
            created_dt = datetime.fromisoformat(r["created_ts"])
            if created_dt.timestamp() < cutoff_ts:
                expired_ids.append(r["id"])
        except Exception:
            expired_ids.append(r["id"])

    if expired_ids:
        placeholders = ",".join("?" for _ in expired_ids)
        cursor.execute(f"UPDATE commands SET status = 'expired' WHERE id IN ({placeholders})", expired_ids)
        conn.commit()

    return expired_ids


def get_pending_commands_for_device(conn, device_id=None):
    """Fetch all pending commands for a device (oldest first)."""
    expire_stale_commands(conn, max_age_seconds=60)

    cursor = conn.cursor()
    if device_id:
        cursor.execute("""
            SELECT id, created_ts, device_id, type, payload_json, status, sent_ts
            FROM commands
            WHERE status = 'pending' AND (device_id = ? OR device_id IS NULL OR device_id = '')
            ORDER BY id ASC
        """, (device_id,))
    else:
        cursor.execute("""
            SELECT id, created_ts, device_id, type, payload_json, status, sent_ts
            FROM commands
            WHERE status = 'pending'
            ORDER BY id ASC
        """)

    rows = cursor.fetchall()
    results = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except Exception:
            payload = {}
        results.append({
            "id": r["id"],
            "created_ts": r["created_ts"],
            "device_id": r["device_id"],
            "type": r["type"],
            "payload": payload,
            "status": r["status"],
            "sent_ts": r["sent_ts"],
        })
    return results


def merge_commands(pending_commands):
    """
    Merge multiple pending commands into one payload dictionary according to protocol rules:
    - calibrate: true if any
    - mute_s: integer seconds from latest mute command
    - test: target from latest test command
    - config: merged dictionary containing the latest value for each field
    """
    if not pending_commands:
        return None

    calibrate = False
    mute_s = None
    test_target = None
    config_dict = {}

    for cmd in pending_commands:
        c_type = cmd["type"]
        payload = cmd.get("payload", {})

        if c_type == "calibrate":
            calibrate = True

        elif c_type == "mute":
            # Can be in payload['seconds'] or payload['mute_s']
            if "seconds" in payload:
                mute_s = int(payload["seconds"])
            elif "mute_s" in payload:
                mute_s = int(payload["mute_s"])

        elif c_type == "test":
            target = payload.get("target")
            if target:
                test_target = target

        elif c_type == "config":
            cfg = payload.get("config", payload)
            for k in ("bend_on_deg", "bend_off_deg", "vibrate_delay_s", "buzzer_delay_s"):
                if k in cfg and cfg[k] is not None:
                    config_dict[k] = float(cfg[k])

    result = {}
    if calibrate:
        result["calibrate"] = True
    if mute_s is not None:
        result["mute_s"] = mute_s
    if test_target is not None:
        result["test"] = test_target
    if config_dict:
        result["config"] = config_dict

    return result if result else None


def mark_commands_sent(conn, command_ids):
    """Mark list of command IDs as sent with current UTC timestamp."""
    if not command_ids:
        return
    now_iso = get_current_utc_iso()
    placeholders = ",".join("?" for _ in command_ids)
    conn.execute(
        f"UPDATE commands SET status = 'sent', sent_ts = ? WHERE id IN ({placeholders})",
        [now_iso] + list(command_ids)
    )
    conn.commit()


def get_recent_commands(conn, limit=5):
    """Retrieve the most recent commands with their statuses."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, created_ts, device_id, type, payload_json, status, sent_ts
        FROM commands
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    results = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"])
        except Exception:
            payload = {}
        results.append({
            "id": r["id"],
            "created_ts": r["created_ts"],
            "device_id": r["device_id"],
            "type": r["type"],
            "payload": payload,
            "status": r["status"],
            "sent_ts": r["sent_ts"],
        })
    return results
