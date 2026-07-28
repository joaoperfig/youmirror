# youmirror

A pan-tilt mirror that tracks a user's face in real time, driven by a
Raspberry Pi Zero W, a Pi Camera Rev 1.3, and a Waveshare Servo Driver HAT.

---

## How it works

1. The Pi Camera captures frames at 320×240.
2. OpenCV's Haar cascade detector finds the user's face in each frame.
3. A proportional controller calculates the angular error between the face
   centre and the frame centre.
4. The error is converted to servo angle corrections and sent to the
   Servo Driver HAT (PCA9685) over I2C.
5. The pan servo (channel 0) handles left/right; the tilt servo (channel 1)
   handles up/down.

---

## Repository layout

```
youmirror/
├── config.py          # all hardware constants and tuning parameters
├── servo_control.py   # PCA9685 driver (I2C via smbus2)
├── camera.py          # Pi Camera capture + OpenCV face detection
├── main.py            # tracking loop – entry point
├── requirements.txt   # Python dependencies
└── docs/
    └── hardware.md    # detailed hardware notes and wiring
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

# Test servos only (sweep pan axis 0°→180°→90°)
python3 servo_control.py

# Test camera and face detection only (30-frame report)
python3 camera.py
```

Stop with **Ctrl-C** or `kill <pid>`. The servos return to their home
position (90°/90°) before the process exits.

---

## Configuration

All tuneable values are in `config.py`:

| Variable | Default | Description |
|---|---|---|
| `PAN_CHANNEL` | `0` | HAT channel for the pan servo |
| `TILT_CHANNEL` | `1` | HAT channel for the tilt servo |
| `PAN_HOME_ANGLE` | `90` | Pan neutral position (degrees) |
| `TILT_HOME_ANGLE` | `90` | Tilt neutral position (degrees) |
| `CAMERA_WIDTH/HEIGHT` | `320×240` | Capture resolution |
| `CAMERA_FRAMERATE` | `24` | Frames per second |
| `KP_PAN` / `KP_TILT` | `0.05` | Proportional gain (°/px) |
| `DEAD_BAND_PX` | `10` | Ignore errors smaller than this |

Increase `KP_PAN` / `KP_TILT` if tracking feels sluggish; decrease if the
mirror oscillates around the face.

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
