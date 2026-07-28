"""
Hardware configuration and tuning parameters for youmirror.

All physical constants, pin assignments, and tunable values live here so
nothing is scattered across modules.
"""

# ---------------------------------------------------------------------------
# PCA9685 / Servo Driver HAT
# ---------------------------------------------------------------------------

# Default I2C address when all A0-A4 pads are open (unsoldered)
PCA9685_I2C_ADDRESS = 0x40

# PCA9685 I2C bus number on Pi Zero W (GPIO 2/3 = bus 1)
I2C_BUS = 1

# PWM frequency for standard hobby servos (Hz)
SERVO_PWM_FREQ = 50  # 20 ms period

# Pulse widths in microseconds for the servos in use.
# Adjust these if a servo doesn't reach true 0° / 180° or overshoots.
SERVO_PULSE_MIN_US = 500   # ~0°
SERVO_PULSE_MAX_US = 2500  # ~180°

# PCA9685 resolution: 12-bit → 4096 counts over one PWM period
PCA9685_RESOLUTION = 4096

# ---------------------------------------------------------------------------
# Servo channel assignments on the Servo Driver HAT
# ---------------------------------------------------------------------------
# Channel 0 = pan  (horizontal / left-right)
# Channel 1 = tilt (vertical   / up-down)
PAN_CHANNEL  = 0
TILT_CHANNEL = 1

# Physical rotation range of each servo (degrees, full travel 0 → max).
# This is the servo's true mechanical range, NOT the PWM angle convention.
# The pulse-width mapping always spans SERVO_PULSE_MIN_US–SERVO_PULSE_MAX_US
# across this range, so angles are expressed in the servo's own units.
#
# Pan  servo (channel 0): 236° total travel (118° each direction from centre)
# Tilt servo (channel 1): 180° total travel (standard hobby servo)
PAN_SERVO_RANGE  = 236
TILT_SERVO_RANGE = 180

# Safe software limits for each axis (same units as the servo range above).
# Clamp movements to these bounds to protect the mirror mechanics.
PAN_MIN_ANGLE  =   0    # hard left  (0° end of the 236° range)
PAN_MAX_ANGLE  = 236    # hard right (236° end of the 236° range)
TILT_MIN_ANGLE =  60
TILT_MAX_ANGLE = 120

# Neutral / home position when no face is detected (degrees).
#
# Pan centre is at 118° (midpoint of 0–236°).
# Tilt centre is at 90° (midpoint of 0–180°) — update after calibration.
#
# The camera-behind-mirror design means that when a face is centred in the
# camera frame the mirror is correctly aimed — so the home position is just
# where you want the mirror to park when no face is visible.
PAN_HOME_ANGLE  = 118  # midpoint of 0–236°; update after physical calibration
TILT_HOME_ANGLE =  90  # update after physical calibration

# ---------------------------------------------------------------------------
# Pi Camera Module Rev 1.3 (OV5647, 5 MP)
# ---------------------------------------------------------------------------

# Capture resolution used during face tracking.
# Lower = faster processing on the Pi Zero W (single-core 1 GHz).
CAMERA_WIDTH  = 320
CAMERA_HEIGHT = 240
CAMERA_FRAMERATE = 24

# Camera rotation in degrees (0 / 90 / 180 / 270).
# Set to 180 if the ribbon connector is on the wrong side.
CAMERA_ROTATION = 0

# ---------------------------------------------------------------------------
# Face detection (OpenCV Haar cascade)
# ---------------------------------------------------------------------------

# Scale factor for the image pyramid in detectMultiScale
FACE_SCALE_FACTOR = 1.1

# Minimum neighbours a rectangle must have to be retained
FACE_MIN_NEIGHBOURS = 5

# Minimum face size in pixels (filters out noise on a 320×240 frame)
FACE_MIN_SIZE = (60, 60)

# ---------------------------------------------------------------------------
# Tracking controller (proportional gain)
# ---------------------------------------------------------------------------

# How aggressively the servos chase the face error.
# Increase if tracking feels sluggish, decrease if it oscillates.
# Units: degrees of servo movement per pixel of face-center error.
KP_PAN  = 0.05
KP_TILT = 0.05

# Dead-band: ignore face-center errors smaller than this many pixels.
# Prevents the mirror from constantly hunting when the face is nearly centred.
DEAD_BAND_PX = 10
