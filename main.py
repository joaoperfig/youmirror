"""
youmirror – main tracking loop.

Physical setup
--------------
The Pi Camera is rigidly mounted behind the mirror, centred on it and looking
through it at the user. Camera and mirror move as a single unit on the
pan/tilt rig. This means:

  - When a face is centred in the camera frame, the mirror is correctly aimed.
  - The error signal is already in the mirror's own reference frame — no
    coordinate transformation is needed.
  - Corrections are always relative ("a bit more left", "a bit more up") rather
    than absolute angle commands.

Control strategy
----------------
A simple proportional controller is used for each axis:

    error_px  = face_centre_px - frame_centre_px   (pixels)
    Δangle    = Kp * error_px                      (degrees)
    new_angle = current_angle + Δangle

A dead-band prevents constant hunting when the face is nearly centred.
Extend to PID by adding integral and derivative terms in _update_axis().

Usage
-----
    python main.py            # run normally
    python main.py --debug    # print face-error values each frame
"""

import argparse
import logging
import signal
import sys
import time

import config
from camera import CameraController
from servo_control import ServoController


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


class MirrorTracker:
    """Ties the camera and servo controller together into a tracking loop."""

    def __init__(self, debug: bool = False) -> None:
        self._debug = debug
        self._tilt_angle = float(config.TILT_HOME_ANGLE)
        self._running = False

        log.info("Initialising servo controller…")
        self._servos = ServoController()

        homing_s = (
            config.PAN_TRAVEL_DEG / config.PAN_SPEED_LEFT_DPS
            + config.PAN_HOME_EXTRA_S
            + config.PAN_TRAVEL_DEG / 2.0 / config.PAN_SPEED_RIGHT_DPS
        )
        log.info(
            "Homing pan: touching the left wall, then centring (~%.1f s)…",
            homing_s,
        )
        self._servos.pan_home()
        self._servos.home()
        log.info("Pan homed — estimated position zeroed at centre.")

        log.info("Initialising camera…")
        self._camera = CameraController()

        self._frame_cx, self._frame_cy = self._camera.get_frame_center()
        log.info(
            "Frame centre: (%d, %d)  –  tracking started.",
            self._frame_cx, self._frame_cy,
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True
        consecutive_misses = 0
        max_misses_before_home = 30  # ~1–2 s at ~20 fps before returning home

        try:
            while self._running:
                frame = self._camera.capture_frame()
                face  = self._camera.detect_face(frame)

                if face is not None:
                    consecutive_misses = 0
                    error_x = face.cx - self._frame_cx   # + = face is right of centre
                    error_y = face.cy - self._frame_cy   # + = face is below centre

                    if self._debug:
                        log.debug(
                            "Face @ (%3d, %3d)  error x=%+4d  y=%+4d",
                            face.cx, face.cy, error_x, error_y,
                        )

                    # Pan (continuous-rotation servo): rotate toward the face,
                    # stop once it is inside the dead band.  The camera closes
                    # this loop, so no position is needed — the controller's
                    # dead-reckoned soft limits keep us off the walls.
                    if abs(error_x) <= config.DEAD_BAND_PX:
                        self._servos.pan_stop()
                    else:
                        direction = 1 if error_x > 0 else -1
                        if config.PAN_INVERT:
                            direction = -direction
                        self._servos.pan_drive(direction)

                    # Tilt (positional servo): proportional control as before.
                    self._tilt_angle = self._update_axis(
                        self._tilt_angle,
                        error_y,
                        config.KP_TILT,
                        config.TILT_MIN_ANGLE,
                        config.TILT_MAX_ANGLE,
                        invert=True,   # positive error → look down → smaller angle
                    )
                    self._servos.set_tilt(self._tilt_angle)

                else:
                    consecutive_misses += 1
                    if consecutive_misses < max_misses_before_home:
                        # Face just lost: stop rotating immediately, don't
                        # keep sweeping on stale information.
                        self._servos.pan_stop()
                    else:
                        if consecutive_misses == max_misses_before_home:
                            log.info("No face detected – seeking estimated centre.")
                        self._seek_home()

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._running = False
        log.info("Shutting down…")
        self._servos.home()
        time.sleep(0.3)
        self._servos.shutdown()
        self._camera.release()
        log.info("Shutdown complete.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_axis(
        self,
        current_angle: float,
        error_px: int,
        kp: float,
        min_angle: float,
        max_angle: float,
        invert: bool,
    ) -> float:
        """Apply proportional control with dead-band and angle clamping."""
        if abs(error_px) <= config.DEAD_BAND_PX:
            return current_angle

        delta = kp * error_px
        if invert:
            delta = -delta

        new_angle = current_angle + delta
        return max(min_angle, min(max_angle, new_angle))

    def _seek_home(self) -> None:
        """
        One per-frame step toward the startup centre (estimated position 0).

        Called repeatedly while no face is visible; the frame rate provides
        the pacing.  Dead reckoning is coarse, so we stop within a tolerance
        rather than hunting for an exact zero.
        """
        estimate = self._servos.pan_position_deg()
        if abs(estimate) <= config.PAN_HOME_TOLERANCE_DEG:
            self._servos.pan_stop()
        else:
            self._servos.pan_drive(-1 if estimate > 0 else +1)

        self._tilt_angle = float(config.TILT_HOME_ANGLE)
        self._servos.set_tilt(self._tilt_angle)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="youmirror face-tracking mirror")
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable verbose face-error logging",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    tracker = MirrorTracker(debug=args.debug)

    # Ensure clean shutdown on SIGTERM (e.g. systemd stop)
    def _sigterm_handler(sig, frame):
        log.info("Received SIGTERM.")
        tracker.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)

    tracker.run()


if __name__ == "__main__":
    main()
