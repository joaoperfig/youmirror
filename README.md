# youmirror

A pan-tilt mirror that tracks a user's face in real time, driven by a
Raspberry Pi Zero W, a Pi Camera Rev 1.3, and a Waveshare Servo Driver HAT.

---

## How it works

1. The Pi Camera captures frames at 320×240.
2. OpenCV's Haar cascade detector finds the user's face in each frame.
3. Every frame, the pixel offset between the face centre and the frame
   centre becomes a desired direction vector.
4. Both servos are continuous-rotation units, so each axis is sent a
   velocity command (direction + speed) via the Servo Driver HAT (PCA9685)
   over I2C. Speed ramps with the pixel error and the axis stops inside a
   dead band — the camera closes the loop.
5. The pan servo (channel 0) handles left/right; the tilt servo (channel 1)
   handles up/down.

---

## Repository layout

```
youmirror/
├── config.py           # all hardware constants and tuning parameters
├── servo_control.py    # PCA9685 driver (I2C via smbus2), velocity API
├── camera.py           # Pi Camera capture + OpenCV face detection
├── main.py             # tracking loop – entry point
├── test_drive.py       # manual WASD drive of both servos
├── test_servo_pan.py   # pan dead-band / speed calibration tool
├── test_camera.py      # camera + face detection test
├── requirements.txt    # Python dependencies
└── docs/
    └── hardware.md     # detailed hardware notes and wiring
```

---

## Hardware

| Component | Details |
|---|---|
| Compute | Raspberry Pi Zero W v1.1 |
| OS | Raspberry Pi OS Lite Legacy (32-bit) |
| Camera | Pi Camera Module Rev 1.3 (OV5647, 5 MP) |
| Servo HAT | Waveshare Servo Driver HAT (PCA9685, 16-ch PWM) |
| Pan servo | Channel 0 on the HAT |
| Tilt servo | Channel 1 on the HAT |

See [`docs/hardware.md`](docs/hardware.md) for full wiring details, I2C
address configuration, PWM parameters, and servo power notes.

---

## One-time Pi setup

> Tested on **Raspberry Pi Zero W v1.1**, **Raspberry Pi OS Lite Legacy**.
> On this OS the firmware config is at `/boot/firmware/config.txt`.
>
> **Camera stack note:** this project uses `picamera2` (libcamera), not the
> legacy `picamera`/MMAL stack. On this Pi's kernel/firmware, the legacy
> stack fails to detect the OV5647 sensor (`vcgencmd get_camera` reports
> `detected=0`) even though the sensor itself is fine — libcamera detects
> and drives it correctly. `picamera2` must be installed via `apt`, not
> `pip` (see step 6) — pip would otherwise try to build libcamera's Python
> bindings from source, dragging in FFmpeg dev headers and other heavy
> native deps that are painful to build on a Pi Zero W.

```bash
# 1. Enable I2C
sudo raspi-config   # Interface Options → I2C → Enable → reboot

# 2. Enable the camera stack
#    raspi-config does not have a camera option on this OS version.
#    Add the lines directly to the correct config file:
echo "start_x=1"          | sudo tee -a /boot/firmware/config.txt
echo "gpu_mem=128"         | sudo tee -a /boot/firmware/config.txt
echo "dtoverlay=ov5647"    | sudo tee -a /boot/firmware/config.txt
sudo reboot

# 3. Install system packages, including picamera2 (via apt, not pip)
sudo apt-get update
sudo apt-get install -y python3-pip python3-dev python3-smbus i2c-tools
sudo apt-get install -y python3-picamera2

# 4. Verify I2C sees the Servo Driver HAT
i2cdetect -y 1          # expect 0x40 (and 0x70 ALLCALL alias)

# 5. Verify the camera is detected via libcamera
python3 -c "from picamera2 import Picamera2; print(Picamera2.global_camera_info())"
# expect a list containing {'Model': 'ov5647', ...}
# (vcgencmd get_camera may still show detected=0 — that's the legacy
#  stack, which this project does not use, and can be ignored)

# 6. Create the venv WITH --system-site-packages so it can see the
#    apt-installed picamera2 / libcamera bindings
python3 -m venv --system-site-packages venv
source venv/bin/activate

# 7. Install the remaining Python dependencies
pip install -r requirements.txt
```

---

## Running

```bash
# Normal operation
python3 main.py

# Verbose face-error logging (useful while tuning gains)
python3 main.py --debug

# Test servos only (short velocity wiggle on both axes)
python3 servo_control.py

# Drive both servos manually (hold WASD/arrows, Shift = turbo)
python3 test_drive.py

# Calibrate the pan dead band and speeds
python3 test_servo_pan.py

# Test camera and face detection only (30-frame report)
python3 camera.py
```

Stop with **Ctrl-C** or `kill <pid>`. The servos are stopped and all PWM
channels released before the process exits.

---

## Configuration

All tuneable values are in `config.py`:

| Variable | Default | Description |
|---|---|---|
| `PAN_CHANNEL` | `0` | HAT channel for the pan servo |
| `TILT_CHANNEL` | `1` | HAT channel for the tilt servo |
| `PAN_MOVE_LEFT_US` / `PAN_MOVE_RIGHT_US` | `1498` / `1616` | Pan dead-band edges (pulse where movement starts) |
| `TILT_MOVE_DOWN_US` / `TILT_MOVE_UP_US` | `1498` / `1616` | Tilt dead-band edges (assumed = pan until calibrated) |
| `PAN_OFFSET_MIN_US` / `PAN_OFFSET_MAX_US` | `200` / `450` | Pan speed range: drive offset beyond the dead-band edge |
| `TILT_OFFSET_MIN_US` / `TILT_OFFSET_MAX_US` | `100` / `250` | Tilt speed range |
| `PAN_INVERT` / `TILT_INVERT` | `False` | Flip an axis's direction sense |
| `CAMERA_WIDTH/HEIGHT` | `320×240` | Capture resolution |
| `CAMERA_FRAMERATE` | `24` | Frames per second |
| `DEAD_BAND_PX` | `10` | Stop the axis when the error is smaller than this |
| `FULL_SPEED_ERROR_PX` | `100` | Pixel error at which an axis reaches full speed |

Raise the `OFFSET_MAX` values if tracking feels sluggish; lower the
`OFFSET_MIN` values (or raise `FULL_SPEED_ERROR_PX` for a gentler ramp)
if the mirror oscillates around the face.

---

## Deploying changes from this repo to the Pi

```bash
# On the Pi – pull latest and restart
cd ~/youmirror
git pull
python3 main.py
```

Or set up a systemd service so it starts automatically on boot:

```ini
# /etc/systemd/system/youmirror.service
[Unit]
Description=youmirror face-tracking
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/youmirror/main.py
WorkingDirectory=/home/pi/youmirror
Restart=on-failure
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable youmirror
sudo systemctl start youmirror
```
