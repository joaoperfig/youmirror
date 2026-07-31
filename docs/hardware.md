# Hardware Reference

Notes on every physical component in the youmirror rig.

---

## Raspberry Pi Zero W v1.1

| Property | Value |
|---|---|
| SoC | Broadcom BCM2835 (single-core ARM1176JZF-S @ 1 GHz) |
| RAM | 512 MB LPDDR2 |
| Wireless | 802.11 b/g/n + Bluetooth 4.1 |
| GPIO | 40-pin header |
| Camera connector | 22-pin CSI ribbon |
| Operating system | Raspberry Pi OS Lite **Legacy** (32-bit, Bullseye-based) |

**Performance note:** The Pi Zero W has a single slow core. Keep the camera
capture resolution low (320×240 is the default in `config.py`) and avoid
running any other CPU-heavy services while the tracker is running.

### I2C pins used by the Servo Driver HAT

| GPIO | Physical pin | Function |
|---|---|---|
| GPIO 2 | Pin 3 | SDA (I2C bus 1) |
| GPIO 3 | Pin 5 | SCL (I2C bus 1) |
| 5 V | Pin 2 or 4 | HAT power (up to 3 A via onboard regulator) |
| GND | Pin 6, 9, … | Common ground |

Enable I2C on the Pi (one-time setup):

```bash
sudo raspi-config   # → Interface Options → I2C → Enable
sudo reboot
# Verify:
i2cdetect -y 1      # should show 0x40 (and 0x70 ALLCALL alias)
```

---

## Waveshare Servo Driver HAT

- **Product page:** https://www.waveshare.com/wiki/Servo_Driver_HAT
- **Driver chip:** PCA9685 (16-channel, 12-bit PWM)
- **Default I2C address:** `0x40` (configurable via A0–A4 solder pads; `0x70` is the broadcast ALLCALL alias and always appears)
- **Servo supply:** 5 V from Pi's onboard regulator (max **3 A** combined)
- **Logic voltage:** 3.3 V
- **External power option:** Green VIN terminal, accepts **6–12 V** for high-torque servos
  - To use external power: remove the onboard 0 Ω resistor (bypasses the Pi 5 V path)

### Servo connector layout (per channel)

```
[GND / brown]  [5V / red]  [PWM / yellow]
     ↑               ↑            ↑
  Black pin      Red pin      Yellow pin
```

Channels are numbered 0–15 across the top of the HAT.

| Channel | Axis | Type |
|---|---|---|
| 0 | Pan (horizontal / left-right) | Continuous rotation — pulse commands speed + direction (see below) |
| 1 | Tilt (vertical / up-down) | Continuous rotation — pulse commands speed + direction (see below) |

> **Do not plug the servo cable in reverse** – the PCA9685 and/or servo will be damaged.

### PWM parameters

| Parameter | Value |
|---|---|
| Frequency | 50 Hz (20 ms period) |
| Resolution | 12-bit (4096 counts per period → ~4.9 µs per count at 50 Hz) |

Both servos are continuous-rotation units, so there is no angle↔pulse
mapping. Each axis uses its calibrated dead-band edges (the pulses where
movement starts in each direction, e.g. `PAN_MOVE_LEFT_US` /
`PAN_MOVE_RIGHT_US`) plus a drive offset that sets the speed — see the
Servos section below and `config.py`.

### I2C address configuration

The five pads A0–A4 add to the base address `0x40`:

| Pad soldered | Address offset |
|---|---|
| A0 | +1 |
| A1 | +2 |
| A2 | +4 |
| A3 | +8 |
| A4 | +16 |

Up to 32 boards can be stacked on the same bus. Update `PCA9685_I2C_ADDRESS`
in `config.py` if the pads are changed.

---

## Raspberry Pi Camera Module Rev 1.3

- **Sensor:** OmniVision OV5647
- **Resolution:** 5 MP (2592 × 1944 still / up to 1080p30 video)
- **Interface:** CSI ribbon cable (22-pin, Pi Zero size)
- **Field of view:** ~54° horizontal × ~41° vertical (fixed focus)
- **Focal length:** Fixed focus at ~1 m

Enable the camera (one-time setup):

> `raspi-config` does not have a Camera option on this OS version. Add the
> lines directly to the firmware config instead. Note the path is
> `/boot/firmware/config.txt` on this OS, not the older `/boot/config.txt`.

```bash
echo "start_x=1"       | sudo tee -a /boot/firmware/config.txt
echo "gpu_mem=128"      | sudo tee -a /boot/firmware/config.txt
echo "dtoverlay=ov5647" | sudo tee -a /boot/firmware/config.txt
sudo reboot

# Verify via libcamera/picamera2 (this project's camera stack):
python3 -c "from picamera2 import Picamera2; print(Picamera2.global_camera_info())"
# expect a list containing {'Model': 'ov5647', ...}
```

**Why not the legacy `picamera` library / `vcgencmd get_camera`?** On this
Pi's kernel/firmware, the legacy MMAL camera stack fails to detect the
OV5647 (`vcgencmd get_camera` reports `detected=0`) even though the sensor
is physically fine. `picamera2` (built on libcamera) detects and drives it
correctly, so this project uses that instead. See `requirements.txt` and
the README for the apt-based install (picamera2 should not be pip-installed).

The tracker captures at **320 × 240 @ 24 fps** by default (configurable in
`config.py`). The OV5647 delivers good low-light performance for an indoor
mirror scenario, but does not have IR capability.

### Ribbon cable orientation

The blue backing of the ribbon faces **away from** the PCB when inserted into
the Pi Zero's CSI connector. The metal contacts face toward the PCB.

---

## Camera-behind-mirror design

The Pi Camera is mounted on the back of the mirror, centred on it, looking
through the mirror at the user. The camera and mirror are a single rigid
assembly on the pan/tilt rig.

**Why this simplifies control:**

- When the user's face is centred in the camera frame, the mirror is already
  aimed correctly at the user's face — no geometric transformation needed.
- All servo corrections are relative: "face is 30 px to the right of frame
  centre → pan right by `Kp × 30` degrees."
- The system only ever issues incremental adjustments ("a bit more left/up"),
  not absolute angle targets.

**Direction calibration:**

There is no home position — both axes are velocity controlled and the
camera closes the loop. The only per-rig setting is the direction sense:
run `python3 test_drive.py` and check that `d` pans toward the rig's right
and `w` tilts up; flip `PAN_INVERT` / `TILT_INVERT` in `config.py` if an
axis runs the wrong way.

---

## Servos

Both servos are **continuous-rotation** units: the pulse commands **speed
and direction, not position**. Per axis, the pulses at which movement
starts (dead-band edges) are calibrated, and speed is set by how far the
drive pulse sits beyond the edge:

| Pulse | Behaviour |
|---|---|
| ≤ negative edge (e.g. ~1498 µs) | drives negative (left / down), faster the lower the pulse |
| between the edges | stopped (dead band) |
| ≥ positive edge (e.g. ~1616 µs) | drives positive (right / up), faster the higher the pulse |

**Control model.** The camera closes the tracking loop: each frame,
`main.py` converts the face-centre error vector into a direction and speed
per axis (`ServoController.drive`). Speed ramps linearly from the axis's
`OFFSET_MIN_US` (at the pixel dead band) to `OFFSET_MAX_US` (at
`FULL_SPEED_ERROR_PX` of error), so the rig slows as the face approaches
the centre and stops inside the dead band. No position is tracked and no
range limits are enforced for now.

### Pan servo (channel 0)

Dead-band edges measured on the rig: moves left at ≤ 1498 µs, right at
≥ 1616 µs. Drive offsets: 200 µs (min) to 450 µs (max). The rig's
mechanical stops are ~118° each side of centre (~236° wall to wall);
measured speed reference is ~120°/s (see `config.py`).

Calibrate the dead-band edges and reference speeds with
`python3 test_servo_pan.py` and paste the printed values into `config.py`.

### Tilt servo (channel 1)

Also continuous rotation. Its dead-band edges are **assumed identical to
the pan servo's** (`TILT_MOVE_DOWN_US` / `TILT_MOVE_UP_US` = 1498 / 1616 µs)
until the axis gets its own calibration run. Drive offsets: 100 µs (min)
to 250 µs (max).

---

## Wiring Diagram (text)

```
Raspberry Pi Zero W
┌──────────────────────────────────┐
│  Pin 2  (5V)  ──────────────────►│ Servo Driver HAT 5V (powers HAT + servos)
│  Pin 3  (SDA) ──────────────────►│ Servo Driver HAT SDA
│  Pin 5  (SCL) ──────────────────►│ Servo Driver HAT SCL
│  Pin 6  (GND) ──────────────────►│ Servo Driver HAT GND
│  CSI connector ─── ribbon ──────►│ Pi Camera Rev 1.3
└──────────────────────────────────┘

Servo Driver HAT
┌──────────────────────────────────┐
│  Channel 0 ────────────────────►│ Pan servo
│  Channel 1 ────────────────────►│ Tilt servo
└──────────────────────────────────┘
```
