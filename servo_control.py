"""
Servo controller for the Waveshare Servo Driver HAT (PCA9685).

The HAT communicates over I2C using the PCA9685 PWM chip. This module
provides a thin, angle-oriented interface on top of the smbus2 register
writes so the rest of the codebase never has to think in pulse counts.

Wiring reminder
---------------
  Pi GPIO 2 (SDA) → HAT SDA
  Pi GPIO 3 (SCL) → HAT SCL
  HAT powered via 5 V GPIO pins (or external VIN 6-12 V for high-torque servos)
  Pan  servo  → Channel 0 (yellow = PWM, red = 5 V, brown/black = GND)
  Tilt servo  → Channel 1
"""

import time
import smbus2

import config


# ---------------------------------------------------------------------------
# PCA9685 register map (subset used here)
# ---------------------------------------------------------------------------
_MODE1       = 0x00
_MODE2       = 0x01
_PRESCALE    = 0xFE
_LED0_ON_L   = 0x06   # base register; each channel occupies 4 bytes


class ServoController:
    """Controls up to 16 hobby servos via the PCA9685 on the Servo Driver HAT."""

    def __init__(
        self,
        i2c_address: int = config.PCA9685_I2C_ADDRESS,
        bus: int = config.I2C_BUS,
        pwm_freq: int = config.SERVO_PWM_FREQ,
    ) -> None:
        self._bus = smbus2.SMBus(bus)
        self._address = i2c_address
        self._pwm_freq = pwm_freq
        self._init_pca9685()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_angle(self, channel: int, angle: float, servo_range: float = 180.0) -> None:
        """
        Move servo on *channel* to *angle*.

        *servo_range* is the servo's full physical rotation in degrees
        (e.g. 180 for a standard servo, 236 for the pan servo).
        The pulse width is scaled linearly across SERVO_PULSE_MIN_US –
        SERVO_PULSE_MAX_US to cover the full *servo_range*.
        """
        angle = max(0.0, min(servo_range, angle))
        pulse_us = self._angle_to_pulse(angle, servo_range)
        self._set_pwm(channel, 0, self._pulse_us_to_count(pulse_us))

    def set_pan(self, angle: float) -> None:
        """Set pan angle in degrees (0–236, centre = 118)."""
        angle = max(config.PAN_MIN_ANGLE, min(config.PAN_MAX_ANGLE, angle))
        self.set_angle(config.PAN_CHANNEL, angle, servo_range=config.PAN_SERVO_RANGE)

    def set_tilt(self, angle: float) -> None:
        """Set tilt angle in degrees (0–180, centre = 90)."""
        angle = max(config.TILT_MIN_ANGLE, min(config.TILT_MAX_ANGLE, angle))
        self.set_angle(config.TILT_CHANNEL, angle, servo_range=config.TILT_SERVO_RANGE)

    def home(self) -> None:
        """Return both axes to their neutral positions."""
        self.set_pan(config.PAN_HOME_ANGLE)
        self.set_tilt(config.TILT_HOME_ANGLE)

    def shutdown(self) -> None:
        """Release all channels (zero duty cycle) and close I2C."""
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

    def _angle_to_pulse(self, angle: float, servo_range: float) -> float:
        """Convert *angle* (0–*servo_range* degrees) to pulse width in µs."""
        span = config.SERVO_PULSE_MAX_US - config.SERVO_PULSE_MIN_US
        return config.SERVO_PULSE_MIN_US + span * (angle / servo_range)

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
    print(f"Servo test: sweeping pan axis 0° → {config.PAN_SERVO_RANGE}° → home ({config.PAN_HOME_ANGLE}°)")
    controller = ServoController()
    try:
        for angle in range(0, config.PAN_SERVO_RANGE + 1, 10):
            controller.set_pan(angle)
            time.sleep(0.05)
        for angle in range(config.PAN_SERVO_RANGE, -1, -10):
            controller.set_pan(angle)
            time.sleep(0.05)
        controller.home()
        print("Done. Servos at home position.")
    finally:
        controller.shutdown()
