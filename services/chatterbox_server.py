"""
Chatterbox Turbo TTS Service
----------------------------

Runs inside:

    .venv_chatterbox

Alexa Lite communicates with this service over localhost.

Endpoints:

    GET  /health
    POST /synthesize

The Chatterbox model is loaded ONCE at startup and stays
resident on the RTX GPU.
"""

import io
import time
import wave

import numpy as np
import torch
import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from chatterbox.tts_turbo import ChatterboxTurboTTS


# ============================================================
# SETTINGS
# ============================================================

HOST = "127.0.0.1"
PORT = 5050

DEVICE = "cuda"


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Alexa Lite Chatterbox Turbo",
    version="1.0",
)


# ============================================================
# REQUEST
# ============================================================

class SynthesisRequest(BaseModel):

    text: str


# ============================================================
# GLOBAL MODEL
# ============================================================

model = None


# ============================================================
# WAV ENCODER
# ============================================================

def waveform_to_wav_bytes(
    waveform: torch.Tensor,
    sample_rate: int,
) -> bytes:
    """
    Convert Chatterbox float waveform tensor to 16-bit mono WAV.
    """

    audio = (
        waveform
        .detach()
        .cpu()
        .squeeze()
        .numpy()
    )

    audio = np.clip(
        audio,
        -1.0,
        1.0,
    )

    pcm = (
        audio * 32767.0
    ).astype(
        np.int16
    )

    buffer = io.BytesIO()

    with wave.open(
        buffer,
        "wb",
    ) as wav_file:

        wav_file.setnchannels(1)

        wav_file.setsampwidth(2)

        wav_file.setframerate(
            sample_rate
        )

        wav_file.writeframes(
            pcm.tobytes()
        )

    return buffer.getvalue()


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup():

    global model

    print()
    print("=" * 70)
    print("CHATTERBOX TURBO SERVICE")
    print("=" * 70)

    print(
        f"CUDA available : "
        f"{torch.cuda.is_available()}"
    )

    if not torch.cuda.is_available():

        raise RuntimeError(
            "CUDA is not available."
        )

    print(
        f"GPU            : "
        f"{torch.cuda.get_device_name(0)}"
    )

    print()
    print(
        "[TTS] Loading Chatterbox Turbo..."
    )

    start = time.perf_counter()

    model = (
        ChatterboxTurboTTS
        .from_pretrained(
            device=DEVICE,
        )
    )

    torch.cuda.synchronize()

    elapsed = (
        time.perf_counter()
        - start
    )

    print(
        f"[TTS] Loaded in "
        f"{elapsed:.2f}s"
    )


    # --------------------------------------------------------
    # WARMUP
    # --------------------------------------------------------

    print(
        "[TTS] Warming..."
    )

    start = time.perf_counter()

    _ = model.generate(
        "Hello."
    )

    torch.cuda.synchronize()

    elapsed = (
        time.perf_counter()
        - start
    )

    print(
        f"[TTS] Warmup complete "
        f"{elapsed:.2f}s"
    )

    print()
    print(
        "[TTS] READY"
    )

    print("=" * 70)
    print()


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "model": "chatterbox-turbo",
        "device": DEVICE,
        "sample_rate": (
            model.sr
            if model is not None
            else None
        ),
    }


# ============================================================
# SYNTHESIZE
# ============================================================

@app.post("/synthesize")
def synthesize(
    request: SynthesisRequest,
):

    if model is None:

        raise HTTPException(
            status_code=503,
            detail="TTS model is not loaded.",
        )

    text = request.text.strip()

    if not text:

        raise HTTPException(
            status_code=400,
            detail="Text cannot be empty.",
        )


    print()
    print(
        f"[TTS REQUEST] "
        f"{text}"
    )


    start = time.perf_counter()


    try:

        waveform = model.generate(
            text
        )

        torch.cuda.synchronize()


    except Exception as exc:

        print(
            f"[TTS ERROR] {exc}"
        )

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


    generation_time = (
        time.perf_counter()
        - start
    )


    wav_bytes = waveform_to_wav_bytes(
        waveform,
        model.sr,
    )


    audio_duration = (
        waveform.shape[-1]
        / model.sr
    )


    print(
        f"[TTS] generation="
        f"{generation_time * 1000:.1f}ms "
        f"audio={audio_duration:.2f}s"
    )


    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={
            "X-TTS-Generation-MS": (
                f"{generation_time * 1000:.1f}"
            ),
            "X-Audio-Sample-Rate": (
                str(model.sr)
            ),
        },
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
    )