"""Headless browser smoke test for all dashboard pages and analysis ranges.

Requires Playwright for Python and its Chromium browser. Copies the source DB with
SQLite's backup API, never reseeds it, and generates a second copy with null HR.
"""
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "backend" / "vest_v2.db"
OUT = ROOT / "artifacts" / "browser-smoke"
PORT = 5139
RANGES = [5, 15, 60, 360, 1440, 0]
PAGES = ["live", "analysis", "history", "alerts"]


def backup_database(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)


def wait_for_server(url, process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Backend stopped before becoming ready")
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError(f"Backend did not start at {url}")


def run_database(db_path, screenshots=False):
    from playwright.sync_api import sync_playwright

    env = os.environ.copy()
    env["VEST_DB_PATH"] = str(db_path)
    env["VEST_PORT"] = str(PORT)
    backend = subprocess.Popen(
        [sys.executable, "-m", "backend.app"], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    console_errors = []
    try:
        base = f"http://127.0.0.1:{PORT}/"
        wait_for_server(base, backend)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.on("console", lambda msg: console_errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda error: console_errors.append(f"pageerror: {error}"))

            for minutes in RANGES:
                for route in PAGES:
                    page.goto(base + f"#/{route}", wait_until="domcontentloaded")
                    page.wait_for_timeout(800)
                    if route == "analysis":
                        button = page.locator(f'#range-control button[data-minutes="{minutes}"]')
                        button.click()
                        page.wait_for_timeout(900)
                        page.locator("#analysis-content").wait_for(state="visible")
                        if screenshots:
                            page.screenshot(path=OUT / f"analysis-{minutes if minutes else 'all'}.png", full_page=True)
            browser.close()
    finally:
        backend.terminate()
        try:
            backend.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend.kill()
            backend.wait()

    if console_errors:
        raise AssertionError("Browser console errors:\n" + "\n".join(console_errors))
    print(f"{db_path.name}: console errors: 0")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    real_copy = OUT / "real-data-backup.db"
    null_hr_copy = OUT / "null-heart-rate.db"
    backup_database(SOURCE_DB, real_copy)
    with sqlite3.connect(real_copy) as conn:
        conn.execute("DELETE FROM telemetry WHERE device_id LIKE 'sim-%'")
        conn.execute("DELETE FROM episodes WHERE device_id LIKE 'sim-%'")
    shutil.copy2(real_copy, null_hr_copy)
    with sqlite3.connect(null_hr_copy) as conn:
        conn.execute("UPDATE telemetry SET heart_rate_bpm = NULL, finger_present = 0")

    try:
        run_database(real_copy, screenshots=True)
        run_database(null_hr_copy)
    except ModuleNotFoundError as exc:
        if exc.name == "playwright":
            raise RuntimeError("Backups created, but browser smoke requires the Python Playwright package and Chromium") from exc
        raise
    print(f"screenshots: {OUT}")


if __name__ == "__main__":
    main()
