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

| Channel | Axis | Direction |
|---|---|---|
| 0 | Pan (horizontal / left-right) | Multi-turn servo; rig degrees 0 = left wall … `PAN_TRAVEL_DEG` = right wall (see below) |
| 1 | Tilt (vertical / up-down) | 0° = full down, 90° = centre, 180° = full up |

> **Do not plug the servo cable in reverse** – the PCA9685 and/or servo will be damaged.

### PWM parameters

| Parameter | Value |
|---|---|
| Frequency | 50 Hz (20 ms period) |
| Min pulse | 500 µs ≈ 0° (tilt axis) |
| Max pulse | 2500 µs ≈ 180° (tilt axis) |
| Resolution | 12-bit (4096 counts per period → ~4.9 µs per count at 50 Hz) |

These values match the defaults in `config.py`. Adjust `SERVO_PULSE_MIN_US`
/ `SERVO_PULSE_MAX_US` if the tilt servo doesn't hit its endpoints cleanly.
The **pan axis does not use this mapping** — it uses the pulse endpoints
measured at the rig's mechanical stops (`PAN_PULSE_LEFT_US` /
`PAN_PULSE_RIGHT_US`, calibrated with `test_servo_pan.py`).

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

**Home position calibration:**

The `PAN_HOME_ANGLE` and `TILT_HOME_ANGLE` values in `config.py` must be set
to the angles where the mirror points straight ahead at a standing user —
not blindly to 90°/90°. Procedure:

1. Mount the mirror/camera assembly on the rig.
2. Stand in front of the mirror at the expected use distance.
3. Run `python3 servo_control.py` and manually command angles until the mirror
   reflects your face back at you centred.
4. Record those angles and update `PAN_HOME_ANGLE` / `TILT_HOME_ANGLE`.

---

## Servos

### Pan servo (channel 0) — continuous rotation

The pan servo is a **continuous-rotation** unit: the pulse commands **speed
and direction, not position**. Measured on the rig:

| Pulse | Behaviour |
|---|---|
| ≤ ~1500 µs | rotates toward the left wall |
| ~1500–1616 µs | stopped (dead band) |
| ≥ ~1616 µs | rotates toward the right wall |

The rig's mechanical stops are ~118° each side of centre (~236° wall to
wall). Measured drive speed at the configured offset is ~120°/s each way.

**Control model.** The camera closes the tracking loop (rotate toward the
face, stop when it is centred in frame), so absolute position is never
needed for tracking. To keep the rig off its mechanical stops, position is
**dead-reckoned**: estimated degrees = commanded direction × measured speed
× time (`ServoController.pan_position_deg`). Soft limits refuse to drive
past ±`PAN_SOFT_LIMIT_DEG` of estimated excursion.

**Startup homing.** The estimate is anchored automatically when `main.py`
starts (`ServoController.pan_home`): the rig drives left long enough to
guarantee touching the left wall from any starting position (a brief,
gentle stall), then drives right for half the travel time — that point is
the physical centre and the estimate is zeroed there. The estimate still
drifts slowly afterwards (speed varies with load and supply voltage); the
soft-limit margin absorbs this.

Calibrate the dead-band edges and the per-direction speeds with
`python3 test_servo_pan.py` and paste the printed values into `config.py`.

### Tilt servo (channel 1) — standard

| Spec | Recommendation |
|---|---|
| Type | PWM hobby servo (50 Hz, 500–2500 µs, 180°) |
| Torque | ≥ 1.5 kg·cm for a small mirror |
| Voltage | 5 V (matches HAT output) |
| Note | Avoid high-torque servos (e.g. MG996R) without external power on VIN |

Low-power servos like the **SG90** or **MG90S** work well at 5 V from the Pi.
For heavier mirrors, supply 6–12 V via the VIN terminal after removing the
onboard 0 Ω resistor.

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
