"""
Hardware configuration and tuning parameters for youmirror.

All physical constants, pin assignments, and tunable values live here so
nothing is scattered across modules.

Both servos are CONTINUOUS-ROTATION units: the pulse commands SPEED and
DIRECTION, not position.  Per axis, the calibrated dead band gives the
pulse edges where movement starts, and the min/max drive offsets give the
usable speed range beyond those edges:

    pulse = negative_edge - offset   ->  drive negative (left / down)
    pulse = positive_edge + offset   ->  drive positive (right / up)
    pulse between the edges          ->  stopped

    offset = OFFSET_MIN_US .. OFFSET_MAX_US   (slowest .. fastest)
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
# Pan axis (channel 0) — continuous rotation, velocity controlled
# ---------------------------------------------------------------------------
# Dead-band edges measured on the rig with `python3 test_servo_pan.py`:
#   pulse <= PAN_MOVE_LEFT_US   → rotates toward the left wall
#   pulse >= PAN_MOVE_RIGHT_US  → rotates toward the right wall
#   anywhere in between         → stopped
PAN_MOVE_LEFT_US  = 1498   # highest pulse that still rotates left
PAN_MOVE_RIGHT_US = 1616   # lowest pulse that rotates right

# Drive offset beyond the dead-band edge (us).  MIN = slowest usable speed,
# MAX = fastest; the tracking loop interpolates between them based on how
# far the face is from the frame centre.
PAN_OFFSET_MIN_US = 200
PAN_OFFSET_MAX_US = 450

# Flip if the mirror runs away from the face instead of toward it.
PAN_INVERT = False

# Reference values from calibration (used by test_servo_pan.py only; the
# tracking loop is closed by the camera and does not use position).
PAN_SPEED_LEFT_DPS  = 120.0
PAN_SPEED_RIGHT_DPS = 120.0
PAN_TRAVEL_DEG      = 236   # measured wall-to-wall travel

# ---------------------------------------------------------------------------
# Tilt axis (channel 1) — continuous rotation, velocity controlled
# ---------------------------------------------------------------------------
# Dead-band edges: assumed identical to the pan servo until the tilt axis
# gets its own calibration run.
#   pulse <= TILT_MOVE_DOWN_US  → rotates down
#   pulse >= TILT_MOVE_UP_US    → rotates up
TILT_MOVE_DOWN_US = 1498
TILT_MOVE_UP_US   = 1616

# Drive offset range beyond the dead-band edge (us), as for pan.
TILT_OFFSET_MIN_US = 100
TILT_OFFSET_MAX_US = 250

# Flip if the mirror tilts away from the face instead of toward it.
TILT_INVERT = False

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

# Downscale factor applied to the frame before running detection.
# 2 = detect on 160×120 instead of 320×240 (~4× faster). Coordinates are
# scaled back to full-frame pixels afterwards, so callers see no difference.
# Trade-off: the Haar window is 24 px, so the smallest detectable face is
# 24 × DETECTION_DOWNSCALE px in full-frame terms (48 px at downscale 2).
# Set to 1 to detect at full resolution (much slower on the Pi Zero W).
DETECTION_DOWNSCALE = 2

# Scale factor for the image pyramid in detectMultiScale.
# Larger = fewer pyramid levels = faster, but coarser size coverage.
# 1.1 was measured at ~1.4 s/frame on the Pi Zero W; 1.2 roughly halves it.
FACE_SCALE_FACTOR = 1.2

# Minimum neighbours a rectangle must have to be retained.
# Lower = more sensitive (keeps detections when the face is slightly turned)
# but also more prone to false positives.
FACE_MIN_NEIGHBOURS = 3

# Minimum face size in pixels (filters out noise on a 320×240 frame)
FACE_MIN_SIZE = (40, 40)

# ---------------------------------------------------------------------------
# Tracking controller (velocity, proportional to pixel error)
# ---------------------------------------------------------------------------
# Every frame, the face-centre error vector (pixels) is converted to a
# direction and speed per axis:
#
#   |error| <= DEAD_BAND_PX          → axis stopped
#   |error| >= FULL_SPEED_ERROR_PX   → drive at OFFSET_MAX_US (full speed)
#   in between                       → linear ramp OFFSET_MIN..OFFSET_MAX
#
# The camera closes the loop: the servo slows as the face approaches the
# centre and stops inside the dead band.

# Dead-band: ignore face-centre errors smaller than this many pixels.
# Prevents the mirror from constantly hunting when the face is nearly centred.
DEAD_BAND_PX = 10

# Pixel error at which an axis reaches full speed (OFFSET_MAX_US).
FULL_SPEED_ERROR_PX = 100
