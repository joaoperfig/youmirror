"""
Servo controller for the Waveshare Servo Driver HAT (PCA9685).

The HAT communicates over I2C using the PCA9685 PWM chip.  Both rig servos
are CONTINUOUS-ROTATION units, so this module exposes a velocity-oriented
interface: each axis is driven with a direction (-1 / 0 / +1) and a
throttle (0..1) that interpolates between the axis's calibrated minimum
and maximum drive offsets.  There is no position feedback; the camera
closes the tracking loop.

Wiring reminder
---------------
  Pi GPIO 2 (SDA) → HAT SDA
  Pi GPIO 3 (SCL) → HAT SCL
  HAT powered via 5 V GPIO pins (or external VIN 6-12 V for high-torque servos)
  Pan  servo  → Channel 0 (yellow = PWM, red = 5 V, brown/black = GND)
  Tilt servo  → Channel 1
"""

import time
from dataclasses import dataclass

import smbus2

import config


# ---------------------------------------------------------------------------
# PCA9685 register map (subset used here)
# ---------------------------------------------------------------------------
_MODE1       = 0x00
_MODE2       = 0x01
_PRESCALE    = 0xFE
_LED0_ON_L   = 0x06   # base register; each channel occupies 4 bytes


@dataclass(frozen=True)
class _Axis:
    """Calibration of one continuous-rotation axis."""
    channel: int
    neg_edge_us: float    # highest pulse that still drives negative (left/down)
    pos_edge_us: float    # lowest pulse that drives positive (right/up)
    offset_min_us: float  # slowest usable drive offset beyond an edge
    offset_max_us: float  # fastest drive offset

    def pulse(self, direction: int, throttle: float) -> float:
        if direction == 0:
            return (self.neg_edge_us + self.pos_edge_us) / 2.0
        throttle = max(0.0, min(1.0, throttle))
        offset = self.offset_min_us + throttle * (self.offset_max_us - self.offset_min_us)
        if direction < 0:
            return self.neg_edge_us - offset
        return self.pos_edge_us + offset


_AXES = {
    "pan": _Axis(
        channel=config.PAN_CHANNEL,
        neg_edge_us=config.PAN_MOVE_LEFT_US,
        pos_edge_us=config.PAN_MOVE_RIGHT_US,
        offset_min_us=config.PAN_OFFSET_MIN_US,
        offset_max_us=config.PAN_OFFSET_MAX_US,
    ),
    "tilt": _Axis(
        channel=config.TILT_CHANNEL,
        neg_edge_us=config.TILT_MOVE_DOWN_US,
        pos_edge_us=config.TILT_MOVE_UP_US,
        offset_min_us=config.TILT_OFFSET_MIN_US,
        offset_max_us=config.TILT_OFFSET_MAX_US,
    ),
}


class ServoController:
    """Velocity control for the two continuous-rotation servos on the HAT."""

    def __init__(
        self,
        i2c_address: int = config.PCA9685_I2C_ADDRESS,
        bus: int = config.I2C_BUS,
        pwm_freq: int = config.SERVO_PWM_FREQ,
    ) -> None:
        self._bus = smbus2.SMBus(bus)
        self._address = i2c_address
        self._pwm_freq = pwm_freq
        # Last commanded PCA9685 count per channel, to skip redundant I2C
        # writes when the tracking loop re-commands the same speed each frame.
        self._last_count: dict[int, int] = {}
        self._init_pca9685()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def drive(self, axis: str, direction: int, throttle: float = 0.0) -> None:
        """
        Drive *axis* ("pan" or "tilt") at a given direction and speed.

        direction : -1 (left/down), 0 (stop), +1 (right/up)
        throttle  : 0..1 — interpolates the drive offset between the axis's
                    calibrated OFFSET_MIN_US (slowest) and OFFSET_MAX_US
                    (fastest).  Ignored when direction is 0.
        """
        cal = _AXES[axis]
        direction = 0 if direction == 0 else (1 if direction > 0 else -1)
        self.set_pulse_us(cal.channel, cal.pulse(direction, throttle))

    def stop(self, axis: str) -> None:
        """Stop one axis (centre of its dead band)."""
        self.drive(axis, 0)

    def stop_all(self) -> None:
        """Stop both axes."""
        for axis in _AXES:
            self.stop(axis)

    def set_pulse_us(self, channel: int, pulse_us: float) -> float:
        """
        Command a raw pulse width on *channel*.

        Returns the pulse actually set after PCA9685 count quantisation
        (~4.9 µs granularity at 50 Hz).  Skips the I2C write if the channel
        is already at that count.
        """
        count = self._pulse_us_to_count(pulse_us)
        if self._last_count.get(channel) != count:
            self._set_pwm(channel, 0, count)
            self._last_count[channel] = count
        return count * (1_000_000 / self._pwm_freq) / config.PCA9685_RESOLUTION

    def shutdown(self) -> None:
        """Stop both servos, release all channels, and close I2C."""
        self.stop_all()
        for ch in range(16):
            self._set_pwm(ch, 0, 0)
        self._bus.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_pca9685(self) -> None:
        """Reset the chip, then configure PWM frequency."""
        self._write(_MODE1, 0x00)          # normal mode, internal oscillator
        self._set_pwm_freq(self._pwm_freq)
        time.sleep(0.05)

    def _set_pwm_freq(self, freq_hz: int) -> None:
        """
        Set the PWM frequency.

        PCA9685 internal oscillator is 25 MHz.
        prescale = round(25_000_000 / (4096 * freq)) - 1
        """
        prescale = round(25_000_000 / (config.PCA9685_RESOLUTION * freq_hz)) - 1
        prescale = max(3, min(255, prescale))   # datasheet limits

        old_mode = self._read(_MODE1)
        sleep_mode = (old_mode & 0x7F) | 0x10  # set SLEEP bit
        self._write(_MODE1, sleep_mode)
        self._write(_PRESCALE, prescale)
        self._write(_MODE1, old_mode)
        time.sleep(0.005)
        self._write(_MODE1, old_mode | 0xA0)    # restart + auto-increment

    def _set_pwm(self, channel: int, on: int, off: int) -> None:
        """Write ON/OFF tick counts directly to a channel's registers."""
        base = _LED0_ON_L + 4 * channel
        self._bus.write_i2c_block_data(
            self._address,
            base,
            [on & 0xFF, on >> 8, off & 0xFF, off >> 8],
        )

    def _pulse_us_to_count(self, pulse_us: float) -> int:
        """Convert a pulse width (µs) to a PCA9685 12-bit tick count."""
        period_us = 1_000_000 / self._pwm_freq
        return round(config.PCA9685_RESOLUTION * pulse_us / period_us)

    def _write(self, register: int, value: int) -> None:
        self._bus.write_byte_data(self._address, register, value)

    def _read(self, register: int) -> int:
        return self._bus.read_byte_data(self._address, register)


# ---------------------------------------------------------------------------
# Quick standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Sanity wiggle: each axis drives 0.5 s each way at minimum speed.
    # Full pan calibration (dead band, speeds) lives in test_servo_pan.py.
    print("Velocity test: pan left/right, tilt down/up, 0.5 s each at min speed.")
    controller = ServoController()
    try:
        for axis in ("pan", "tilt"):
            for direction in (-1, +1):
                controller.drive(axis, direction, throttle=0.0)
                time.sleep(0.5)
                controller.stop(axis)
                time.sleep(0.3)
        print("Done.")
    finally:
        controller.shutdown()
