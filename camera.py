"""
Camera access and face detection for youmirror.

Uses `picamera2` (built on libcamera), not the legacy `picamera`/MMAL stack.
On this Pi's kernel/firmware combination the legacy stack fails to detect
the OV5647 sensor (`vcgencmd get_camera` reports `detected=0`) even though
the sensor is physically fine — libcamera detects it without issue.

Setup requirement: `picamera2` and its libcamera Python bindings must be
installed via apt (`sudo apt-get install python3-picamera2`), not pip —
building libcamera bindings from source via pip drags in FFmpeg/PyAV and
other heavy native deps that are painful to build on a Pi Zero W. The
project venv must be created with `--system-site-packages` so it can see
the apt-installed packages. See README.md for the full setup sequence.

Face detection uses OpenCV's Haar cascade classifier.

The Pi Camera Rev 1.3 (OV5647, 5 MP) is accessed at a reduced resolution
(see config.py) to keep CPU usage manageable on the Pi Zero W single core.

Face detection returns the centre pixel of the largest detected face, or
None when no face is found, so callers don't have to inspect raw rectangles.
"""

import pathlib
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np
from picamera2 import Picamera2  # type: ignore  # available only on the Pi
from libcamera import Transform  # type: ignore  # available only on the Pi

import config


# Path to the Haar cascade bundled with OpenCV
_CASCADE_PATH = (
    pathlib.Path(cv2.__file__).parent
    / "data"
    / "haarcascade_frontalface_default.xml"
)


@dataclass
class FaceLocation:
    """Centre pixel and bounding box of a detected face."""
    cx: int          # face centre X  (pixels from left)
    cy: int          # face centre Y  (pixels from top)
    x: int           # bounding box top-left X
    y: int           # bounding box top-left Y
    w: int           # bounding box width
    h: int           # bounding box height

    @property
    def center(self) -> Tuple[int, int]:
        return (self.cx, self.cy)


class CameraController:
    """Wraps Picamera2 + OpenCV to deliver face locations frame by frame."""

    def __init__(self) -> None:
        self._camera = Picamera2()

        # picamera2's "RGB888" format is, confusingly, actually stored in
        # BGR byte order in memory — which is exactly what OpenCV expects,
        # so no channel swap is needed before running cv2 operations.
        #
        # Only 0°/180° rotation is supported here via hflip+vflip. 90°/270°
        # would require a transpose, which is not wired up — rotate frames
        # in software with cv2.rotate() in capture_frame() if ever needed.
        if config.CAMERA_ROTATION not in (0, 180):
            raise NotImplementedError(
                "CAMERA_ROTATION only supports 0 or 180 in the current "
                "picamera2 setup. Rotate in software if 90/270 is needed."
            )
        flip = config.CAMERA_ROTATION == 180
        transform = Transform(hflip=flip, vflip=flip)

        video_config = self._camera.create_video_configuration(
            main={
                "size": (config.CAMERA_WIDTH, config.CAMERA_HEIGHT),
                "format": "RGB888",
            },
            controls={"FrameRate": config.CAMERA_FRAMERATE},
            transform=transform,
        )
        self._camera.configure(video_config)
        self._camera.start()

        self._detector = cv2.CascadeClassifier(str(_CASCADE_PATH))
        if self._detector.empty():
            raise RuntimeError(
                f"Failed to load Haar cascade from {_CASCADE_PATH}. "
                "Ensure opencv-python is correctly installed."
            )

        # Give the sensor a moment to adjust exposure after start
        time.sleep(0.5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture_frame(self) -> np.ndarray:
        """Capture a single BGR frame as a NumPy array."""
        return self._camera.capture_array()

    def detect_face(self, frame: np.ndarray) -> Optional[FaceLocation]:
        """
        Run Haar face detection on *frame* and return the largest face found,
        or None if no face is detected.

        Only the largest face is returned; the assumption is that the user
        standing in front of the mirror is the primary (and typically closest)
        face in frame.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._detector.detectMultiScale(
            gray,
            scaleFactor=config.FACE_SCALE_FACTOR,
            minNeighbors=config.FACE_MIN_NEIGHBOURS,
            minSize=config.FACE_MIN_SIZE,
        )

        if len(faces) == 0:
            return None

        # Pick the largest face by area
        x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
        return FaceLocation(
            cx=x + w // 2,
            cy=y + h // 2,
            x=x, y=y, w=w, h=h,
        )

    def get_frame_center(self) -> Tuple[int, int]:
        """Return the pixel coordinates of the frame centre."""
        return (config.CAMERA_WIDTH // 2, config.CAMERA_HEIGHT // 2)

    def release(self) -> None:
        """Close the camera cleanly."""
        self._camera.stop()
        self._camera.close()

    # Allow use as a context manager
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()


# ---------------------------------------------------------------------------
# Quick standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Camera test: capturing 30 frames and reporting any detected faces.")
    with CameraController() as cam:
        frame_cx, frame_cy = cam.get_frame_center()
        for i in range(30):
            frame = cam.capture_frame()
            face = cam.detect_face(frame)
            if face:
                dx = face.cx - frame_cx
                dy = face.cy - frame_cy
                print(f"Frame {i:02d}: face at ({face.cx}, {face.cy})  "
                      f"error dx={dx:+d} dy={dy:+d}")
            else:
                print(f"Frame {i:02d}: no face detected")
            time.sleep(0.1)
    print("Camera test done.")
