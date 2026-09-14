# SARA / SIA — Design Decisions

This document answers the questions a technical interviewer is most likely to ask.

---

## 1. Why not build this as one Python script?

Because SARA crosses several fundamentally different boundaries:

- real-time embedded audio
- serial transport
- desktop control
- speech recognition
- LLM inference
- GPU speech synthesis
- conversational state

A monolith would make failures hard to isolate and components hard to replace.

The system therefore separates:

```text
embedded device
transport
host orchestration
AI inference
speech serving
product policy
```

---

## 2. Why ESP32-S3?

The ESP32-S3 gives SARA a real embedded boundary.

It can own:

- I2S microphone capture
- I2S speaker playback
- ESP-SR audio front-end
- VAD
- AEC reference handling
- relay/audio routing
- persistent USB transport
- future sensors/actuators

This makes the project an embedded AI system rather than only a desktop voice app.

---

## 3. Why keep the heavy AI on the host?

Speech and LLM models exceed what is practical on the ESP32-S3.

The partition is intentional:

```text
ESP32-S3 → deterministic real-time I/O
Windows   → orchestration + STT + LLM + tools
WSL2      → specialized GPU TTS environment
```

Each machine does the work it is best suited for.

---

## 4. Why Windows for orchestration?

The product is designed to interact with the user's PC.

Windows simplifies:

- application launching/resolution
- local system information
- PC actions
- UI
- serial device access
- Ollama integration

Moving the complete runtime into Linux would make Windows-control features less natural.

---

## 5. Why WSL2 for CosyVoice?

The CosyVoice/vLLM/TensorRT-oriented stack is easier to manage in a Linux environment.

WSL2 lets the project keep Windows as the product host while isolating Linux-first ML dependencies.

This is a pragmatic engineering compromise, not an architectural requirement forever.

Long term, the backend could be replaced by:

- a native Windows runtime
- containerized service
- remote LAN inference node
- dedicated edge AI device

without rewriting the whole assistant.

---

## 6. Why local inference?

Primary reasons:

- privacy
- offline capability
- control over model/runtime behavior
- predictable dependency boundaries
- direct profiling
- no per-request cloud requirement

Local inference also exposes real systems problems—VRAM pressure, model residency, startup latency and resource contention—which are hidden by cloud APIs.

---

## 7. Why Ollama?

Ollama provides a simple local serving boundary.

The assistant code sends messages to a model service instead of embedding model-loading logic into the voice pipeline.

That makes model replacement much easier.

---

## 8. Why `gemma3:4b`?

The live configuration currently selects:

```text
gemma3:4b
```

It offers substantially stronger general conversational ability than ultra-small local models while still being deployable on the available development hardware.

The rest of the architecture does not depend strongly on Gemma specifically; model selection is isolated in configuration/client code.

---

## 9. Why partial GPU offload?

The current LLM client requests:

```text
num_gpu = 4
```

The project has competing GPU workloads.

A fully GPU-resident LLM can consume VRAM needed by the TTS stack.

The engineering goal is therefore **system-level latency**, not maximum standalone LLM benchmark speed.

---

## 10. Why separate wake STT and conversation STT?

They optimize different objectives.

### Wake path
Parakeet is the known, proven wake/English recognizer.

### Conversation path
Faster-Whisper gives broader multilingual/Hinglish support.

Trying to force one model/configuration to solve both tasks creates unnecessary compromises.

---

## 11. Why keep Faster-Whisper on CPU int8?

The configuration deliberately keeps conversation STT on CPU:

```text
device=cpu
compute_type=int8
```

This leaves GPU headroom for LLM/TTS workloads and reduces cross-model VRAM contention.

Again, the objective is whole-system behavior.

---

## 12. Why explicit language routing?

The model should not be the only component deciding how speech is produced.

Language routing separates:

- user language detection
- explicit user preference
- text response behavior
- TTS backend selection

This is especially important because English and Hindi/Hinglish currently use different speech paths.

---

## 13. Why persistent CosyVoice WebSocket?

Opening a fresh backend connection and paying setup overhead for every phrase would increase latency.

The client therefore maintains one connection that can carry multiple sequential TTS requests.

The design supports:

```text
LLM phrase 1 → TTS
LLM phrase 2 → TTS
LLM phrase 3 → TTS
```

without reconnecting each time.

---

## 14. Why stream LLM text into TTS-sized chunks?

Waiting for the entire LLM answer before synthesis increases perceived latency.

But sending every token to TTS creates poor speech.

SARA therefore uses a sentence/phrase buffer that emits only speakable chunks.

This balances:

- early speech
- prosody
- technical-text integrity
- backend overhead

---

## 15. Why 16 kHz on the embedded full-duplex path?

The firmware README states that the current ESP-SR AEC path is based on 16 kHz audio.

Therefore:

```text
CosyVoice 24 kHz
  ↓
host resample
  ↓
16 kHz PCM16
  ↓
ESP32 playback
```

The exact speaker PCM can also serve as the far-end AEC reference.

---

## 16. Why stateful resampling?

TTS arrives in arbitrary streamed chunks.

Resampling each chunk independently can introduce discontinuities.

`SIAAudioPlayer` preserves conversion state across chunks so the audio stream remains continuous.

---

## 17. Why a framed USB protocol?

Raw unstructured bytes are fragile for a full product protocol.

SARA needs to distinguish:

- microphone audio
- TTS audio
- routing
- VAD events
- handshake
- stats
- acknowledgements
- errors

Framing, sequence numbers and CRC32 make those operations explicit and debuggable.

---

## 18. Why explicit assistant states?

Without states, a voice assistant can accidentally:

- listen while speaking
- require the wake word too often
- execute stale commands
- confuse idle timeout with sleep
- lose track of session ownership

Explicit application and voice states make behavior inspectable.

---

## 19. Why keep security logic outside the LLM?

Sensitive operations should not depend on a probabilistic language model deciding whether a user is authorized.

The shutdown-verification path:

- performs deterministic matching
- keeps private recognition out of normal history
- does not send the secret transcript to the LLM

That is the correct trust boundary.

---

## 20. Why is barge-in disabled in the stable host path?

Because “microphone is physically available while TTS is playing” is not the same as “barge-in is production ready.”

Reliable interruption requires validation of:

- AEC
- double-talk
- self-echo rejection
- false interruption rate
- playback cancellation timing

The stable path prioritizes correctness over claiming a half-tuned feature.

---

## 21. Why not commit model weights / TensorRT plans?

Because Git should contain the project, not machine-generated runtime state.

Excluded artifacts include:

- ONNX/GGUF/Safetensors weights
- virtual environments
- Hugging Face caches
- TensorRT plans
- model blobs
- ESP-IDF build output
- large RAG datasets

Instead, the repository keeps:

- source
- dependency locks
- upstream commit hashes
- setup notes
- architecture documentation

---

## 22. What would I change for a production release?

High-priority work:

1. finish deployment automation
2. normalize stale configuration/comments
3. make WSL TTS service reproducibly installable
4. validate barge-in and AEC quantitatively
5. add reconnect/watchdog behavior for every external service
6. add automated latency regression tests
7. add secure provisioning for embedded production hardware
8. make resource-aware model/backend selection
9. package the host runtime cleanly
10. add reproducible model-download manifests/checksums

---

## 23. Core interview takeaway

The strongest technical point in SARA is not any single model.

It is the **system decomposition and integration** required to make multiple local AI components, operating systems and an embedded device behave like one assistant.
