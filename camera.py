"""
Camera access and face detection for youmirror.

Uses the legacy `picamera` library (correct for Raspberry Pi OS Lite Legacy)
together with OpenCV's Haar cascade classifier for face detection.

The Pi Camera Rev 1.3 (OV5647, 5 MP) is accessed at a reduced resolution
(see config.py) to keep CPU usage manageable on the Pi Zero W single core.

Face detection returns the centre pixel of the largest detected face, or
None when no face is found, so callers don't have to inspect raw rectangles.
"""

import io
import pathlib
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np
import picamera  # type: ignore  # available only on the Pi

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
    """Wraps PiCamera + OpenCV to deliver face locations frame by frame."""

    def __init__(self) -> None:
        self._camera = picamera.PiCamera()
        self._camera.resolution = (config.CAMERA_WIDTH, config.CAMERA_HEIGHT)
        self._camera.framerate = config.CAMERA_FRAMERATE
        self._camera.rotation = config.CAMERA_ROTATION

        # Pre-allocate a reusable stream buffer for raw frame capture
        self._stream = io.BytesIO()

        self._detector = cv2.CascadeClassifier(str(_CASCADE_PATH))
        if self._detector.empty():
            raise RuntimeError(
                f"Failed to load Haar cascade from {_CASCADE_PATH}. "
                "Ensure opencv-python is correctly installed."
            )

        # Give the sensor a moment to adjust exposure after init
        import time; time.sleep(0.5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture_frame(self) -> np.ndarray:
        """Capture a single BGR frame as a NumPy array."""
        self._stream.seek(0)
        self._camera.capture(self._stream, format="bgr", use_video_port=True)
        self._stream.seek(0)
        data = np.frombuffer(self._stream.read(), dtype=np.uint8)
        return data.reshape((config.CAMERA_HEIGHT, config.CAMERA_WIDTH, 3))

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
    import time

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
