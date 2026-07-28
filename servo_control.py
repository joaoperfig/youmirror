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
        # Last commanded pulse per channel (µs) — the controller has no
        # feedback, so this is the only notion of "current position" we have.
        self._last_pulse_us: dict[int, float] = {}
        # Pan dead-reckoning state (continuous-rotation servo): commanded
        # direction, when it was last changed/integrated, and the estimated
        # position in degrees relative to the startup orientation.
        self._pan_dir: int = 0
        self._pan_last_t: float = time.monotonic()
        self._pan_est_deg: float = 0.0
        self._init_pca9685()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_pulse_us(self, channel: int, pulse_us: float) -> float:
        """
        Command a raw pulse width on *channel*.

        Returns the pulse actually set after PCA9685 count quantisation
        (~4.9 µs granularity at 50 Hz).
        """
        count = self._pulse_us_to_count(pulse_us)
        self._set_pwm(channel, 0, count)
        actual = count * (1_000_000 / self._pwm_freq) / config.PCA9685_RESOLUTION
        self._last_pulse_us[channel] = actual
        return actual

    def ramp_pulse_us(
        self,
        channel: int,
        target_us: float,
        wait_s: float = 0.04,
    ) -> float:
        """
        Move to *target_us* one PCA9685 count at a time.

        A hobby servo runs at full speed toward any distant setpoint, so
        every large move must be ramped.  One count is ~4.9 µs; with the
        default wait this is a calm, steady crawl.  Falls back to a direct
        set if no previous pulse is known (first command after power-up).
        """
        current = self._last_pulse_us.get(channel)
        if current is None:
            return self.set_pulse_us(channel, target_us)

        step = (1_000_000 / self._pwm_freq) / config.PCA9685_RESOLUTION
        direction = 1.0 if target_us > current else -1.0
        while direction * (target_us - current) > step / 2:
            current += direction * step
            if direction * (current - target_us) > 0:
                current = target_us
            self.set_pulse_us(channel, current)
            time.sleep(wait_s)
        return self.set_pulse_us(channel, target_us)

    def set_angle(self, channel: int, angle: float, servo_range: float = 180.0) -> None:
        """
        Move servo on *channel* to *angle* (used by the tilt axis).

        *servo_range* is the servo's full physical rotation in degrees.
        The pulse width is scaled linearly across SERVO_PULSE_MIN_US –
        SERVO_PULSE_MAX_US to cover the full *servo_range*.
        """
        angle = max(0.0, min(servo_range, angle))
        self.set_pulse_us(channel, self._angle_to_pulse(angle, servo_range))

    # -- Pan axis: continuous-rotation servo (velocity + dead reckoning) --
    #
    # The pan servo has no positions: pulses at/below PAN_MOVE_LEFT_US rotate
    # left, at/above PAN_MOVE_RIGHT_US rotate right, and pulses in between
    # stop it.  Position is estimated by integrating commanded direction ×
    # measured speed × time.  Zero = wherever the rig pointed at startup, so
    # start with the mirror physically centred.  Call pan_drive()/pan_stop()
    # regularly (every tracking frame) so soft limits are enforced promptly.

    def pan_stop(self) -> None:
        """Stop pan rotation (centre of the dead band)."""
        self._pan_apply(0)

    def pan_home(self) -> None:
        """
        Anchor the position estimate by wall-referenced homing (blocking).

        Drives left long enough to guarantee reaching the left wall from any
        starting position (ending in a brief, gentle stall against the stop),
        then drives right for half the travel time — that point is the
        physical centre, and the estimate is zeroed there.  Bypasses the
        soft limits, which are meaningless until this has run.
        """
        left_s = config.PAN_TRAVEL_DEG / config.PAN_SPEED_LEFT_DPS + config.PAN_HOME_EXTRA_S
        right_s = (config.PAN_TRAVEL_DEG / 2.0) / config.PAN_SPEED_RIGHT_DPS

        self._pan_apply(-1)
        time.sleep(left_s)
        self._pan_apply(0)
        time.sleep(0.3)          # let the mechanics settle off the wall
        self._pan_apply(+1)
        time.sleep(right_s)
        self._pan_apply(0)
        self.pan_reset_estimate(0.0)

    def pan_drive(self, direction: int) -> None:
        """
        Rotate the pan axis: -1 = toward left wall, +1 = toward right wall,
        0 = stop.  Refuses to drive past the estimated soft limit and stops
        instead.
        """
        direction = int(direction)
        if direction != 0:
            direction = 1 if direction > 0 else -1
            if self._pan_limit_blocks(direction):
                direction = 0
        self._pan_apply(direction)

    def pan_position_deg(self) -> float:
        """Dead-reckoned pan position in degrees from the startup centre."""
        self._pan_integrate()
        return self._pan_est_deg

    def pan_reset_estimate(self, deg: float = 0.0) -> None:
        """Re-zero the estimate (e.g. after physically re-centring the rig)."""
        self._pan_integrate()
        self._pan_est_deg = deg

    def _pan_integrate(self) -> None:
        now = time.monotonic()
        dt = now - self._pan_last_t
        self._pan_last_t = now
        if self._pan_dir < 0:
            self._pan_est_deg -= config.PAN_SPEED_LEFT_DPS * dt
        elif self._pan_dir > 0:
            self._pan_est_deg += config.PAN_SPEED_RIGHT_DPS * dt

    def _pan_limit_blocks(self, direction: int) -> bool:
        self._pan_integrate()
        if direction > 0:
            return self._pan_est_deg >= config.PAN_SOFT_LIMIT_DEG
        return self._pan_est_deg <= -config.PAN_SOFT_LIMIT_DEG

    def _pan_apply(self, direction: int) -> None:
        self._pan_integrate()
        if direction == self._pan_dir:
            return
        if direction < 0:
            pulse = config.PAN_MOVE_LEFT_US - config.PAN_DRIVE_OFFSET_US
        elif direction > 0:
            pulse = config.PAN_MOVE_RIGHT_US + config.PAN_DRIVE_OFFSET_US
        else:
            pulse = (config.PAN_MOVE_LEFT_US + config.PAN_MOVE_RIGHT_US) / 2.0
        self.set_pulse_us(config.PAN_CHANNEL, pulse)
        self._pan_dir = direction

    def set_tilt(self, angle: float) -> None:
        """Set tilt angle in degrees (0–180, centre = 90)."""
        angle = max(config.TILT_MIN_ANGLE, min(config.TILT_MAX_ANGLE, angle))
        self.set_angle(config.TILT_CHANNEL, angle, servo_range=config.TILT_SERVO_RANGE)

    def home(self) -> None:
        """
        Stop pan rotation and centre the tilt axis.

        Pan cannot be homed positionally (no feedback); the tracking loop
        seeks estimated position 0 instead (see main.py).
        """
        self.pan_stop()
        self.set_tilt(config.TILT_HOME_ANGLE)

    def shutdown(self) -> None:
        """Stop the pan servo, release all channels, and close I2C."""
        self.pan_stop()          # settle the dead-reckoning state
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
    # Quick sanity wiggle: short velocity pulses each way, then stop.
    # Full calibration (dead band, speeds) lives in test_servo_pan.py.
    print("Pan velocity test: 0.5 s left, 0.5 s right, stop.")
    controller = ServoController()
    try:
        controller.set_tilt(config.TILT_HOME_ANGLE)
        controller.pan_drive(-1)
        time.sleep(0.5)
        controller.pan_stop()
        time.sleep(0.5)
        controller.pan_drive(+1)
        time.sleep(0.5)
        controller.pan_stop()
        print(f"Estimated pan position: {controller.pan_position_deg():+.0f} deg "
              "(should be ~0 if speeds are calibrated symmetrically)")
    finally:
        controller.shutdown()
