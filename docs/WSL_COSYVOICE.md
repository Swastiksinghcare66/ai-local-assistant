# SARA / SIA — WSL2 CosyVoice Backend

## 1. Purpose

SARA keeps its main orchestration on Windows but runs the high-quality CosyVoice speech backend inside WSL2/Ubuntu.

The split exists because the TTS stack is Linux-oriented and includes GPU/runtime dependencies that are cleaner to isolate from the Windows host environment.

---

## 2. Host-side client

Windows implementation:

```text
app/audio/cosyvoice_client.py
```

The persistent client defaults to:

```text
ws://127.0.0.1:5051/tts
```

Key property:

> A single WebSocket connection can carry multiple sequential synthesis requests.

This is important for streaming LLM → TTS operation.

---

## 3. Project-specific WSL export

The public repository keeps the project-specific overlay instead of copying an entire third-party checkout.

Expected structure:

```text
wsl_cosyvoice/
├── COSYVOICE_COMMIT.txt
├── MATCHA_COMMIT.txt
├── requirements_wsl_lock.txt
├── sara_voice_styles.py
├── asset/
│   └── zero_shot_prompt.wav
└── services/
    ├── cosyvoice_server_prod.py
    └── cosyvoice_flow_step_controller.py
```

The commit-pin files preserve the upstream revisions used by the working environment.

---

## 4. Current public-repo caveat

At the time this documentation pack was generated, GitHub contained the flow-step controller but **not** `wsl_cosyvoice/services/cosyvoice_server_prod.py`.

Cause: a broad `.gitignore` filename rule also matched the nested canonical server source.

Before using the repository as a reproducibility reference, re-add that local source file and change the ignore rule so only the obsolete root-level duplicate is ignored.

This is repository hygiene, not a runtime failure—the validated local WSL server was already tested separately.

---

## 5. Flow-step controller

The exported controller can override the CosyVoice decoder `n_timesteps` parameter at runtime.

Allowed values in the exported controller are:

```text
5
6
8
10
```

This allows latency/quality experiments without rewriting upstream CosyVoice source for every request.

---

## 6. Important flow-step consistency note

The current Windows `VoicePipeline` source defines:

```text
FLOW_STEPS = 3
```

while the exported WSL controller only accepts:

```text
{5, 6, 8, 10}
```

The previously validated WSL health response reported a server-side current/default value of 5.

Therefore:

> Do not publish “3 flow steps” as a validated end-to-end benchmark until the client/server configuration is normalized.

This is exactly the type of integration mismatch that system-level testing should catch.

---

## 7. Audio contract

CosyVoice client-side playback expects:

```text
PCM16
mono
24 kHz
```

The Windows hardware playback path then converts it to:

```text
PCM16
mono
16 kHz
```

for the embedded SIA protocol.

---

## 8. Voice style

The persistent client default is:

```text
warm_conversational
```

The WSL export also includes:

```text
sara_voice_styles.py
```

so voice behavior is treated as an explicit configuration layer.

---

## 9. Why persistent serving?

A per-query model lifecycle would look like:

```text
request
 ↓
load heavy model/runtime
 ↓
synthesize
 ↓
destroy
```

That is unacceptable for an interactive assistant.

SARA instead uses:

```text
start backend once
 ↓
warm model/runtime
 ↓
keep service resident
 ↓
synthesize repeated requests
```

---

## 10. Validated backend health

The working WSL backend was previously validated with a health response reporting:

```text
ready                  true
version                1.8-persistent
persistent_websocket   true
sample_rate            24000
default_style          warm_conversational
cached_profiles        5
default_flow_steps     5
current_flow_steps     5
allowed_flow_steps     5,6,8,10
warmup_runs            4
last_warmup_ttfa_ms    ~1053.3
```

These are environment-specific observations, not universal performance guarantees.

---

## 11. Reproducibility strategy

Do commit:

- custom service source
- custom flow controller
- voice-style source
- exact upstream commits
- dependency lock
- small project-owned reference asset where licensing permits

Do not commit:

- `.venv_vllm`
- downloaded pretrained model weights
- generated TensorRT plans
- caches
- temporary vLLM directories

---

## 12. Development environment vs production installer

The validated local runtime and the unfinished production packaging effort should be treated separately.

The working project proves the architecture.

A production installer still needs to solve:

- WSL bootstrap
- dependency installation
- model download
- GPU capability checks
- vLLM/TensorRT build ordering
- low-VRAM failure recovery
- service startup
- version/checksum validation

Do not claim one-click deployment until those steps are fully validated.
