"""
Interactive pan-servo calibration (channel 0).

Why the old script failed
-------------------------
config.py used to assume the pan servo covers 236 deg across the 500-2500 us
pulse range, like a standard hobby servo.  The real unit is multi-turn
(~1118 deg each side of centre, ~2236 deg wall to wall), so every commanded
"degree" moved ~9.5 real degrees, "nudges" were huge full-speed swings, and
sweeping to the configured pulse extremes drove the rig straight into its
mechanical stops.  On top of that, the old "calibration" never measured
anything - it just recorded the configured extremes back as the limits.

The PCA9685 has no position feedback, so the only safe calibration is a
human jogging the servo in raw pulse-width and marking the walls by eye.

Procedure
---------
1. The servo is energised at the midpoint of the currently configured pulse
   endpoints.  It may move there at full speed - keep hands clear.
2. Jog with `a` / `d` until the rig *just* touches each wall; mark the walls
   with `l` and `r`.  Use small steps near the walls (`s` changes the step).
3. `c` parks midway between the marks.  If the true physical centre is
   elsewhere, jog to it and mark it with `m`.
4. `v` runs a gentle ramped verification wiggle around the centre.
5. `done` prints the exact lines to paste into config.py and parks.

All motion is ramped one PCA9685 count at a time (~4.9 us ~ 5.5 deg of pan), so
nothing ever slams.  If the servo KEEPS ROTATING while the pulse is held
constant, it is a continuous-rotation servo and no pulse mapping can position
it - abort and rethink the hardware.

Usage
-----
    python3 test_servo_pan.py
"""

import time
from typing import Optional

import config
from servo_control import ServoController


# Absolute safety window for commanded pulses (us).  Most servos accept
# 500-2500; this only guards against typos in `g`, not against the walls.
_PULSE_FLOOR_US = 400.0
_PULSE_CEIL_US = 2600.0

_DEFAULT_STEP_US = 10.0   # ~11 deg of pan at the nominal calibration
_RAMP_WAIT_S = 0.04       # per PCA9685 count while ramping

_HELP = """\
  a [us]   jog toward lower pulse by one step (or an explicit us amount)
  d [us]   jog toward higher pulse by one step (or an explicit us amount)
  s us     set the default jog step
  g us     ramp to an absolute pulse width
  l        mark current pulse as the LEFT wall
  r        mark current pulse as the RIGHT wall
  m        mark current pulse as the physical CENTRE
  c        ramp to the centre (marked centre, else midpoint of the walls)
  v        gentle verification wiggle around the centre (needs both walls)
  p        print status
  done     print config.py values and park at centre
  q        abort (PWM released wherever the servo is)
"""


class _Session:
    def __init__(self, servo: ServoController) -> None:
        self.servo = servo
        self.pulse: float = 0.0
        self.step: float = _DEFAULT_STEP_US
        self.left: Optional[float] = None
        self.right: Optional[float] = None
        self.centre_mark: Optional[float] = None

    # -- geometry helpers ------------------------------------------------

    def span_us(self) -> Optional[float]:
        if self.left is None or self.right is None:
            return None
        return abs(self.right - self.left)

    def deg_per_us(self) -> float:
        """Physical degrees per us, from marked walls if available."""
        span = self.span_us()
        if not span:
            span = abs(config.PAN_PULSE_RIGHT_US - config.PAN_PULSE_LEFT_US)
        return config.PAN_TRAVEL_DEG / span

    def centre_pulse(self) -> Optional[float]:
        if self.centre_mark is not None:
            return self.centre_mark
        if self.left is not None and self.right is not None:
            return (self.left + self.right) / 2.0
        return None

    # -- motion ----------------------------------------------------------

    def goto(self, target_us: float) -> None:
        target_us = max(_PULSE_FLOOR_US, min(_PULSE_CEIL_US, target_us))
        self.pulse = self.servo.ramp_pulse_us(
            config.PAN_CHANNEL, target_us, wait_s=_RAMP_WAIT_S
        )

    # -- display ---------------------------------------------------------

    def print_status(self) -> None:
        dpu = self.deg_per_us()
        count_us = (1_000_000 / config.SERVO_PWM_FREQ) / config.PCA9685_RESOLUTION

        def fmt(mark: Optional[float]) -> str:
            return f"{mark:.0f} us" if mark is not None else "not marked"

        print(f"     pulse now : {self.pulse:.0f} us")
        print(f"     jog step  : {self.step:.0f} us  (~{self.step * dpu:.0f} deg of pan)")
        print(f"     left wall : {fmt(self.left)}    right wall: {fmt(self.right)}")
        centre = self.centre_pulse()
        source = "marked" if self.centre_mark is not None else "midpoint of walls"
        print(f"     centre    : {fmt(centre)}" + (f"  ({source})" if centre is not None else ""))
        print(f"     resolution: {count_us:.1f} us/count ~ {count_us * dpu:.1f} deg/count")


def _verify(session: _Session) -> None:
    """Gentle ramped nudges around the centre, well inside the walls."""
    centre = session.centre_pulse()
    span = session.span_us()
    if centre is None or span is None:
        print("     Mark both walls first (l and r).")
        return

    dpu = session.deg_per_us()
    half = span / 2.0
    print("     Verification wiggle (all moves ramped):")
    for fraction in (0.10, 0.30):
        offset = half * fraction
        for direction, name in ((+1, "right"), (-1, "left")):
            target = centre + direction * offset
            print(
                f"       {name:>5} {offset:.0f} us (~{offset * dpu:.0f} deg) ... ",
                end="", flush=True,
            )
            session.goto(target)
            time.sleep(0.6)
            print("back to centre")
            session.goto(centre)
            time.sleep(0.6)
    print("     Done - the rig should be at its physical centre now.")


def _finish(session: _Session) -> bool:
    """Print config values and park at centre.  Returns True on success."""
    if session.left is None or session.right is None:
        print("     Mark both walls first (l and r).")
        return False

    raw = input(
        f"     Measured wall-to-wall travel in degrees "
        f"[{config.PAN_TRAVEL_DEG}]: "
    ).strip()
    travel = float(raw) if raw else float(config.PAN_TRAVEL_DEG)

    span = session.right - session.left
    centre = session.centre_pulse()
    home_deg = (centre - session.left) / span * travel

    # Soft-limit margin: ~10 PCA9685 counts clear of each wall.
    count_us = (1_000_000 / config.SERVO_PWM_FREQ) / config.PCA9685_RESOLUTION
    margin_deg = round(10 * count_us * travel / abs(span))

    print()
    print("  --- Paste into config.py -------------------------------")
    print(f"  PAN_PULSE_LEFT_US  = {session.left:.0f}")
    print(f"  PAN_PULSE_RIGHT_US = {session.right:.0f}")
    print(f"  PAN_TRAVEL_DEG     = {travel:.0f}")
    print(f"  PAN_MIN_ANGLE = {margin_deg}")
    print(f"  PAN_MAX_ANGLE = PAN_TRAVEL_DEG - {margin_deg}")
    print(f"  PAN_HOME_ANGLE = {home_deg:.0f}")
    print("  --------------------------------------------------------")
    print(f"  (resolution: ~{count_us * travel / abs(span):.1f} deg of pan per PCA9685 count)")
    print()

    print("     Parking at centre...")
    session.goto(centre)
    time.sleep(1.5)
    return True


def main() -> None:
    print("=" * 58)
    print("  youmirror - interactive pan calibration (channel 0)")
    print("=" * 58)
    print(_HELP)
    print("  The servo will be energised at the midpoint of the current")
    print("  config pulses and may move there at full speed.")
    input("\n  Press Enter to energise (Ctrl-C aborts at any time)...")

    servo = ServoController()
    session = _Session(servo)

    start = (config.PAN_PULSE_LEFT_US + config.PAN_PULSE_RIGHT_US) / 2.0
    session.pulse = servo.set_pulse_us(config.PAN_CHANNEL, start)
    time.sleep(1.0)
    session.print_status()

    try:
        while True:
            try:
                raw = input(f"\n  [{session.pulse:.0f} us] > ").strip().lower()
            except EOFError:
                break
            if not raw:
                continue
            parts = raw.split()
            cmd, args = parts[0], parts[1:]

            if cmd in ("a", "d"):
                try:
                    amount = float(args[0]) if args else session.step
                except ValueError:
                    print("     Usage: a [us]  /  d [us]")
                    continue
                sign = -1.0 if cmd == "a" else 1.0
                session.goto(session.pulse + sign * amount)
                dpu = session.deg_per_us()
                print(f"     -> {session.pulse:.0f} us  (moved ~{amount * dpu:.0f} deg)")

            elif cmd == "s":
                try:
                    session.step = abs(float(args[0]))
                    print(f"     step = {session.step:.0f} us")
                except (IndexError, ValueError):
                    print("     Usage: s us   e.g.  s 5")

            elif cmd == "g":
                try:
                    session.goto(float(args[0]))
                    print(f"     -> {session.pulse:.0f} us")
                except (IndexError, ValueError):
                    print("     Usage: g us   e.g.  g 1500")

            elif cmd == "l":
                session.left = session.pulse
                print(f"     LEFT wall marked at {session.left:.0f} us")

            elif cmd == "r":
                session.right = session.pulse
                print(f"     RIGHT wall marked at {session.right:.0f} us")

            elif cmd == "m":
                session.centre_mark = session.pulse
                print(f"     CENTRE marked at {session.centre_mark:.0f} us")

            elif cmd == "c":
                centre = session.centre_pulse()
                if centre is None:
                    print("     No centre yet - mark walls (l, r) or centre (m) first.")
                else:
                    session.goto(centre)
                    print(f"     -> centre ({session.pulse:.0f} us)")

            elif cmd == "v":
                _verify(session)

            elif cmd == "p":
                session.print_status()

            elif cmd == "done":
                if _finish(session):
                    break

            elif cmd == "q":
                print("     Aborting.")
                break

            else:
                print(_HELP)

    except KeyboardInterrupt:
        print("\n  Interrupted.")

    finally:
        servo.shutdown()
        print("  PWM released.  Done.")


if __name__ == "__main__":
    main()
