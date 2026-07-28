"""
Continuous-rotation pan servo calibration (channel 0).

The pan servo is a continuous-rotation unit: the pulse commands SPEED and
DIRECTION, not position.  Measured behaviour on this rig:

    pulse <= ~1500 us  -> rotates left
    pulse >= ~1616 us  -> rotates right
    in between         -> stopped

The tracking loop does not need position (the camera closes that loop), but
to avoid forcing the rig against its mechanical stops we dead-reckon the
position: estimated degrees = commanded direction x measured speed x time.
This tool measures everything that model needs:

    Phase 1 - dead band : find the exact pulse where rotation starts, each way
    Phase 2 - speeds    : timed drive runs; you report degrees rotated
    Phase 3 - free drive: videogame-style driving with the live estimate and
                          soft limits active, to sanity-check the numbers

At the end it prints the config.py lines to paste.

Controls are single keypresses (no Enter) unless a prompt asks you to type.

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


_COUNT_US = (1_000_000 / config.SERVO_PWM_FREQ) / config.PCA9685_RESOLUTION
_PULSE_FLOOR_US = 400.0
_PULSE_CEIL_US = 2600.0
_MAX_TIMED_RUN_S = 5.0


# ---------------------------------------------------------------------------
# Raw keyboard input
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


def _read_key(timeout: Optional[float] = None) -> Optional[str]:
    """
    Single-key read; arrows map to 'a' / 'd'.

    With *timeout* set, returns None if no key arrives in time (lets loops
    keep integrating the position estimate while idle).
    """
    if _WINDOWS:
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):  # extended key prefix
                    return {"K": "a", "M": "d"}.get(msvcrt.getwch(), "")
                return ch
            time.sleep(0.01)
        return None

    if timeout is not None and not select.select([sys.stdin], [], [], timeout)[0]:
        return None
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


def _parse_degrees(raw: str) -> Optional[float]:
    """Accept '540', '1.5t' or '1.5 turns' (turns are converted to degrees)."""
    raw = raw.strip().lower().replace("turns", "t").replace("turn", "t").rstrip()
    try:
        if raw.endswith("t"):
            return float(raw[:-1].strip()) * 360.0
        return float(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Calibration state
# ---------------------------------------------------------------------------

class _Cal:
    def __init__(self) -> None:
        self.move_left_us = float(config.PAN_MOVE_LEFT_US)
        self.move_right_us = float(config.PAN_MOVE_RIGHT_US)
        self.drive_offset_us = float(config.PAN_DRIVE_OFFSET_US)
        self.speed_left_dps = float(config.PAN_SPEED_LEFT_DPS)
        self.speed_right_dps = float(config.PAN_SPEED_RIGHT_DPS)
        self.travel_deg = float(config.PAN_TRAVEL_DEG)

    def stop_pulse(self) -> float:
        return (self.move_left_us + self.move_right_us) / 2.0

    def drive_pulse(self, direction: int) -> float:
        if direction < 0:
            return self.move_left_us - self.drive_offset_us
        return self.move_right_us + self.drive_offset_us

    def speed(self, direction: int) -> float:
        return self.speed_left_dps if direction < 0 else self.speed_right_dps


class _Drive:
    """Owns the commanded direction and the dead-reckoned estimate."""

    def __init__(self, servo: ServoController, cal: _Cal) -> None:
        self.servo = servo
        self.cal = cal
        self.direction = 0
        self.est_deg = 0.0
        self._last_t = time.monotonic()

    def integrate(self) -> None:
        now = time.monotonic()
        dt = now - self._last_t
        self._last_t = now
        if self.direction:
            self.est_deg += self.direction * self.cal.speed(self.direction) * dt

    def set(self, direction: int) -> None:
        self.integrate()
        if direction == self.direction:
            return
        pulse = self.cal.stop_pulse() if direction == 0 else self.cal.drive_pulse(direction)
        self.servo.set_pulse_us(config.PAN_CHANNEL, pulse)
        self.direction = direction

    def stop(self) -> None:
        self.set(0)


# ---------------------------------------------------------------------------
# Phase 1: dead-band edges
# ---------------------------------------------------------------------------

def _confirm_stopped(servo: ServoController, pulse: float) -> float:
    print(f"\n  Energised at {pulse:.0f} us.  The servo should be STOPPED.")
    print("  If it creeps, nudge with a/d (one count) until it stops, then Enter.")
    _raw_on()
    try:
        while True:
            key = _read_key()
            if key in ("\r", "\n"):
                return pulse
            if key in ("a", "d"):
                pulse += -_COUNT_US if key == "a" else _COUNT_US
                pulse = servo.set_pulse_us(config.PAN_CHANNEL, pulse)
                sys.stdout.write(f"\r  pulse {pulse:6.0f} us   ")
                sys.stdout.flush()
    finally:
        _raw_off()


def _find_edge(servo: ServoController, stop_pulse: float, direction: int) -> float:
    name = "LEFT" if direction < 0 else "RIGHT"
    print(f"\n  --- {name} movement threshold ---")
    print("  SPACE steps the pulse one count away from stop; 'b' steps back.")
    print("  The moment the rig starts to creep, press Enter to record it.")
    pulse = servo.set_pulse_us(config.PAN_CHANNEL, stop_pulse)
    _raw_on()
    try:
        while True:
            key = _read_key()
            if key == " ":
                pulse = servo.set_pulse_us(config.PAN_CHANNEL, pulse + direction * _COUNT_US)
            elif key == "b":
                pulse = servo.set_pulse_us(config.PAN_CHANNEL, pulse - direction * _COUNT_US)
            elif key in ("\r", "\n"):
                break
            else:
                continue
            sys.stdout.write(f"\r  pulse {pulse:6.0f} us   ")
            sys.stdout.flush()
    finally:
        _raw_off()
    print(f"\n  {name} threshold recorded at {pulse:.0f} us.")
    servo.set_pulse_us(config.PAN_CHANNEL, stop_pulse)
    return pulse


# ---------------------------------------------------------------------------
# Phase 2: speed measurement
# ---------------------------------------------------------------------------

def _reposition(drive: _Drive, message: str) -> None:
    print(f"\n  {message}")
    print("  Drive with a (left) / d (right) / space (stop); Enter when ready.")
    _raw_on()
    try:
        while True:
            key = _read_key(timeout=0.1)
            drive.integrate()
            if key == "a":
                drive.set(-1)
            elif key == "d":
                drive.set(+1)
            elif key in (" ", "s"):
                drive.stop()
            elif key in ("\r", "\n"):
                drive.stop()
                return
    finally:
        drive.stop()
        _raw_off()


def _measure_speed(drive: _Drive, direction: int) -> float:
    name = "LEFT" if direction < 0 else "RIGHT"
    other = "right" if direction < 0 else "left"
    _reposition(
        drive,
        f"Speed run {name}: position the rig near the {other} wall so there is "
        "room to rotate,\n  and put a piece of tape on the rig as a reference mark.",
    )

    while True:
        raw = _line_input(f"  Drive duration in seconds [2.0, max {_MAX_TIMED_RUN_S:.0f}]: ").strip()
        try:
            duration = float(raw) if raw else 2.0
        except ValueError:
            duration = 2.0
        duration = max(0.2, min(_MAX_TIMED_RUN_S, duration))

        input(f"  Press Enter to drive {name} for {duration:.1f} s...")
        drive.servo.set_pulse_us(config.PAN_CHANNEL, drive.cal.drive_pulse(direction))
        time.sleep(duration)
        drive.servo.set_pulse_us(config.PAN_CHANNEL, drive.cal.stop_pulse())

        while True:
            raw = _line_input("  How far did it rotate? (degrees, or e.g. '1.5t' for turns): ")
            degrees = _parse_degrees(raw)
            if degrees is not None:
                break
            print("  Could not parse that - enter e.g. 540 or 1.5t")

        dps = degrees / duration
        print(f"  -> {name} speed = {dps:.0f} deg/s")
        again = _line_input("  Accept? (Enter = yes, r = redo): ").strip().lower()
        if again != "r":
            # The estimate integrated during the run used the old speed; the
            # timed run itself is not position-tracked, so just re-zero later.
            return dps


# ---------------------------------------------------------------------------
# Phase 3: free drive with the estimate live
# ---------------------------------------------------------------------------

def _free_drive(drive: _Drive) -> None:
    soft = drive.cal.travel_deg / 2.0 - 200.0
    print("\n  --- Free drive (estimate + soft limits live) ---")
    print("  First drive to the PHYSICAL CENTRE and press z to zero the estimate.")
    print("  a = left   d = right   space/s = stop   z = zero estimate   Enter = finish")
    drive.est_deg = 0.0
    _raw_on()
    try:
        while True:
            key = _read_key(timeout=0.1)
            drive.integrate()

            # Soft limits: refuse to continue outward past the margin.
            if drive.direction and abs(drive.est_deg) >= soft and (
                (drive.direction > 0) == (drive.est_deg > 0)
            ):
                drive.stop()
                note = "SOFT LIMIT - stopped"
            else:
                note = ""

            arrow = {0: " stop", -1: "<<--", +1: "-->>"}[drive.direction]
            turns = drive.est_deg / 360.0
            sys.stdout.write(
                f"\r  [{arrow}]  est {drive.est_deg:+7.0f} deg ({turns:+5.2f} turns)"
                f"   limit +-{soft:.0f} deg   {note}".ljust(78)
            )
            sys.stdout.flush()

            if key == "a":
                drive.set(-1)
            elif key == "d":
                drive.set(+1)
            elif key in (" ", "s"):
                drive.stop()
            elif key == "z":
                drive.integrate()
                drive.est_deg = 0.0
            elif key in ("\r", "\n", "q"):
                drive.stop()
                print()
                return
    finally:
        drive.stop()
        _raw_off()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _print_config(cal: _Cal) -> None:
    print()
    print("  --- Paste into config.py -------------------------------")
    print(f"  PAN_MOVE_LEFT_US  = {cal.move_left_us:.0f}")
    print(f"  PAN_MOVE_RIGHT_US = {cal.move_right_us:.0f}")
    print(f"  PAN_DRIVE_OFFSET_US = {cal.drive_offset_us:.0f}")
    print(f"  PAN_SPEED_LEFT_DPS  = {cal.speed_left_dps:.0f}")
    print(f"  PAN_SPEED_RIGHT_DPS = {cal.speed_right_dps:.0f}")
    print(f"  PAN_TRAVEL_DEG     = {cal.travel_deg:.0f}")
    print("  --------------------------------------------------------")
    print("  Reminder: start main.py with the mirror physically centred -")
    print("  the position estimate is zeroed at startup.")


def main() -> None:
    print("=" * 58)
    print("  youmirror - continuous-rotation pan calibration")
    print("=" * 58)
    print(__doc__.split("Usage")[0])

    cal = _Cal()
    servo = ServoController()

    try:
        raw = input(
            f"  Measure the dead band? Current config: moves left <= "
            f"{cal.move_left_us:.0f} us,\n  right >= {cal.move_right_us:.0f} us. "
            "(Enter = keep, m = measure): "
        ).strip().lower()

        stop = servo.set_pulse_us(config.PAN_CHANNEL, cal.stop_pulse())
        time.sleep(0.3)

        if raw == "m":
            stop = _confirm_stopped(servo, stop)
            cal.move_left_us = _find_edge(servo, stop, -1)
            cal.move_right_us = _find_edge(servo, stop, +1)

        raw = input(
            f"\n  Drive offset beyond the threshold in us [{cal.drive_offset_us:.0f}] "
            "(0 = slowest creep): "
        ).strip()
        if raw:
            try:
                cal.drive_offset_us = abs(float(raw))
            except ValueError:
                pass

        drive = _Drive(servo, cal)

        print("\n  === Speed measurement ===")
        print("  Two timed runs; you report how far the rig rotated each time.")
        cal.speed_left_dps = abs(_measure_speed(drive, -1))
        cal.speed_right_dps = abs(_measure_speed(drive, +1))

        raw = input(
            f"\n  Wall-to-wall travel in degrees [{cal.travel_deg:.0f}]: "
        ).strip()
        if raw:
            parsed = _parse_degrees(raw)
            if parsed:
                cal.travel_deg = parsed

        _free_drive(drive)
        _print_config(cal)

    except KeyboardInterrupt:
        print("\n  Interrupted.")

    finally:
        _raw_off()
        servo.shutdown()
        print("  PWM released (servo stops without a pulse).  Done.")


if __name__ == "__main__":
    main()
