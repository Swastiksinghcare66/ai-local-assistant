# SARA / SIA — Hardware and Embedded Architecture

## 1. Hardware overview

The embedded subsystem is centered on:

```text
ESP32-S3 DevKitC-1
ESP32-S3-WROOM-1 N16R8
```

Primary peripherals:

- INMP441 digital I2S microphone
- MAX98357A I2S DAC/amplifier
- speaker
- dual relay/audio-route hardware
- USB connection to Windows host

---

## 2. Physical signal path

### Input

```text
User
 ↓ acoustic
INMP441
 ↓ I2S
ESP32-S3
 ↓ ESP-SR AFE
USB CDC
 ↓
Windows
```

### Output

```text
Windows 16 kHz PCM
 ↓ USB CDC
ESP32-S3
 ↓ I2S
MAX98357A
 ↓ amplified speaker signal
Speaker
```

---

## 3. INMP441 connection

Firmware documentation currently specifies:

| Signal | ESP32-S3 |
|---|---|
| BCLK | GPIO12 |
| WS | GPIO13 |
| SD | GPIO14 |
| L/R | GND |
| Supply | 3.3 V |

The INMP441 is a digital microphone; the host does not sample analog audio directly.

---

## 4. MAX98357A connection

| Signal | ESP32-S3 |
|---|---|
| BCLK | GPIO6 |
| LRC / WS | GPIO5 |
| DIN | GPIO7 |

The MAX98357A receives I2S PCM and drives the speaker.

---

## 5. Relay / route control

Firmware documentation specifies:

| Function | GPIO |
|---|---|
| Relay IN1 | GPIO4 through level shifter |
| Relay IN2 | GPIO10 through level shifter |

The relay channels are active-low and intended to switch together.

The firmware README includes an important BTL warning: speaker negative outputs from BTL amplifier paths must not be treated as ordinary ground.

---

## 6. ESP-SR audio front-end

The current firmware architecture uses an `MR` input format:

```text
M = microphone
R = exact playback reference
```

That lets the AEC path compare near-end microphone input against the actual far-end audio being played.

Configured concepts include:

- full-duplex AFE
- low-cost AFE mode
- low-cost full-duplex AEC
- normal AEC NLP level
- WebRTC NS baseline
- WebRTC VAD baseline
- AFE AGC disabled to avoid double AGC
- WakeNet disabled until an appropriate wake model is selected

---

## 7. What can one microphone actually do?

With the current single-INMP441 architecture:

### Reasonable claims

- acoustic echo cancellation
- single-channel noise suppression
- voice activity detection

### Claims to avoid

- true spatial beamforming
- microphone-array direction finding
- consumer-headphone-style active noise cancellation

This distinction matters in interviews.

---

## 8. Embedded sample rate

The production audio contract is:

```text
16 kHz
PCM16
mono
```

Reason: the selected ESP-SR AEC path is built around 16 kHz.

The high-quality CosyVoice path therefore uses:

```text
CosyVoice @ 24 kHz
 ↓
Windows stateful resampling
 ↓
16 kHz PCM16
 ↓
ESP32
```

---

## 9. Firmware structure

Canonical location:

```text
firmware/esp32_s3/
```

Important files:

```text
main/app_main.cpp
main/audio_frontend.cpp
main/audio_frontend.h
main/audio_io.cpp
main/audio_io.h
main/board_config.h
main/diagnostics.cpp
main/diagnostics.h
main/relay_manager.cpp
main/relay_manager.h
main/sia_protocol.cpp
main/sia_protocol.h
main/system_state.cpp
main/system_state.h
main/usb_transport.cpp
main/usb_transport.h
main/idf_component.yml
partitions.csv
sdkconfig.defaults
```

---

## 10. Native ESP-IDF design

The current firmware moved beyond the earlier Arduino mic-only prototype.

The architecture is native ESP-IDF and uses ESP-SR.

The firmware documentation targets an ESP-IDF 5.5.x baseline and records ESP-SR/TinyUSB component versions.

This gives access to:

- FreeRTOS task architecture
- ESP-SR AFE
- TinyUSB/USB CDC
- PSRAM
- OTA partitioning
- coredump support
- production-oriented diagnostics

---

## 11. Host protocol

Python implementation:

```text
app/audio/sia_hardware.py
```

Protocol framing:

```text
MAGIC   = 0x31414953
VERSION = 1
```

Transport default:

```text
921600 baud
```

Validated Espressif USB identity used for preferred discovery:

```text
VID:PID = 303A:4001
```

---

## 12. Protocol operations

### Host control

```text
HOST_HELLO
SET_ROUTE
PING
GET_STATS
```

### Playback

```text
TTS_START
TTS_PCM
TTS_END
```

### Microphone

```text
MIC_START
MIC_STOP
MIC_PCM
VAD_EVENT
```

### Device responses

```text
DEVICE_HELLO
ROUTE_ACK
PONG
STATS
TTS_READY
TTS_DONE
ERROR
```

---

## 13. Why persistent ownership?

One `SIAHardware` instance owns the serial port for the whole runtime.

This prevents:

- competing readers
- interleaved packets
- repeated port open/close delays
- ownership ambiguity

Thread-safe transmission and event-driven acknowledgements are handled inside the transport abstraction.

---

## 14. Playback session

`SIAAudioPlayer` exposes a playback interface compatible with the TTS client but routes audio to hardware instead of a PC speaker.

A logical playback session looks like:

```text
set SIA route
reset resampler/DSP
TTS_START
TTS_PCM...
TTS_END
wait TTS_DONE
```

---

## 15. Productization work still required

The firmware README correctly states that architecture is not commercial certification.

Before a real product release, validate at least:

- ERLE / AEC quality
- double-talk
- far-field WER
- speaker SPL/distortion
- long audio soak
- USB reconnect
- brownout/power cycles
- ESD
- EMC/EMI
- thermal behavior
- secure boot / flash encryption provisioning
- OTA rollback
- production fixture and audio QA

This is useful interview context because it distinguishes a development prototype from a certified product.
