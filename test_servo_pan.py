"""
Pan servo range calibration + sanity-check (channel 0).

Phase 1 – Range discovery
    The servo is swept slowly toward each configured PWM extreme
    (config.PAN_MIN_ANGLE and config.PAN_MAX_ANGLE).  The servo physically
    stalls against its mechanical stop while the controller holds that pulse
    for a settle period, then the commanded angle is recorded as the limit.

    NOTE: Standard hobby servos on a PCA9685 have no position feedback –
    the PCA9685 only generates PWM pulses; it cannot read current or angle.
    The limits recorded here are therefore the commanded PWM extremes.
    If the actual mechanical stop is reached before the configured extreme,
    the servo will stall silently; the recorded limit will be slightly inside
    the true mechanical stop.  Listen for any grinding noise and press
    Ctrl-C to abort immediately.

Phase 2 – Pan tests (relative to discovered centre)
    Replicates the original nudge/swing/sweep tests, now referenced to the
    real measured centre rather than the hardcoded PAN_HOME_ANGLE.

Usage
-----
    python3 test_servo_pan.py
"""

import time
from typing import Optional

import config
from servo_control import ServoController


# ---------------------------------------------------------------------------
# Calibration parameters
# ---------------------------------------------------------------------------
_CAL_STEP_DEG  = 1.0   # degrees per step during calibration sweep
_CAL_STEP_WAIT = 0.04  # seconds between steps  (~25 steps/s → slow crawl)
_CAL_SETTLE    = 1.2   # seconds to hold at each extreme before recording
_HOME_HOLD     = 2.5   # seconds to hold centre pulse before killing signal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt(message: str) -> None:
    """Print a labelled step and pause so the movement is visible."""
    print(f"\n  ▶  {message}")
    time.sleep(0.5)


def _move(
    servo: ServoController,
    angle: float,
    left_limit: float,
    right_limit: float,
) -> None:
    """Command the pan servo, clamped to the discovered limits."""
    clamped = max(left_limit, min(right_limit, angle))
    if abs(clamped - angle) > 0.05:
        print(f"     (clamped {angle:.1f}° → {clamped:.1f}° by discovered limits)")
    servo.set_pan(clamped)
    time.sleep(0.8)


def _sweep_to(
    servo: ServoController,
    start: float,
    target: float,
    step: float = _CAL_STEP_DEG,
    wait: float = _CAL_STEP_WAIT,
) -> None:
    """Sweep the pan servo from *start* to *target* in *step* increments."""
    direction = 1.0 if target > start else -1.0
    angle = start
    while direction * (target - angle) > 1e-6:
        angle += direction * step
        if direction * (angle - target) > 0:
            angle = target
        servo.set_pan(angle)
        time.sleep(wait)


# ---------------------------------------------------------------------------
# Range calibration
# ---------------------------------------------------------------------------

def calibrate_range(servo: ServoController) -> tuple[float, float]:
    """
    Sweep slowly to both configured PWM extremes and return (left, right).

    The servo is commanded all the way to config.PAN_MIN_ANGLE (left) and
    config.PAN_MAX_ANGLE (right).  If the servo's mechanical end-stop is
    reached before those angles, it will stall silently – the controller has
    no way to detect this.  Either way, the extreme commanded angle is used
    as the range limit.
    """
    print()
    print("  ─── Calibration sweep ──────────────────────────────────")
    print("  No position feedback available – limits are inferred from")
    print("  the configured PWM extremes.  Listen for grinding noises.")
    print("  ────────────────────────────────────────────────────────")

    current = float(config.PAN_HOME_ANGLE)

    # ── Left limit ────────────────────────────────────────────────────────
    print(f"\n  Sweeping LEFT  ({current:.0f}° → {config.PAN_MIN_ANGLE}°) …", end="", flush=True)
    _sweep_to(servo, current, config.PAN_MIN_ANGLE)
    time.sleep(_CAL_SETTLE)
    left_limit = float(config.PAN_MIN_ANGLE)
    print(f"  held.  Left  limit = {left_limit:.1f}°")

    # ── Right limit ───────────────────────────────────────────────────────
    print(f"\n  Sweeping RIGHT ({left_limit:.0f}° → {config.PAN_MAX_ANGLE}°) …", end="", flush=True)
    _sweep_to(servo, left_limit, config.PAN_MAX_ANGLE)
    time.sleep(_CAL_SETTLE)
    right_limit = float(config.PAN_MAX_ANGLE)
    print(f"  held.  Right limit = {right_limit:.1f}°")

    centre = (left_limit + right_limit) / 2.0
    half   = (right_limit - left_limit) / 2.0

    print()
    print(f"  Range    : {left_limit:.1f}°  ←  {centre:.1f}°  →  {right_limit:.1f}°  (±{half:.1f}° each side)")
    print(f"  Config   : PAN_HOME_ANGLE = {config.PAN_HOME_ANGLE}°")

    offset = abs(centre - config.PAN_HOME_ANGLE)
    if offset > 2.0:
        print(f"  ⚠  Discovered centre differs from config by {offset:.1f}°.")
        print(f"     Tests will use the discovered centre ({centre:.1f}°).")
    else:
        print(f"  ✓  Discovered centre matches config within {offset:.1f}°.")

    return left_limit, right_limit


# ---------------------------------------------------------------------------
# Main test sequence
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 58)
    print("  youmirror – pan servo calibration + test")
    print(f"  Channel      : {config.PAN_CHANNEL}")
    print(f"  PWM range    : {config.PAN_MIN_ANGLE}° – {config.PAN_MAX_ANGLE}°")
    print(f"  Config home  : {config.PAN_HOME_ANGLE}°")
    print("=" * 58)
    input("\n  Press Enter to start (Ctrl-C to abort at any time)…")

    servo = ServoController()

    centre: Optional[float] = None

    try:
        # ── Move to config home before sweeping ───────────────────────────
        _prompt(f"Moving to config HOME ({config.PAN_HOME_ANGLE}°) before calibration")
        servo.set_pan(config.PAN_HOME_ANGLE)
        time.sleep(1.0)

        # ── Phase 1: discover range ───────────────────────────────────────
        left_limit, right_limit = calibrate_range(servo)
        centre    = (left_limit + right_limit) / 2.0
        half_range = (right_limit - left_limit) / 2.0

        _prompt(f"Moving to discovered CENTRE ({centre:.1f}°)")
        servo.set_pan(centre)
        time.sleep(1.2)

        # ── Phase 2: pan tests relative to discovered centre ──────────────
        print()
        print("─" * 58)
        print(f"  Pan tests  (centre = {centre:.1f}°,  range = ±{half_range:.1f}°)")
        print("─" * 58)

        _prompt("RIGHT +20° nudge")
        _move(servo, centre + 20, left_limit, right_limit)

        _prompt(f"CENTRE ({centre:.1f}°)")
        _move(servo, centre, left_limit, right_limit)

        _prompt("LEFT –20° nudge")
        _move(servo, centre - 20, left_limit, right_limit)

        _prompt(f"CENTRE ({centre:.1f}°)")
        _move(servo, centre, left_limit, right_limit)

        _prompt("RIGHT +60°")
        _move(servo, centre + 60, left_limit, right_limit)

        _prompt(f"CENTRE ({centre:.1f}°)")
        _move(servo, centre, left_limit, right_limit)

        _prompt("LEFT –60°")
        _move(servo, centre - 60, left_limit, right_limit)

        _prompt(f"CENTRE ({centre:.1f}°)")
        _move(servo, centre, left_limit, right_limit)

        _prompt("RIGHT +100° (near mechanical stop)")
        _move(servo, centre + 100, left_limit, right_limit)

        _prompt(f"CENTRE ({centre:.1f}°)")
        _move(servo, centre, left_limit, right_limit)

        _prompt("LEFT –100° (near mechanical stop)")
        _move(servo, centre - 100, left_limit, right_limit)

        _prompt(f"CENTRE ({centre:.1f}°)")
        _move(servo, centre, left_limit, right_limit)

        _prompt("SLOW SWEEP: centre → left limit → right limit → centre")
        _sweep_to(servo, centre,      left_limit,  step=1.0, wait=0.06)
        _sweep_to(servo, left_limit,  right_limit, step=1.0, wait=0.03)
        _sweep_to(servo, right_limit, centre,      step=1.0, wait=0.06)

        print(f"\n  ✓  All tests done.  Servo is at centre ({centre:.1f}°).\n")

    except KeyboardInterrupt:
        print("\n  Aborted by user.")

    finally:
        # Hold centre pulse for _HOME_HOLD seconds so the servo physically
        # reaches and stays at centre before the signal is cut.
        # (Zeroing PWM immediately after set_pan was the cause of the servo
        # not appearing to return home in the previous version.)
        park = centre if centre is not None else float(config.PAN_HOME_ANGLE)
        print(f"  Holding CENTRE ({park:.1f}°) for {_HOME_HOLD:.0f} s before releasing…")
        servo.set_pan(park)
        time.sleep(_HOME_HOLD)
        servo.shutdown()
        print("  Done.")


if __name__ == "__main__":
    main()
