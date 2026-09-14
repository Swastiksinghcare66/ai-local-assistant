# SARA / SIA — Interview Demo Guide

## 1. Goal

The demo should prove that SARA is one integrated system.

Do not spend the first minute scrolling code.

Show:

1. physical device
2. runtime boundaries
3. wake behavior
4. local inference
5. follow-up conversation
6. multilingual behavior
7. sleep transition

Target length: **60–90 seconds**.

---

## 2. Before the interview

Verify:

- ESP32-S3 is powered and detected
- firmware is the expected build
- Ollama is running
- `gemma3:4b` is installed
- WSL2 CosyVoice backend is healthy
- Windows project venv is active
- `SIA_PORT` is correct or discovery is working
- speaker route is functional
- microphone level is stable

Do not update dependencies immediately before a demo.

---

## 3. Demo opening — 10 seconds

Show the hardware.

Say:

> “This is SARA, a local cross-device voice assistant. The ESP32 handles the real-time audio boundary, Windows handles speech/agent/LLM orchestration, and WSL2 runs the high-quality speech backend.”

---

## 4. Show the architecture — 10 seconds

Keep the README architecture diagram open.

Point to:

```text
ESP32-S3
  ↓
Windows runtime
  ↓
STT + agent + Ollama
  ↓
WSL2 CosyVoice
  ↓
Windows resampling
  ↓
ESP32 speaker
```

---

## 5. Wake demo — 10 seconds

Start in STANDBY.

Say:

```text
SIA
```

Expected behavior:

- wake accepted
- route changes to assistant speaker path
- runtime enters ACTIVE
- acknowledgement may play for wake-only input

Explain:

> “Once it wakes, it stays active; I don’t require the wake word before every follow-up.”

---

## 6. English conversation — 15 seconds

Ask:

```text
Explain what a neural network is in one sentence.
```

Then immediately ask without saying SIA:

```text
Give me one embedded-systems example.
```

This demonstrates persistent ACTIVE mode and conversation continuity.

---

## 7. Hinglish / language routing — 10 seconds

Ask:

```text
Ab isko simple Hinglish mein samjhao.
```

Explain:

> “Wake recognition and conversation recognition are separate. Faster-Whisper handles the multilingual conversation path, and the output language router can choose the Hindi/Hinglish speech path.”

---

## 8. Local capability demo — optional 10 seconds

Use a safe deterministic request such as:

```text
What is my system status?
```

or a supported app/media action.

Explain:

> “Supported deterministic actions go through the capability layer instead of asking the LLM to pretend an action happened.”

---

## 9. Sleep — 5 seconds

Say:

```text
sleep
```

Expected:

```text
ACTIVE → STANDBY
```

This closes the interaction loop cleanly.

---

## 10. 30-second technical pitch

> **SARA is a cross-device local conversational AI runtime. I built the embedded audio layer on ESP32-S3 using ESP-IDF/ESP-SR, with INMP441 input, MAX98357A output and a framed USB protocol. Windows owns the assistant state, Parakeet wake recognition, Faster-Whisper multilingual STT, agent routing and a local Gemma 3 4B model through Ollama. High-quality English speech is served by a persistent CosyVoice backend in WSL2, then resampled from 24 kHz to the ESP32’s 16 kHz playback contract. The important part of the project is the system integration and resource-aware separation between the MCU, host and GPU speech backend.**

---

## 11. 90-second technical explanation

### Problem
A useful local assistant needs more than an LLM. It needs real-time audio, state, device transport, STT, TTS, language handling, tool routing and error recovery.

### Architecture
I split it into three compute domains:

- ESP32-S3 for deterministic audio/device work
- Windows for orchestration and local intelligence
- WSL2 for the specialized GPU TTS stack

### Input
The ESP32 captures audio and uses the ESP-SR AFE architecture. The host receives framed PCM. Parakeet handles wake recognition and Faster-Whisper handles active multilingual conversation.

### Intelligence
The transcript moves through state/context/agent logic and then the local Ollama model, currently Gemma 3 4B.

### Output
LLM text is buffered into speakable chunks, sent through a persistent CosyVoice WebSocket, returned as 24 kHz PCM, converted to 16 kHz on Windows and streamed to the ESP32/MAX98357A speaker path.

### Product behavior
SARA has explicit standby/active/offline states. After wake, silence does not force another wake word; only `sleep` returns it to standby.

---

## 12. Likely interview questions

### Why WSL?
Because the CosyVoice/vLLM/TensorRT-oriented stack is easier to isolate in Linux while Windows remains the product host.

### Why not everything on ESP32?
The AI models are too large; ESP32 owns the real-time edge boundary, not the heavy inference.

### Why two STT models?
Wake and multilingual conversation have different constraints.

### Why CPU Faster-Whisper?
To preserve GPU headroom for concurrent local inference/TTS workloads.

### Why persistent WebSocket?
To avoid reconnect/setup overhead on each TTS phrase.

### Why 16 kHz?
The embedded full-duplex/AEC contract is built around the ESP-SR 16 kHz path.

### How do you handle latency?
The pipeline records endpointing, STT, LLM TTFT, chunk wait, TTS TTFA and full speech-to-audio time.

### Is barge-in finished?
No. The firmware architecture supports full-duplex/AEC work, but host barge-in is intentionally disabled in the stable path until it is validated robustly.

That is the correct answer.

---

## 13. What not to claim

Do not say:

- “fully production ready”
- “commercial-grade ANC”
- “beamforming” with the current one-mic setup
- “zero latency”
- “fully offline web search”
- “one-click install” until packaging is complete
- “barge-in fully solved”
- a fixed flow-step benchmark before client/server config is normalized

Honest scope makes the project stronger, not weaker.

---

## 14. What to show if the live demo fails

Have:

- a short recorded demo
- README architecture
- terminal screenshot showing healthy services
- benchmark output
- hardware photo

Then explain the failure boundary rather than improvising.

A systems engineer should be able to say **which subsystem failed and why**.
