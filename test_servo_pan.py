"""
Interactive pan-servo calibration (channel 0) - live keyboard control.

Background
----------
The pan servo is multi-turn (~2236 deg wall to wall measured on the rig) and
the PCA9685 has no position feedback, so the only safe calibration is a human
jogging the servo in raw pulse-width and marking the walls by eye.

A PWM servo has no "stay where you are" command: the moment PWM starts it
drives at full speed to whatever position the start pulse encodes.  If that
position lies beyond a wall, the servo pins against the stop and stalls
(holding with a buzz).  If that happens, hold the opposite jog key until it
comes free - and do not leave it stalled for long.

Controls (single keypress, no Enter - hold a key to crawl)
----------------------------------------------------------
  a / d  (or arrows)  jog one PCA9685 count (~4.9 us ~ 5.5 deg of pan)
  A / D               coarse jog, five counts (~27 deg)
  l / r               mark current pulse as the LEFT / RIGHT wall
  m                   mark current pulse as the physical CENTRE
  c                   ramp to the centre (marked, else midpoint of walls)
  g                   type an absolute pulse width to ramp to
  v                   gentle verification wiggle around the centre
  p                   full status
  h                   help
  Enter               finish: print config.py values and park at centre
  q                   quit without finishing (PWM released where it is)

Procedure
---------
1. Enter a start pulse (or accept the default).  The servo moves there at
   full speed - keep hands clear.
2. Jog until the rig *just* touches each wall; mark with `l` and `r`.
3. `c` parks midway between the marks; jog to the true physical centre if it
   differs and mark it with `m`.
4. `v` to verify, then Enter to print the config.py lines and park.

Sanity check: if the servo KEEPS ROTATING while the pulse is held constant
(away from the walls), it is a continuous-rotation servo and no pulse
mapping can position it - abort and rethink the hardware.

Usage
-----
    python3 test_servo_pan.py
"""

import sys
import time
from typing import Optional

import config
from servo_control import ServoController

try:
    import termios
    import tty
    import select
    _WINDOWS = False
except ImportError:  # allows trying the tool off-rig on Windows
    import msvcrt
    _WINDOWS = True


# Absolute safety window for commanded pulses (us).  Most servos accept
# 500-2500; this only guards against typos in `g`, not against the walls.
_PULSE_FLOOR_US = 400.0
_PULSE_CEIL_US = 2600.0

_COUNT_US = (1_000_000 / config.SERVO_PWM_FREQ) / config.PCA9685_RESOLUTION
_FINE_STEP_US = _COUNT_US        # one PCA9685 count per keypress
_COARSE_STEP_US = 5 * _COUNT_US  # Shift+A / Shift+D
_RAMP_WAIT_S = 0.04              # per count during ramped moves (c, g, v)

_HELP = """\
  a / d  (or arrows)  jog one count (~5.5 deg of pan) - hold the key to crawl
  A / D               coarse jog, five counts (~27 deg)
  l / r               mark current pulse as the LEFT / RIGHT wall
  m                   mark current pulse as the physical CENTRE
  c                   ramp to the centre (marked centre, else wall midpoint)
  g                   type an absolute pulse width to ramp to
  v                   verification wiggle around the centre (needs both walls)
  p                   full status
  h                   this help
  Enter               finish: print config.py values and park at centre
  q                   quit without finishing
"""


# ---------------------------------------------------------------------------
# Raw keyboard input (single keypress, no Enter)
# ---------------------------------------------------------------------------

_saved_term = None


def _raw_on() -> None:
    global _saved_term
    if _WINDOWS:
        return
    fd = sys.stdin.fileno()
    _saved_term = termios.tcgetattr(fd)
    tty.setcbreak(fd)  # single-char reads; Ctrl-C still works


def _raw_off() -> None:
    global _saved_term
    if _WINDOWS or _saved_term is None:
        return
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _saved_term)
    _saved_term = None


def _read_key() -> str:
    """Blocking single-key read.  Arrow keys are mapped to 'a' / 'd'."""
    if _WINDOWS:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # extended key prefix
            return {"K": "a", "M": "d"}.get(msvcrt.getwch(), "")
        return ch
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # Arrows arrive as ESC [ C/D; a bare Esc press has no follow-up bytes.
        if select.select([sys.stdin], [], [], 0.01)[0]:
            if sys.stdin.read(1) == "[" and select.select([sys.stdin], [], [], 0.01)[0]:
                return {"D": "a", "C": "d"}.get(sys.stdin.read(1), "")
        return "\x1b"
    return ch


def _line_input(prompt: str) -> str:
    """Regular Enter-terminated input, temporarily leaving raw mode."""
    _raw_off()
    try:
        return input(prompt)
    finally:
        _raw_on()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

class _Session:
    def __init__(self, servo: ServoController) -> None:
        self.servo = servo
        self.pulse: float = 0.0
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

    def nudge(self, delta_us: float) -> None:
        """Immediate small move - used by the live jog keys."""
        target = max(_PULSE_FLOOR_US, min(_PULSE_CEIL_US, self.pulse + delta_us))
        self.pulse = self.servo.set_pulse_us(config.PAN_CHANNEL, target)

    def goto(self, target_us: float) -> None:
        """Ramped move for anything larger than a jog step."""
        target_us = max(_PULSE_FLOOR_US, min(_PULSE_CEIL_US, target_us))
        self.pulse = self.servo.ramp_pulse_us(
            config.PAN_CHANNEL, target_us, wait_s=_RAMP_WAIT_S
        )

    # -- display ---------------------------------------------------------

    def hud(self, note: str = "") -> None:
        """One-line live status, redrawn in place."""
        def fmt(mark: Optional[float]) -> str:
            return f"{mark:.0f}" if mark is not None else "---"

        line = (
            f"  pulse {self.pulse:6.0f} us   "
            f"L {fmt(self.left)}  R {fmt(self.right)}  C {fmt(self.centre_pulse())}"
        )
        if note:
            line += f"   {note}"
        sys.stdout.write("\r" + line.ljust(70))
        sys.stdout.flush()

    def print_status(self) -> None:
        dpu = self.deg_per_us()

        def fmt(mark: Optional[float]) -> str:
            return f"{mark:.0f} us" if mark is not None else "not marked"

        print(f"     pulse now : {self.pulse:.0f} us")
        print(f"     left wall : {fmt(self.left)}    right wall: {fmt(self.right)}")
        centre = self.centre_pulse()
        source = "marked" if self.centre_mark is not None else "midpoint of walls"
        print(f"     centre    : {fmt(centre)}" + (f"  ({source})" if centre is not None else ""))
        print(f"     jog steps : fine {_FINE_STEP_US:.1f} us (~{_FINE_STEP_US * dpu:.0f} deg)"
              f"   coarse {_COARSE_STEP_US:.1f} us (~{_COARSE_STEP_US * dpu:.0f} deg)")


# ---------------------------------------------------------------------------
# Verification + finish
# ---------------------------------------------------------------------------

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
            print(
                f"       {name:>5} {offset:.0f} us (~{offset * dpu:.0f} deg) ... ",
                end="", flush=True,
            )
            session.goto(centre + direction * offset)
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

    raw = _line_input(
        f"     Measured wall-to-wall travel in degrees [{config.PAN_TRAVEL_DEG}]: "
    ).strip()
    travel = float(raw) if raw else float(config.PAN_TRAVEL_DEG)

    span = session.right - session.left
    centre = session.centre_pulse()
    home_deg = (centre - session.left) / span * travel

    # Soft-limit margin: ~10 PCA9685 counts clear of each wall.
    margin_deg = round(10 * _COUNT_US * travel / abs(span))

    print()
    print("  --- Paste into config.py -------------------------------")
    print(f"  PAN_PULSE_LEFT_US  = {session.left:.0f}")
    print(f"  PAN_PULSE_RIGHT_US = {session.right:.0f}")
    print(f"  PAN_TRAVEL_DEG     = {travel:.0f}")
    print(f"  PAN_MIN_ANGLE = {margin_deg}")
    print(f"  PAN_MAX_ANGLE = PAN_TRAVEL_DEG - {margin_deg}")
    print(f"  PAN_HOME_ANGLE = {home_deg:.0f}")
    print("  --------------------------------------------------------")
    print(f"  (resolution: ~{_COUNT_US * travel / abs(span):.1f} deg of pan per PCA9685 count)")
    print()

    print("     Parking at centre...")
    session.goto(centre)
    time.sleep(1.5)
    return True


# ---------------------------------------------------------------------------
# Live control loop
# ---------------------------------------------------------------------------

def _live_loop(session: _Session) -> str:
    """Run the raw-keyboard loop.  Returns 'done' or 'quit'."""
    session.hud()
    _raw_on()
    try:
        while True:
            key = _read_key()

            if key in ("a", "d"):
                session.nudge(-_FINE_STEP_US if key == "a" else _FINE_STEP_US)
                session.hud()

            elif key in ("A", "D"):
                session.nudge(-_COARSE_STEP_US if key == "A" else _COARSE_STEP_US)
                session.hud()

            elif key == "l":
                session.left = session.pulse
                session.hud(note="LEFT wall marked")

            elif key == "r":
                session.right = session.pulse
                session.hud(note="RIGHT wall marked")

            elif key == "m":
                session.centre_mark = session.pulse
                session.hud(note="CENTRE marked")

            elif key == "c":
                centre = session.centre_pulse()
                if centre is None:
                    session.hud(note="no centre yet - mark walls or m")
                else:
                    session.goto(centre)
                    session.hud(note="at centre")

            elif key == "g":
                print()
                raw = _line_input("     Go to pulse (us): ").strip()
                try:
                    session.goto(float(raw))
                except ValueError:
                    print("     Not a number.")
                session.hud()

            elif key == "v":
                print()
                _verify(session)
                session.hud()

            elif key == "p":
                print()
                session.print_status()
                session.hud()

            elif key == "h":
                print()
                print(_HELP)
                session.hud()

            elif key in ("\r", "\n"):
                print()
                return "done"

            elif key == "q":
                print()
                return "quit"
    finally:
        _raw_off()


def main() -> None:
    print("=" * 58)
    print("  youmirror - interactive pan calibration (channel 0)")
    print("=" * 58)
    print(_HELP)
    print("  The servo has no feedback: it will move to the start pulse")
    print("  at FULL SPEED the moment PWM begins.  If it pins against a")
    print("  wall and buzzes, hold the opposite jog key until it comes")
    print("  free - do not leave it stalled for long.")

    default_start = (config.PAN_PULSE_LEFT_US + config.PAN_PULSE_RIGHT_US) / 2.0
    raw = input(f"\n  Start pulse in us [{default_start:.0f}]: ").strip()
    try:
        start = float(raw) if raw else default_start
    except ValueError:
        start = default_start
    start = max(_PULSE_FLOOR_US, min(_PULSE_CEIL_US, start))

    servo = ServoController()
    session = _Session(servo)

    try:
        session.pulse = servo.set_pulse_us(config.PAN_CHANNEL, start)
        time.sleep(0.5)

        while True:
            action = _live_loop(session)
            if action == "quit":
                print("  Quitting without finishing.")
                break
            if action == "done" and _finish(session):
                break

    except KeyboardInterrupt:
        print("\n  Interrupted.")

    finally:
        _raw_off()
        servo.shutdown()
        print("  PWM released.  Done.")


if __name__ == "__main__":
    main()
