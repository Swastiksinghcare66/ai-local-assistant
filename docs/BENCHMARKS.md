# SARA / SIA — Benchmarks and Performance Methodology

## 1. Rule: measured values only

For an interview repository, a missing number is better than an invented one.

SARA already has explicit latency instrumentation, so benchmark claims should come from measured runs.

---

## 2. Built-in turn timing

`VoiceTiming` tracks:

```text
speech_end
capture_end
stt_start
stt_end
llm_start
llm_first_text
llm_end
first_tts_text
first_audio
playback_end
```

Derived metrics:

| Metric | Meaning |
|---|---|
| `endpoint_ms` | speech end → capture completion |
| `stt_ms` | STT start → transcript |
| `llm_ttft_ms` | LLM request → first generated text |
| `chunk_wait_ms` | first LLM text → first speakable TTS chunk |
| `tts_ttfa_ms` | first TTS text → first returned audio |
| `speech_to_audio_ms` | user speech end → first audio response |

That last metric is the strongest user-perceived latency metric.

---

## 3. Current validated configuration

### LLM

```text
runtime       Ollama
model         gemma3:4b
context       4096
max tokens    160
temperature   0.7
keep alive    30m
GPU layers    4
streaming     enabled
```

### Conversation STT

```text
Faster-Whisper small
CPU
int8
8 threads
1 worker
beam size 1
```

### Wake STT

```text
sherpa-onnx Nemo Parakeet TDT 0.6B v2 int8
16 kHz
8 threads
```

### Audio output

```text
CosyVoice client PCM     24 kHz mono int16
ESP32 hardware PCM       16 kHz mono int16
playback slices          20 ms
```

---

## 4. Previously validated WSL backend observations

The tested CosyVoice service reported:

| Metric | Observed value |
|---|---:|
| Health | HTTP 200 |
| Persistent WebSocket | enabled |
| Output rate | 24 kHz |
| Cached profiles | 5 |
| Warm-up runs | 4 |
| Last warm-up TTFA | ~1053.3 ms |
| Server flow steps at validation | 5 |

Do not generalize these values to other machines.

---

## 5. Flow-step benchmark caveat

There is currently a source-level mismatch:

```text
Windows VoicePipeline FLOW_STEPS = 3
WSL controller ALLOWED_STEPS     = {5,6,8,10}
validated server current steps   = 5
```

Normalize this configuration before publishing a formal latency-vs-quality flow-step chart.

---

## 6. Recommended benchmark matrix

Run at least 10 warmed turns per configuration.

### A. STT

Measure:

- English wake-only
- English command
- Hinglish command
- Hindi command
- quiet room
- playback/echo condition

Record:

```text
WER/CER where ground truth is available
transcription latency
fallback rate
```

### B. LLM

Measure:

```text
TTFT
tokens/s
total generation time
CPU
GPU
VRAM
```

Compare only one variable at a time:

- model
- GPU-layer count
- context size
- max tokens

### C. TTS

Measure:

```text
request → first PCM
total synthesis duration
real-time factor
VRAM
first-audio after host resampling
```

### D. End to end

Measure:

```text
end of user speech → first audible SARA audio
```

This is the metric most users feel.

---

## 7. Recommended benchmark table

Use this in the repository after running tests:

| Run | STT ms | LLM TTFT ms | Chunk wait ms | TTS TTFA ms | Speech→audio ms |
|---:|---:|---:|---:|---:|---:|
| 1 |  |  |  |  |  |
| 2 |  |  |  |  |  |
| 3 |  |  |  |  |  |
| 4 |  |  |  |  |  |
| 5 |  |  |  |  |  |
| 6 |  |  |  |  |  |
| 7 |  |  |  |  |  |
| 8 |  |  |  |  |  |
| 9 |  |  |  |  |  |
| 10 |  |  |  |  |  |

Then report:

```text
mean
median
p95
min
max
```

---

## 8. Resource benchmark

Record alongside every serious latency test:

```text
CPU model
GPU model
driver
RAM
VRAM
Windows version
WSL distro
Python version
Ollama version
model tag/hash where available
CosyVoice commit
Matcha commit
```

Without environment metadata, latency numbers are hard to reproduce.

---

## 9. Benchmark failure modes

Avoid these mistakes:

- timing cold start and calling it steady-state latency
- mixing network/web requests into local-inference benchmarks
- changing multiple settings at once
- reporting one run
- ignoring failed/fallback STT turns
- excluding long-tail latency
- publishing “GPU utilization” without sampling method
- treating backend TTFA as full voice-to-voice latency

---

## 10. Interview framing

A strong answer is:

> “I instrumented each boundary separately—endpointing, STT, LLM TTFT, chunk formation, TTS TTFA and full speech-to-audio—because optimizing one model in isolation can make the overall assistant slower.”

That demonstrates systems-level performance thinking.
