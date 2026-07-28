"""
Camera sanity-check.

Captures a single frame from the Pi Camera Rev 1.3 and prints basic
statistics about it so you can confirm the camera is alive and producing
sensible image data without needing a display.

What it checks
--------------
  - Camera opens without error (ribbon connected, camera enabled in raspi-config)
  - Frame has the expected dimensions and 3 colour channels
  - Pixel values are not all black (lens cap off, sensor responding)
  - Pixel values are not all saturated/white (exposure not blown out)
  - The three colour channels have roughly similar mean brightness
    (a very large imbalance would suggest a stuck/broken sensor channel)

Usage
-----
    python3 test_camera.py
"""

import sys
import time

import numpy as np

import config
from camera import CameraController


def channel_stats(frame: "np.ndarray", ch: int, name: str) -> None:
    data = frame[:, :, ch].astype(float)
    print(f"    {name}  mean={data.mean():6.1f}  min={data.min():3.0f}"
          f"  max={data.max():3.0f}  std={data.std():5.1f}")


def main() -> None:
    print("=" * 55)
    print("  youmirror – camera sanity check")
    print(f"  Expected resolution : {config.CAMERA_WIDTH} × {config.CAMERA_HEIGHT}")
    print(f"  Framerate           : {config.CAMERA_FRAMERATE} fps")
    print("=" * 55)

    print("\n  Opening camera…")
    try:
        cam = CameraController()
    except Exception as e:
        print(f"\n  ERROR: Could not open camera: {e}")
        print("  → Is the ribbon cable seated correctly?")
        print("  → Is the camera enabled?  (sudo raspi-config → Interface Options → Camera)")
        sys.exit(1)

    print("  Camera opened OK. Waiting for auto-exposure to settle…")
    time.sleep(1.5)

    print("  Capturing frame…")
    try:
        frame = cam.capture_frame()
    except Exception as e:
        print(f"\n  ERROR: Frame capture failed: {e}")
        cam.release()
        sys.exit(1)
    finally:
        cam.release()

    print("  Frame captured OK.\n")

    # ── Dimensions ─────────────────────────────────────────────────────────
    h, w, ch = frame.shape
    print(f"  Dimensions : {w} × {h} px, {ch} channels (BGR)")
    dim_ok = (w == config.CAMERA_WIDTH and h == config.CAMERA_HEIGHT and ch == 3)
    print(f"  Dimensions : {'OK' if dim_ok else 'UNEXPECTED – check CAMERA_WIDTH/HEIGHT in config.py'}")

    # ── Overall brightness ──────────────────────────────────────────────────
    mean_brightness = frame.mean()
    print(f"\n  Overall mean brightness : {mean_brightness:.1f}  (0=black, 255=white)")
    if mean_brightness < 5:
        print("  WARNING: image is nearly black – lens cap on? ribbon loose?")
    elif mean_brightness > 250:
        print("  WARNING: image is nearly white – sensor saturated or blown out")
    else:
        print("  Brightness              : OK")

    # ── Per-channel stats ───────────────────────────────────────────────────
    print("\n  Per-channel stats (BGR order):")
    channel_stats(frame, 0, "B")
    channel_stats(frame, 1, "G")
    channel_stats(frame, 2, "R")

    b_mean = frame[:, :, 0].mean()
    g_mean = frame[:, :, 1].mean()
    r_mean = frame[:, :, 2].mean()
    max_imbalance = max(b_mean, g_mean, r_mean) - min(b_mean, g_mean, r_mean)
    if max_imbalance > 80:
        print(f"\n  WARNING: large channel imbalance ({max_imbalance:.1f}) – possible sensor issue")
    else:
        print(f"\n  Channel balance : OK (max spread {max_imbalance:.1f})")

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 55)
    all_ok = dim_ok and 5 <= mean_brightness <= 250 and max_imbalance <= 80
    if all_ok:
        print("  RESULT: camera looks healthy")
    else:
        print("  RESULT: one or more checks flagged – see warnings above")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
