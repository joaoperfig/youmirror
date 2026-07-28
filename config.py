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

# ---------------------------------------------------------------------------
# Pan axis (channel 0) — CONTINUOUS-ROTATION servo, velocity controlled
# ---------------------------------------------------------------------------
# The pan servo is a continuous-rotation unit: the pulse commands SPEED and
# DIRECTION, not position (measured on the rig):
#   pulse <= PAN_MOVE_LEFT_US   → rotates toward the left wall
#   pulse >= PAN_MOVE_RIGHT_US  → rotates toward the right wall
#   anywhere in between         → stopped
#
# There is no position feedback.  The camera closes the tracking loop
# (rotate toward the face, stop when centred); position is only *estimated*
# by dead reckoning (commanded direction × measured speed × time) so the rig
# can avoid forcing itself against its mechanical stops.
#
# IMPORTANT: the estimate's zero is wherever the rig points at startup —
# start the system with the mirror physically centred.  The estimate drifts
# over time; the soft-limit margin below absorbs that.
#
# Calibrate all of this with `python3 test_servo_pan.py`.
PAN_MOVE_LEFT_US  = 1500   # highest pulse that still rotates left
PAN_MOVE_RIGHT_US = 1616   # lowest pulse that rotates right

# Extra pulse beyond the movement threshold while driving.  0 = slowest
# creep; larger = faster.  Speeds below must be measured at this offset.
PAN_DRIVE_OFFSET_US = 50

# Measured rotation speed at the drive pulses (degrees per second).
# These WILL differ per direction — measure both with test_servo_pan.py.
PAN_SPEED_LEFT_DPS  = 200.0
PAN_SPEED_RIGHT_DPS = 200.0

# Rig geometry: measured wall-to-wall travel, and how far the *estimated*
# position may stray from centre before the software refuses to drive
# further in that direction.  Margin is generous because dead reckoning
# drifts.
PAN_TRAVEL_DEG     = 2236
PAN_SOFT_LIMIT_DEG = PAN_TRAVEL_DEG // 2 - 200   # ±918° from centre

# Flip if the mirror runs away from the face instead of toward it.
PAN_INVERT = False

# "Home" for the pan axis is estimated position 0 (the startup centre).
# Stop seeking once the estimate is within this tolerance.
PAN_HOME_TOLERANCE_DEG = 25

# ---------------------------------------------------------------------------
# Tilt axis (channel 1) — standard positional hobby servo
# ---------------------------------------------------------------------------
# Mapped across SERVO_PULSE_MIN_US–SERVO_PULSE_MAX_US.
TILT_SERVO_RANGE = 180
TILT_MIN_ANGLE   =  60
TILT_MAX_ANGLE   = 120
TILT_HOME_ANGLE  =  90  # update after physical calibration

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

# Tilt is positional: proportional gain in degrees of tilt per pixel of
# face-centre error.  Increase if sluggish, decrease if it oscillates.
KP_TILT = 0.05

# Pan is velocity controlled (continuous-rotation servo): it simply rotates
# toward the face whenever the horizontal error exceeds DEAD_BAND_PX and
# stops inside it, so there is no pan gain to tune — only the drive speed
# (PAN_DRIVE_OFFSET_US above).

# Dead-band: ignore face-center errors smaller than this many pixels.
# Prevents the mirror from constantly hunting when the face is nearly centred.
DEAD_BAND_PX = 10
