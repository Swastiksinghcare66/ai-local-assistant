# SARA / SIA  
## Cross-Device Local AI Voice Assistant

SARA (Software AI Runtime Assistant) / SIA is a **cross-device, local AI voice assistant system** built using:

- **ESP32-S3 hardware front-end**
- **Windows host runtime**
- **Local STT + local LLM**
- **WSL2-based CosyVoice TTS backend**
- **GPU acceleration using vLLM and TensorRT**

The project was designed as an **end-to-end real-time voice assistant system**, not just a chatbot.  
It integrates hardware, speech processing, AI inference, state management, and system orchestration into one complete architecture.

---

## Project Objective

The goal of this project is to build a **practical local voice assistant** that can:

- listen through a hardware audio front-end
- detect wake-word / activation phrase
- perform speech-to-text locally
- generate responses using a local language model
- synthesize natural speech using a high-quality local TTS pipeline
- interact across **ESP32-S3 + Windows + WSL2**
- support real-time assistant behavior with standby, active, and sleep flow

---

## Key Features

- **Cross-device architecture**
  - ESP32-S3 handles hardware-level interaction
  - Windows handles orchestration and logic
  - WSL2 runs GPU-accelerated CosyVoice TTS

- **Local AI pipeline**
  - Local STT
  - Local LLM through Ollama
  - Local TTS

- **Voice assistant behavior**
  - wake-word / activation flow
  - continuous conversation mode
  - sleep / standby mode
  - conversational voice output

- **Hardware integration**
  - ESP32-S3
  - INMP441 I2S microphone
  - MAX98357A I2S DAC / amplifier
  - speaker output
  - relay / GPIO extensibility

- **Advanced TTS backend**
  - CosyVoice3
  - vLLM
  - TensorRT acceleration
  - persistent TTS service

- **Modular software design**
  - app layer
  - hardware abstraction
  - audio pipeline
  - agent / tools layer
  - firmware layer
  - WSL backend integration

---

## High-Level Architecture

```mermaid
flowchart LR
    A[User Voice Input] --> B[ESP32-S3 Audio Front-End]
    B --> C[USB / Serial Communication]
    C --> D[Windows SARA Runtime]

    D --> E[Wake Detection / State Manager]
    E --> F[Speech-to-Text]
    F --> G[Prompt / Context Builder]
    G --> H[Local LLM via Ollama]
    H --> I[Response Text]

    I --> J[CosyVoice Client]
    J --> K[WSL2 CosyVoice Server]
    K --> L[CosyVoice3 + vLLM + TensorRT]
    L --> M[Generated PCM Audio]

    M --> N[Windows Playback / Audio Routing]
    N --> O[ESP32-S3 Output Path]
    O --> P[MAX98357A + Speaker]
