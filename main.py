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
Both servos are continuous-rotation units, so control is by velocity, not
angle.  Every frame, the face-centre error vector (pixels) is converted to
a direction and speed per axis:

    |error| <= DEAD_BAND_PX          →  axis stopped
    |error| >= FULL_SPEED_ERROR_PX   →  full speed toward the face
    in between                       →  speed ramps linearly

The camera closes the loop: as the face approaches the frame centre the
error shrinks, the servo slows, and it stops inside the dead band.  Both
axes are re-commanded on every loop iteration for dynamic continuous
tracking.  No position is tracked (range limits are ignored for now).

Usage
-----
    python main.py            # run normally
    python main.py --debug    # print face-error values each frame
"""

import argparse
import logging
import signal
import sys

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
        self._running = False

        log.info("Initialising servo controller…")
        self._servos = ServoController()
        self._servos.stop_all()

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

        try:
            while self._running:
                frame = self._camera.capture_frame()
                face  = self._camera.detect_face(frame)

                if face is not None:
                    error_x = face.cx - self._frame_cx   # + = face is right of centre
                    error_y = face.cy - self._frame_cy   # + = face is below centre

                    if self._debug:
                        log.debug(
                            "Face @ (%3d, %3d)  error x=%+4d  y=%+4d",
                            face.cx, face.cy, error_x, error_y,
                        )

                    # Desired direction vector → per-axis direction + speed,
                    # re-commanded every frame.
                    # Pan: positive error (face right of centre) → drive right.
                    self._drive_axis("pan", error_x, invert=config.PAN_INVERT)
                    # Tilt: positive error (face below centre) → drive down,
                    # so the base sense is inverted.
                    self._drive_axis("tilt", error_y, invert=not config.TILT_INVERT)

                else:
                    # No face: stop immediately, don't keep sweeping on
                    # stale information.
                    self._servos.stop_all()

        except KeyboardInterrupt:
            log.info("Interrupted by user.")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._running = False
        log.info("Shutting down…")
        self._servos.shutdown()
        self._camera.release()
        log.info("Shutdown complete.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _drive_axis(self, axis: str, error_px: int, invert: bool) -> None:
        """
        Convert one component of the error vector into a velocity command.

        Inside the dead band the axis stops.  Outside it, speed ramps
        linearly from the axis's minimum drive offset (at the dead-band
        edge) to its maximum (at FULL_SPEED_ERROR_PX and beyond).
        """
        magnitude = abs(error_px)
        if magnitude <= config.DEAD_BAND_PX:
            self._servos.stop(axis)
            return

        ramp_span = config.FULL_SPEED_ERROR_PX - config.DEAD_BAND_PX
        throttle = min(1.0, (magnitude - config.DEAD_BAND_PX) / ramp_span)

        direction = 1 if error_px > 0 else -1
        if invert:
            direction = -direction

        self._servos.drive(axis, direction, throttle)


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
