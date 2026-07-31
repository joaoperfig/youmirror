"""
Videogame-style manual drive for both servos.

Hold a key to move; release it to stop (uses keyboard auto-repeat, so the
axis stops ~0.25 s after the last repeat arrives):

    a / d          pan  left / right   (channel 0)
    w / s          tilt up   / down    (channel 1)
    arrow keys     same as the above
    Shift+key      turbo (drives at the axis's OFFSET_MAX_US)
    space          stop both axes immediately
    q / Esc        quit

Both axes are continuous-rotation servos driven through the velocity API in
servo_control.py.  Normal speed uses the axis's OFFSET_MIN_US, turbo its
OFFSET_MAX_US (see config.py).

No soft limits are enforced here - watch the rig and let go near the stops.

Usage
-----
    python3 test_drive.py
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


# Seconds without a key repeat before an axis is considered released.
# Must be longer than the OS auto-repeat interval (typically ~0.03-0.1 s).
_HOLD_TIMEOUT_S = 0.25


# ---------------------------------------------------------------------------
# Raw keyboard input (same approach as test_servo_pan.py)
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


def _read_key(timeout: float) -> Optional[str]:
    """Single-key read; arrows map to w/a/s/d.  None if nothing arrives."""
    if _WINDOWS:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # extended key prefix
                    return {"H": "w", "P": "s", "K": "a", "M": "d"}.get(
                        msvcrt.getwch(), ""
                    )
                return ch
            time.sleep(0.005)
        return None

    if not select.select([sys.stdin], [], [], timeout)[0]:
        return None
    ch = sys.stdin.read(1)
    if ch == "\x1b":
        # Arrows arrive as ESC [ A/B/C/D; a bare Esc press has no follow-up.
        if select.select([sys.stdin], [], [], 0.01)[0]:
            if sys.stdin.read(1) == "[" and select.select([sys.stdin], [], [], 0.01)[0]:
                return {"A": "w", "B": "s", "C": "d", "D": "a"}.get(
                    sys.stdin.read(1), ""
                )
        return "\x1b"
    return ch


# ---------------------------------------------------------------------------
# Axis hold state
# ---------------------------------------------------------------------------

class _Axis:
    """One axis: commanded direction/turbo tier + key-release timeout."""

    def __init__(self, servo: ServoController, name: str, invert: bool = False) -> None:
        self.servo = servo
        self.name = name
        self.invert = invert
        self.direction = 0
        self.turbo = False
        self._deadline = 0.0

    def press(self, direction: int, turbo: bool = False) -> None:
        """A movement key (or auto-repeat) arrived for this axis."""
        if self.invert:
            direction = -direction
        self._deadline = time.monotonic() + _HOLD_TIMEOUT_S
        self._apply(direction, turbo)

    def tick(self) -> None:
        """Stop if the key has been released (no repeat within the timeout)."""
        if self.direction and time.monotonic() >= self._deadline:
            self._apply(0, False)

    def stop(self) -> None:
        self._apply(0, False)

    def _apply(self, direction: int, turbo: bool) -> None:
        if direction == self.direction and turbo == self.turbo:
            return
        self.servo.drive(self.name, direction, throttle=1.0 if turbo else 0.0)
        self.direction = direction
        self.turbo = turbo


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 58)
    print("  youmirror - videogame servo drive")
    print("=" * 58)
    print("  hold a/d = pan left/right    hold w/s = tilt up/down")
    print("  hold Shift for turbo    arrows work too")
    print("  space = stop    q or Esc = quit")
    print()

    servo = ServoController()
    pan = _Axis(servo, "pan", invert=config.PAN_INVERT)
    tilt = _Axis(servo, "tilt", invert=config.TILT_INVERT)

    # Energise both channels at their stop pulse before driving.
    servo.stop_all()
    time.sleep(0.3)

    _raw_on()
    try:
        while True:
            key = _read_key(timeout=0.03)

            if key and key in "aAdDsSwW":
                turbo = key.isupper()  # Shift+letter arrives as uppercase
                low = key.lower()
                if low == "a":
                    pan.press(-1, turbo)
                elif low == "d":
                    pan.press(+1, turbo)
                elif low == "s":
                    tilt.press(-1, turbo)
                elif low == "w":
                    tilt.press(+1, turbo)
            elif key == " ":
                pan.stop()
                tilt.stop()
            elif key in ("q", "\x1b"):
                break

            pan.tick()
            tilt.tick()

            pan_arrow = {0: "  .  ", -1: "<<-- ", +1: " -->>"}[pan.direction]
            tilt_arrow = {0: "  .  ", -1: " vv  ", +1: " ^^  "}[tilt.direction]
            pan_tag = "TURBO" if pan.turbo else "     "
            tilt_tag = "TURBO" if tilt.turbo else "     "
            sys.stdout.write(
                f"\r  pan [{pan_arrow}] {pan_tag}   tilt [{tilt_arrow}] {tilt_tag}   "
            )
            sys.stdout.flush()

    except KeyboardInterrupt:
        pass

    finally:
        pan.stop()
        tilt.stop()
        _raw_off()
        servo.shutdown()
        print("\n  PWM released (servos stop without a pulse).  Done.")


if __name__ == "__main__":
    main()
