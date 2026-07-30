"""
Videogame-style manual drive for both servos.

Hold a key to move; release it to stop (uses keyboard auto-repeat, so the
axis stops ~0.25 s after the last repeat arrives):

    a / d          pan  left / right   (channel 0)
    w / s          tilt up   / down    (channel 1)
    arrow keys     same as the above
    space          stop both axes immediately
    q / Esc        quit

Both axes are treated as continuous-rotation servos and BOTH use the pan
calibration from config.py (PAN_MOVE_LEFT_US / PAN_MOVE_RIGHT_US /
PAN_DRIVE_OFFSET_US) until the tilt axis gets its own calibration.

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

# If tilt runs the wrong way, flip this instead of relearning the keys.
_TILT_INVERT = False


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
# Velocity drive (pan calibration applied to both channels)
# ---------------------------------------------------------------------------

def _drive_pulse(direction: int) -> float:
    if direction < 0:
        return config.PAN_MOVE_LEFT_US - config.PAN_DRIVE_OFFSET_US
    if direction > 0:
        return config.PAN_MOVE_RIGHT_US + config.PAN_DRIVE_OFFSET_US
    return (config.PAN_MOVE_LEFT_US + config.PAN_MOVE_RIGHT_US) / 2.0


class _Axis:
    """One continuous-rotation axis: commanded direction + release timeout."""

    def __init__(self, servo: ServoController, channel: int, invert: bool = False) -> None:
        self.servo = servo
        self.channel = channel
        self.invert = invert
        self.direction = 0
        self._deadline = 0.0

    def press(self, direction: int) -> None:
        """A movement key (or auto-repeat) arrived for this axis."""
        if self.invert:
            direction = -direction
        self._deadline = time.monotonic() + _HOLD_TIMEOUT_S
        self._apply(direction)

    def tick(self) -> None:
        """Stop if the key has been released (no repeat within the timeout)."""
        if self.direction and time.monotonic() >= self._deadline:
            self._apply(0)

    def stop(self) -> None:
        self._apply(0)

    def _apply(self, direction: int) -> None:
        if direction == self.direction:
            return
        self.servo.set_pulse_us(self.channel, _drive_pulse(direction))
        self.direction = direction


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 58)
    print("  youmirror - videogame servo drive")
    print("=" * 58)
    print("  hold a/d = pan left/right    hold w/s = tilt up/down")
    print("  arrows work too    space = stop    q or Esc = quit")
    print()

    servo = ServoController()
    pan = _Axis(servo, config.PAN_CHANNEL)
    tilt = _Axis(servo, config.TILT_CHANNEL, invert=_TILT_INVERT)

    # Energise both channels at the stop pulse before driving.
    servo.set_pulse_us(config.PAN_CHANNEL, _drive_pulse(0))
    servo.set_pulse_us(config.TILT_CHANNEL, _drive_pulse(0))
    time.sleep(0.3)

    _raw_on()
    try:
        while True:
            key = _read_key(timeout=0.03)

            if key == "a":
                pan.press(-1)
            elif key == "d":
                pan.press(+1)
            elif key == "s":
                tilt.press(-1)
            elif key == "w":
                tilt.press(+1)
            elif key == " ":
                pan.stop()
                tilt.stop()
            elif key in ("q", "\x1b"):
                break

            pan.tick()
            tilt.tick()

            pan_arrow = {0: "  .  ", -1: "<<-- ", +1: " -->>"}[pan.direction]
            tilt_arrow = {0: "  .  ", -1: " vv  ", +1: " ^^  "}[tilt.direction]
            sys.stdout.write(f"\r  pan [{pan_arrow}]   tilt [{tilt_arrow}]   ")
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
