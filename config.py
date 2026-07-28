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
# Pan axis (channel 0) — multi-turn servo, pulse-calibrated
# ---------------------------------------------------------------------------
# The pan servo is a multi-turn unit: measured travel is roughly 1118° each
# side of centre (~2236° wall to wall), NOT the ~180–270° of a standard hobby
# servo.  Pan positions are therefore expressed in *rig degrees*
# (0 = left wall … PAN_TRAVEL_DEG = right wall) and mapped linearly onto the
# pulse widths measured at the mechanical stops.
#
# Run `python3 test_servo_pan.py` to jog the servo to each wall interactively
# and paste the values it prints here.  Until then these are nominal defaults.
#
# Resolution note: at 50 Hz the PCA9685 quantises pulses to ~4.9 µs steps,
# which over 2236° of travel is ~5.5° of pan per step.
PAN_PULSE_LEFT_US  = 500    # pulse measured at the LEFT wall
PAN_PULSE_RIGHT_US = 2500   # pulse measured at the RIGHT wall
PAN_TRAVEL_DEG     = 2236   # measured physical travel between the walls

# Soft limits: stay clear of the walls (rig degrees).
PAN_MIN_ANGLE = 60
PAN_MAX_ANGLE = PAN_TRAVEL_DEG - 60

# Tilt axis (channel 1): standard 180° hobby servo mapped across
# SERVO_PULSE_MIN_US–SERVO_PULSE_MAX_US.
TILT_SERVO_RANGE = 180
TILT_MIN_ANGLE   =  60
TILT_MAX_ANGLE   = 120

# Neutral / home position when no face is detected (degrees).
#
# Pan home should be the rig's *physical* centre — mark it during the
# interactive calibration (test_servo_pan.py) and update this value.
#
# The camera-behind-mirror design means that when a face is centred in the
# camera frame the mirror is correctly aimed — so the home position is just
# where you want the mirror to park when no face is visible.
PAN_HOME_ANGLE  = PAN_TRAVEL_DEG // 2  # update after physical calibration
TILT_HOME_ANGLE = 90                   # update after physical calibration

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
# Units: degrees of axis movement per pixel of face-center error.
#
# The camera sees ~54° across 320 px ≈ 0.17°/px, and the camera pans with the
# rig 1:1, so a gain of 0.17 would fully correct the error in one step.
# Pan uses real rig degrees (see pan calibration above), so its gain must be
# below that; start conservative and tune on the rig.
KP_PAN  = 0.12
KP_TILT = 0.05

# Dead-band: ignore face-center errors smaller than this many pixels.
# Prevents the mirror from constantly hunting when the face is nearly centred.
DEAD_BAND_PX = 10
