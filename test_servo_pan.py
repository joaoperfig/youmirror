"""
Pan servo sanity-check (channel 0).

The pan servo has a 236° total range (118° each direction from the centre).
Angles are expressed in physical servo degrees:
    0°   = hard left end
    118° = centre (home)
    236° = hard right end

All movements in this script are expressed as offsets from PAN_HOME_ANGLE
(config.py) so the test stays valid after you update the home angle.

Usage
-----
    python3 test_servo_pan.py
"""

import sys
import time

import config
from servo_control import ServoController


def prompt(message: str) -> None:
    """Print a labelled step and wait briefly so the move is visible."""
    print(f"\n  ▶  {message}")
    time.sleep(0.5)


def move(servo: ServoController, angle: float, label: str) -> None:
    """Command the pan servo and print what is happening."""
    clamped = max(config.PAN_MIN_ANGLE, min(config.PAN_MAX_ANGLE, angle))
    if clamped != angle:
        print(f"     (clamped {angle:.1f}° → {clamped:.1f}° by software limits)")
    servo.set_pan(clamped)
    time.sleep(0.8)   # give the servo time to reach position


def sweep(servo: ServoController, start: float, end: float, steps: int = 10) -> None:
    """Slowly sweep from start to end angle."""
    for i in range(steps + 1):
        angle = start + (end - start) * i / steps
        angle = max(config.PAN_MIN_ANGLE, min(config.PAN_MAX_ANGLE, angle))
        servo.set_angle(config.PAN_CHANNEL, angle)
        time.sleep(0.06)


def main() -> None:
    home = float(config.PAN_HOME_ANGLE)

    print("=" * 55)
    print("  youmirror – pan servo sanity check")
    print(f"  Channel      : {config.PAN_CHANNEL}")
    print(f"  Servo range  : 0° – {config.PAN_SERVO_RANGE}°  ({config.PAN_SERVO_RANGE/2:.0f}° each side)")
    print(f"  Home angle   : {home}°")
    print(f"  Soft limits  : {config.PAN_MIN_ANGLE}° – {config.PAN_MAX_ANGLE}°")
    print("=" * 55)
    input("\n  Press Enter to start (Ctrl-C to abort at any time)…")

    servo = ServoController()

    try:
        # ── 1. Centre ──────────────────────────────────────────────────────
        prompt("HOME – moving to centre position")
        move(servo, home, "home")

        # ── 2. Small nudges ────────────────────────────────────────────────
        prompt("RIGHT +20° nudge")
        move(servo, home + 20, "right 20")

        prompt("HOME")
        move(servo, home, "home")

        prompt("LEFT -20° nudge")
        move(servo, home - 20, "left 20")

        prompt("HOME")
        move(servo, home, "home")

        # ── 3. Mid-range swings ────────────────────────────────────────────
        prompt("RIGHT +60°")
        move(servo, home + 60, "right 60")

        prompt("HOME")
        move(servo, home, "home")

        prompt("LEFT -60°")
        move(servo, home - 60, "left 60")

        prompt("HOME")
        move(servo, home, "home")

        # ── 4. Near mechanical limits ─────────────────────────────────────
        prompt("RIGHT +100° (watch for mechanical stop)")
        move(servo, home + 100, "right 100")

        prompt("HOME")
        move(servo, home, "home")

        prompt("LEFT -100° (watch for mechanical stop)")
        move(servo, home - 100, "left 100")

        prompt("HOME")
        move(servo, home, "home")

        # ── 5. Full-range slow sweep ───────────────────────────────────────
        prompt("SLOW SWEEP: left limit → right limit → home")
        half_range  = config.PAN_SERVO_RANGE / 2
        left_limit  = max(config.PAN_MIN_ANGLE, home - half_range)
        right_limit = min(config.PAN_MAX_ANGLE, home + half_range)
        sweep(servo, home, left_limit,  steps=20)
        sweep(servo, left_limit, right_limit, steps=40)
        sweep(servo, right_limit, home, steps=20)

        print("\n  ✓  All tests done. Servo is at home position.\n")

    except KeyboardInterrupt:
        print("\n  Aborted by user.")
    finally:
        print("  Returning to home and releasing…")
        servo.home()
        time.sleep(0.5)
        servo.shutdown()


if __name__ == "__main__":
    main()
