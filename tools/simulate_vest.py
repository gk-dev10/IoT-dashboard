#!/usr/bin/env python3
"""
Smart Posture T-Shirt (v2) — Hardware Simulator Tool.

Simulates the ESP32 wearable vest over HTTP POST:
- Realistic sensor kinematics (MPU pitch, ADXL thigh tilt, MAX30105 HR, DHT11 air temp)
- Realistic state machine (UNCALIBRATED, CALIBRATING, UPRIGHT, WARNING, ALERT)
- Obeys bi-directional commands returned from the server (calibrate, mute, test, config)
"""

import argparse
import math
import random
import sys
import time
import requests


def parse_args():
    parser = argparse.ArgumentParser(description="Simulate Smart Posture T-Shirt ESP32 Telemetry")
    parser.add_argument("--url", default="http://localhost:5000/api/data", help="Backend ingest URL")
    parser.add_argument("--token", default="change-me", help="Device authentication token")
    parser.add_argument("--interval", type=float, default=1.0, help="Upload interval in seconds")
    parser.add_argument("--scenario", choices=["demo", "idle"], default="demo", help="Simulation scenario")
    parser.add_argument("--device-id", default="vest-01", help="Device ID to report")
    return parser.parse_args()


class VestSimulator:
    def __init__(self, device_id="vest-01"):
        self.device_id = device_id
        self.fw = "2.1.0-sim"
        self.boot_time = time.time()

        # Configurable thresholds
        self.bend_on_deg = 20.0
        self.bend_off_deg = 15.0
        self.vibrate_delay_s = 5.0
        self.buzzer_delay_s = 15.0

        # State flags
        self.armed = False
        self.calibrating_until = 0.0
        self.mute_until = 0.0
        self.test_until = 0.0
        self.test_target = None

        # Kinematics & Posture
        self.is_standing = True
        self.moving = False
        self.adxl_tilt_deg = 10.0
        self.imu_pitch_deg = 4.0
        self.imu_roll_deg = 0.5
        self.bend_start_time = None

        # Physiological & Environmental baseline
        self.heart_rate = 74
        self.temp_c = 25.5
        self.humidity = 48.0
        self.rssi = -62

    def handle_command(self, cmd_key, cmd_val):
        """Process command received in server response."""
        now = time.time()
        print(f"\n[COMMAND RECEIVED] {cmd_key}: {cmd_val}")

        if cmd_key == "calibrate" and cmd_val:
            self.calibrating_until = now + 2.0
            print(" -> Starting 2-second calibration...")

        elif cmd_key == "mute_s":
            seconds = int(cmd_val)
            if seconds > 0:
                self.mute_until = now + seconds
                print(f" -> Muted alerts for {seconds}s (until +{seconds}s)")
            else:
                self.mute_until = 0.0
                print(" -> Alerts un-muted")

        elif cmd_key == "test":
            target = str(cmd_val).lower()
            if target in ("buzzer", "vibration", "leds"):
                self.test_target = target
                self.test_until = now + 2.0
                print(f" -> Testing actuator '{target}' for 2 seconds...")

        elif cmd_key == "config" and isinstance(cmd_val, dict):
            if "bend_on_deg" in cmd_val and 5.0 <= cmd_val["bend_on_deg"] <= 60.0:
                self.bend_on_deg = float(cmd_val["bend_on_deg"])
            if "bend_off_deg" in cmd_val and 2.0 <= cmd_val["bend_off_deg"] <= 58.0:
                self.bend_off_deg = float(cmd_val["bend_off_deg"])
            if "vibrate_delay_s" in cmd_val and 1.0 <= cmd_val["vibrate_delay_s"] <= 60.0:
                self.vibrate_delay_s = float(cmd_val["vibrate_delay_s"])
            if "buzzer_delay_s" in cmd_val and 2.0 <= cmd_val["buzzer_delay_s"] <= 120.0:
                self.buzzer_delay_s = float(cmd_val["buzzer_delay_s"])
            print(f" -> Updated config: on={self.bend_on_deg}°, off={self.bend_off_deg}°, vib_delay={self.vibrate_delay_s}s, buz_delay={self.buzzer_delay_s}s")

    def update_demo_scenario(self, loop_time):
        """
        Demo timeline (approx 60s total cycle):
        - 0s to 3s: initial auto-calibrate
        - 3s to 23s (20s): standing upright (pitch ~ 2-6°)
        - 23s to 41s (18s): bending forward (pitch rises to ~28°)
          - at 5s bend (t=28s): WARNING, vibration motor on, yellow LED
          - at 15s bend (t=38s): ALERT, buzzer on, red LED
        - 41s to 45s (4s): recovery to upright (pitch drops to ~4°)
        - 45s to 60s (15s): sitting down (pitch ~8°, thigh tilt ~85°, is_standing False)
        - at 60s: stand up and loop
        """
        cycle_pos = loop_time % 60.0
        noise = (random.random() - 0.5) * 1.2

        if cycle_pos < 3.0:
            # Auto-calibration on initial loop
            if not self.armed and self.calibrating_until == 0:
                self.calibrating_until = time.time() + 2.0
            self.is_standing = True
            self.adxl_tilt_deg = 8.0 + noise
            self.imu_pitch_deg = 2.0 + noise
            self.moving = False

        elif cycle_pos < 23.0:
            # Upright standing
            self.is_standing = True
            self.adxl_tilt_deg = 10.0 + noise
            self.imu_pitch_deg = 4.0 + noise
            self.moving = random.random() < 0.15

        elif cycle_pos < 41.0:
            # Forward bending
            bend_progress = (cycle_pos - 23.0) / 18.0
            # Target pitch: ramps smoothly up to 28°
            target_pitch = 20.0 + (8.5 * math.sin(bend_progress * math.pi * 0.95))
            self.is_standing = True
            self.adxl_tilt_deg = 12.0 + noise
            self.imu_pitch_deg = target_pitch + noise
            self.moving = False

        elif cycle_pos < 45.0:
            # Recovering to upright
            self.is_standing = True
            self.adxl_tilt_deg = 9.0 + noise
            self.imu_pitch_deg = 4.0 + noise
            self.moving = True

        else:
            # Sitting down
            self.is_standing = False
            self.adxl_tilt_deg = 84.0 + noise
            self.imu_pitch_deg = 7.0 + noise
            self.moving = False

    def update_idle_scenario(self, loop_time):
        """Idle upright scenario with natural human postural sway."""
        noise = (random.random() - 0.5) * 1.5
        self.is_standing = True
        self.adxl_tilt_deg = 9.5 + noise
        self.imu_pitch_deg = 3.5 + noise
        self.moving = random.random() < 0.1

    def step(self, scenario, loop_time):
        now = time.time()

        if scenario == "demo":
            self.update_demo_scenario(loop_time)
        else:
            self.update_idle_scenario(loop_time)

        # Check calibration status
        if self.calibrating_until > 0:
            if now < self.calibrating_until:
                state = "CALIBRATING"
                self.armed = False
            else:
                self.calibrating_until = 0.0
                self.armed = True
                state = "UPRIGHT"
        elif not self.armed:
            state = "UNCALIBRATED"
        else:
            # Evaluate posture
            is_pitch_bent = self.imu_pitch_deg >= self.bend_on_deg
            bend_confirmed = is_pitch_bent and self.is_standing

            if bend_confirmed:
                if self.bend_start_time is None:
                    self.bend_start_time = now
                duration_s = now - self.bend_start_time

                if duration_s >= self.buzzer_delay_s:
                    state = "ALERT"
                elif duration_s >= self.vibrate_delay_s:
                    state = "WARNING"
                else:
                    state = "UPRIGHT"
            else:
                # Reset bend timer once pitch falls below hysteresis threshold
                if self.imu_pitch_deg < self.bend_off_deg or not self.is_standing:
                    self.bend_start_time = None
                state = "UPRIGHT"

        # Calculate bend duration
        bend_duration_ms = 0
        if self.bend_start_time is not None and state in ("WARNING", "ALERT"):
            bend_duration_ms = int((now - self.bend_start_time) * 1000)

        # Check mute status
        is_muted = now < self.mute_until

        # Check actuator test status
        is_testing = now < self.test_until

        # Compute actuator states
        vibration_active = False
        buzzer_active = False
        led_green = False
        led_yellow = False
        led_red = False

        if state == "ALERT":
            if not is_muted:
                vibration_active = True
                buzzer_active = True
            led_red = True
        elif state == "WARNING":
            if not is_muted:
                vibration_active = True
            led_yellow = True
        elif state == "UPRIGHT":
            led_green = True
        elif state in ("UNCALIBRATED", "CALIBRATING"):
            # LEDs cycle or off
            pass

        # Handle active hardware test override
        if is_testing:
            if self.test_target == "buzzer":
                buzzer_active = True
            elif self.test_target == "vibration":
                vibration_active = True
            elif self.test_target == "leds":
                led_green = True
                led_yellow = True
                led_red = True

        # Slowly drift environmental sensors
        self.temp_c += (random.random() - 0.5) * 0.1
        self.humidity += (random.random() - 0.5) * 0.2
        self.temp_c = max(20.0, min(35.0, self.temp_c))
        self.humidity = max(30.0, min(80.0, self.humidity))

        # Heart rate simulation (with occasional null when finger lifts)
        if random.random() < 0.05:
            current_hr = None
            finger_present = False
        else:
            self.heart_rate += random.choice([-1, 0, 0, 1])
            self.heart_rate = max(60, min(95, self.heart_rate))
            current_hr = self.heart_rate
            finger_present = True

        uptime_s = int(now - self.boot_time)

        payload = {
            "device_id": self.device_id,
            "fw": self.fw,
            "uptime_s": uptime_s,
            "state": state,
            "armed": self.armed,
            "muted": is_muted,
            "is_standing": self.is_standing,
            "moving": self.moving,
            "bend_detected": (state in ("WARNING", "ALERT")),
            "possible_bend": (self.imu_pitch_deg >= self.bend_on_deg and not self.is_standing),
            "bend_duration_ms": bend_duration_ms,
            "imu_pitch_deg": round(self.imu_pitch_deg, 1),
            "imu_roll_deg": round(self.imu_roll_deg + (random.random() - 0.5) * 0.5, 1),
            "imu_says_bent": (self.imu_pitch_deg >= self.bend_on_deg),
            "flex_upper": None,
            "flex_lower": None,
            "flex_says_bent": None,
            "adxl_tilt_deg": round(self.adxl_tilt_deg, 1),
            "vibration_active": vibration_active,
            "buzzer_active": buzzer_active,
            "led_green": led_green,
            "led_yellow": led_yellow,
            "led_red": led_red,
            "heart_rate_bpm": current_hr,
            "finger_present": finger_present,
            "temperature_c": round(self.temp_c, 1),
            "humidity_pct": round(self.humidity, 1),
            "mpu_ok": True,
            "adxl_ok": True,
            "max_ok": True,
            "flex_enabled": False,
            "bend_on_deg": self.bend_on_deg,
            "bend_off_deg": self.bend_off_deg,
            "vibrate_delay_s": self.vibrate_delay_s,
            "buzzer_delay_s": self.buzzer_delay_s,
            "wifi_rssi": self.rssi + random.choice([-2, -1, 0, 1, 2]),
        }

        return payload


def main():
    args = parse_args()
    simulator = VestSimulator(device_id=args.device_id)

    print(f"=== Posture T-Shirt Simulator Started ===")
    print(f"Target:   {args.url}")
    print(f"Token:    {'*' * len(args.token)}")
    print(f"Scenario: {args.scenario}")
    print(f"Interval: {args.interval}s")
    print("Press Ctrl+C to stop.\n")

    start_sim_time = time.time()

    headers = {
        "Content-Type": "application/json",
        "X-Device-Token": args.token,
    }

    while True:
        loop_time = time.time() - start_sim_time
        payload = simulator.step(args.scenario, loop_time)

        try:
            resp = requests.post(args.url, headers=headers, json=payload, timeout=3.0)
            if resp.status_code in (200, 201):
                data = resp.json()
                commands = data.get("commands")
                if commands and isinstance(commands, dict):
                    for k, v in commands.items():
                        simulator.handle_command(k, v)

                # Format single line summary
                hr_display = f"{payload['heart_rate_bpm']} bpm" if payload["heart_rate_bpm"] else "no signal"
                actuators = []
                if payload["vibration_active"]:
                    actuators.append("VIB")
                if payload["buzzer_active"]:
                    actuators.append("BUZ")
                act_str = f" [{'+'.join(actuators)}]" if actuators else ""

                print(
                    f"[{payload['uptime_s']:04d}s] "
                    f"state={payload['state']:<12} "
                    f"pitch={payload['imu_pitch_deg']:>5.1f}° "
                    f"standing={'YES' if payload['is_standing'] else 'NO ':<3} "
                    f"bend_ms={payload['bend_duration_ms']:<5} "
                    f"HR={hr_display:<9} "
                    f"Temp={payload['temperature_c']}°C{act_str}"
                )
            else:
                print(f"[HTTP {resp.status_code}] {resp.text}")

        except requests.exceptions.RequestException as e:
            print(f"[CONNECTION ERROR] Failed to reach server: {e}")

        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSimulator stopped by user.")
        sys.exit(0)
