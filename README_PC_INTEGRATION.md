# SIA PC Hardware Bridge V1

This package is intentionally additive. It does **not** overwrite:

- `app/main.py`
- `app/pipeline/voice_pipeline.py`
- `app/audio/cosyvoice_client.py`
- `app/audio/wake_listener.py`
- `app/audio/stt.py`

The current audit showed that `app/hardware` does not yet exist, while the
current VoicePipeline still constructs `WakeListener` and
`CosyVoicePersistentClient` directly. This package creates the hardware
boundary first; minimal integration patches should be applied only after the
ESP-IDF firmware builds and the protocol smoke test passes.

## Added files

```text
app/
  hardware/
    __init__.py
    sia_protocol.py
    sia_esp32.py
    audio_resampler.py
  audio/
    sia_audio_source.py

tests/
  test_sia_protocol.py
  test_sia_resampler.py
  test_sia_hardware_smoke.py

requirements_sia_hardware.txt
```

## Architecture

```text
ESP32-S3 AFE
  AEC + NS + VAD
       |
       | SIA1 framed USB CDC
       v
app.hardware.sia_esp32.SIAESP32
       |
       +--> SIAHardwareListener --> WakeCapture --> Parakeet
       |
CosyVoice 24 kHz PCM
       |
       v
SIAHardwareAudioPlayer
       |
       v
SoXR streaming 24 -> 16 kHz
       |
       v
SIAESP32.tts_pcm()
       |
       v
MAX98357A + exact AEC reference
```

## Why SoXR

Do not resample each CosyVoice websocket packet independently. A stateful
streaming resampler preserves continuity across arbitrary websocket packet
boundaries and produces a cleaner far-end reference for AEC.

## Install dependencies

From the Alexa Lite venv:

```powershell
cd D:\Alexa_lite\Alexa_lite
& ".\.venv\Scripts\python.exe" -m pip install -r .\requirements_sia_hardware.txt
```

## Software-only tests

These can run before the ESP firmware is flashed:

```powershell
& ".\.venv\Scripts\python.exe" .\tests\test_sia_protocol.py
& ".\.venv\Scripts\python.exe" .\tests\test_sia_resampler.py
```

## Hardware smoke test

Run only after the new ESP-IDF firmware has built and been flashed:

```powershell
& ".\.venv\Scripts\python.exe" .\tests\test_sia_hardware_smoke.py
```

## Next integration patch

After hardware smoke passes:

1. Create one `SIAESP32` during `VoicePipeline.initialize()`.
2. Replace `WakeListener(stt=self.stt)` with
   `SIAHardwareListener(hardware=self.hardware, stt=self.stt)`.
3. Replace the CosyVoice `PCMAudioPlayer` with
   `SIAHardwareAudioPlayer(self.hardware)`.
4. Preserve the existing Parakeet, PromptBuilder, Qwen, semantic phrase, and
   CosyVoice request logic.
5. Add a barge-in worker after AEC/double-talk validation.

Do not enable aggressive second-stage denoising until WER A/B proves it helps.
