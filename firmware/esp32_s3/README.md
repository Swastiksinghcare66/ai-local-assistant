# SIA ESP32-S3 Production Firmware V2.0

Target location:

`D:\Alexa_lite\Alexa_lite\firmware\esp32_s3`

This is a **production-oriented embedded audio architecture**, not a claim of finished commercial certification.

## Why this firmware is different

The old `src/main.cpp` was an Arduino mic-only test. This package migrates the firmware to **native ESP-IDF** and **ESP-SR 2.5.3** so the ESP32-S3 can run the audio front-end expected in a real voice product:

- INMP441 I2S capture
- MAX98357A I2S playback
- synchronized dual-relay BTL source switching
- full-duplex AEC with speaker playback reference
- single-channel noise suppression
- VAD
- continuous processed microphone streaming to Parakeet
- continuous TTS PCM playback
- framed USB CDC binary transport with sequence numbers + CRC32
- health counters
- safe boot route
- watchdog-ready FreeRTOS architecture
- PSRAM validation
- OTA-capable partition layout
- coredump partition

## Important terminology

With one INMP441, SIA can do:

- AEC: yes
- single-channel NS/ANS: yes
- VAD: yes
- barge-in/full-duplex: yes, after host integration/tuning

It cannot do true spatial beamforming or true consumer-headphone-style ANC with one microphone.

## Production voice sample rate

The embedded full-duplex path is intentionally **16 kHz PCM16 mono**.

ESP-SR's current AEC supports 16 kHz. Therefore:

`CosyVoice 24 kHz -> PC resample to 16 kHz -> USB -> ESP32 -> MAX98357A`

The exact PCM sent to MAX is also used as the AEC far-end reference.

A future Hi-Fi mode may keep 24 kHz TTS when the mic is intentionally half-duplex/muted.

## Pins

### INMP441
- BCLK = GPIO12
- WS = GPIO13
- SD = GPIO14
- L/R = GND
- supply = 3.3 V

### MAX98357A
- BCLK = GPIO6
- LRC/WS = GPIO5
- DIN = GPIO7

### Relay
- GPIO4 -> IN1 through level shifter
- GPIO10 -> IN2 through level shifter
- active LOW
- both relay channels always switch together

BTL warning: never connect MAX/PAM negative speaker output to ground.

## AFE

Input format is `MR`:

- M = microphone
- R = exact playback reference

AFE configuration:

- `AFE_TYPE_FD`
- `AFE_MODE_LOW_COST`
- `AEC_MODE_FD_LOW_COST`
- `AEC_NLP_LEVEL_NORMAL`
- WebRTC NS baseline
- WebRTC VAD baseline
- AFE AGC disabled to avoid double-AGC with SIA's PC-side post processing
- WakeNet disabled until a custom/licensed SIA wake model is chosen

## Build toolchain

Use Espressif's official ESP-IDF toolchain, pinned to IDF 5.5.x for this baseline.

Do not compile this project with the old Arduino `platformio.ini`.

Typical commands in an ESP-IDF terminal:

```powershell
cd D:\Alexa_lite\Alexa_lite\firmware\esp32_s3

idf.py set-target esp32s3
idf.py fullclean
idf.py build
idf.py -p COM9 flash monitor
```

On the first build, IDF Component Manager resolves:

- `espressif/esp-sr 2.5.3`
- `espressif/esp_tinyusb 2.2.0`

## PC integration requirement

The existing `app\hardware\sia_esp32.py` must be upgraded to the SIA1 framed binary protocol in this package.

Do not use the old single-byte `R/P/T` production protocol after migration.

## Before installing

Back up the existing firmware folder first.

See `install_into_alexa_lite.ps1`.

## Commercialization checklist still required

Firmware architecture alone does not make a certified market product. Before sale/release, complete:

- enclosure acoustic characterization
- echo-return-loss enhancement (ERLE) testing
- double-talk testing
- far-field WER testing
- speaker distortion / SPL testing
- 24-72 h audio soak testing
- USB disconnect/reconnect tests
- brownout / power-cycle tests
- ESD tests
- EMC/EMI compliance
- radio regulatory compliance if Wi-Fi/BLE is shipped
- battery/charger safety and transport compliance
- thermal validation
- secure boot + flash-encryption provisioning
- OTA rollback validation
- production fixture + per-unit audio QA

Secure Boot / Flash Encryption are deliberately NOT fused by this development package. Enabling release eFuses is a manufacturing/provisioning step and can be irreversible.
