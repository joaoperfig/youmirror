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
        self._pan_angle  = float(config.PAN_HOME_ANGLE)
        self._tilt_angle = float(config.TILT_HOME_ANGLE)
        self._running = False

        log.info("Initialising servo controller…")
        self._servos = ServoController()
        self._servos.home()

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

                    # Pan: face right of centre → increase pan angle (turn right)
                    self._pan_angle = self._update_axis(
                        self._pan_angle,
                        error_x,
                        config.KP_PAN,
                        config.PAN_MIN_ANGLE,
                        config.PAN_MAX_ANGLE,
                        invert=False,
                    )

                    # Tilt: face below centre → decrease tilt angle (look down)
                    self._tilt_angle = self._update_axis(
                        self._tilt_angle,
                        error_y,
                        config.KP_TILT,
                        config.TILT_MIN_ANGLE,
                        config.TILT_MAX_ANGLE,
                        invert=True,   # positive error → look down → smaller angle
                    )

                    self._servos.set_pan(self._pan_angle)
                    self._servos.set_tilt(self._tilt_angle)

                else:
                    consecutive_misses += 1
                    if consecutive_misses >= max_misses_before_home:
                        self._return_home()
                        consecutive_misses = 0  # only log/move once per absence

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

    def _return_home(self) -> None:
        log.info("No face detected – returning to home position.")
        self._pan_angle  = float(config.PAN_HOME_ANGLE)
        self._tilt_angle = float(config.TILT_HOME_ANGLE)
        # Ramp the pan axis: on the multi-turn servo a direct jump home from a
        # far tracking position would run at full speed.
        self._servos.ramp_pan(self._pan_angle)
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
