import asyncio
import json
import time
import uuid as uuid_lib
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import torch
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from cosyvoice.cli.cosyvoice import AutoModel

from sara_voice_styles import (
    DEFAULT_STYLE,
    available_styles,
    get_style_instruction,
)

from services.cosyvoice_flow_step_controller import (
    CosyVoiceFlowStepController,
)


# ============================================================
# VERSION
# ============================================================

SERVER_VERSION = "1.8-persistent"


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent

MODEL_DIR = (
    BASE_DIR
    / "pretrained_models"
    / "Fun-CosyVoice3-0.5B"
)

PROMPT_WAV = (
    BASE_DIR
    / "asset"
    / "zero_shot_prompt.wav"
)


# ============================================================
# SERVER
# ============================================================

HOST = "0.0.0.0"
PORT = 5051


# ============================================================
# STREAM SETTINGS
# ============================================================

BASE_TOKEN_HOP_LEN = 25
TOKEN_MAX_MULTIPLIER = 4
STREAM_SCALE_FACTOR = 2


# ============================================================
# FLOW SETTINGS
# ============================================================

DEFAULT_FLOW_STEPS = 5


# ============================================================
# AUTOMATIC WARM-UP
# ============================================================

WARMUP_MIN_RUNS = 2
WARMUP_MAX_RUNS = 4

WARMUP_TARGET_TTFA_MS = 1200.0

WARMUP_TEXT = (
    "Hello. I'm Sara, your AI assistant, "
    "and I'm ready to help."
)

WARMUP_STYLE = "warm_conversational"


# ============================================================
# STYLE CACHE
# ============================================================

STYLE_SPK_IDS = {
    style: f"sara_{style}"
    for style in available_styles()
}


# ============================================================
# GLOBAL STATE
# ============================================================

model = None

model_lock = asyncio.Lock()

service_ready = False

warmup_results = []


flow_step_controller = (
    CosyVoiceFlowStepController(
        default_steps=DEFAULT_FLOW_STEPS
    )
)


# ============================================================
# AUDIO HELPERS
# ============================================================

def tensor_to_pcm16(
    audio_tensor: torch.Tensor,
) -> bytes:

    audio = (
        audio_tensor
        .detach()
        .cpu()
        .float()
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
    ).astype("<i2")

    return pcm.tobytes()


def next_chunk(generator):

    try:
        return True, next(generator)

    except StopIteration:
        return False, None


# ============================================================
# STREAM STATE RESET
# ============================================================

def reset_cosyvoice_stream_state():

    core_model = model.model

    previous_hop = (
        core_model.token_hop_len
    )

    core_model.token_hop_len = (
        BASE_TOKEN_HOP_LEN
    )

    core_model.token_max_hop_len = (
        BASE_TOKEN_HOP_LEN
        * TOKEN_MAX_MULTIPLIER
    )

    core_model.stream_scale_factor = (
        STREAM_SCALE_FACTOR
    )

    return {
        "previous_hop":
            previous_hop,

        "token_hop_len":
            core_model.token_hop_len,

        "token_max_hop_len":
            core_model.token_max_hop_len,

        "stream_scale_factor":
            core_model.stream_scale_factor,
    }


# ============================================================
# STYLE CACHE
# ============================================================

def build_sara_style_cache():

    print()
    print("=" * 72)
    print("BUILDING SARA STYLE CACHE")
    print("=" * 72)

    cached = []

    for style in available_styles():

        spk_id = (
            STYLE_SPK_IDS[style]
        )

        instruction = (
            get_style_instruction(style)
        )

        print()
        print(
            f"Caching style : {style}"
        )

        print(
            f"Speaker ID    : {spk_id}"
        )

        start = (
            time.perf_counter()
        )

        model.add_zero_shot_spk(
            instruction,
            str(PROMPT_WAV),
            spk_id,
        )

        elapsed = (
            time.perf_counter()
            - start
        )

        cached.append(
            spk_id
        )

        print(
            f"Cache time    : "
            f"{elapsed:.3f} sec"
        )

    print()
    print("-" * 72)

    print(
        f"Cached profiles : "
        f"{len(cached)}"
    )

    print("=" * 72)
    print()

    return cached


# ============================================================
# HIDDEN WARM-UP
# ============================================================

def run_single_warmup(
    run_number: int,
):

    flow_step_controller.set_steps(
        DEFAULT_FLOW_STEPS
    )

    reset_cosyvoice_stream_state()

    instruction = (
        get_style_instruction(
            WARMUP_STYLE
        )
    )

    cached_spk_id = (
        STYLE_SPK_IDS[
            WARMUP_STYLE
        ]
    )

    start = (
        time.perf_counter()
    )

    first_chunk_time = None

    chunk_count = 0
    total_samples = 0

    generator = (
        model.inference_instruct2(
            WARMUP_TEXT,

            instruction,

            str(PROMPT_WAV),

            zero_shot_spk_id=
                cached_spk_id,

            stream=True,

            text_frontend=True,
        )
    )

    for result in generator:

        now = (
            time.perf_counter()
        )

        if first_chunk_time is None:

            first_chunk_time = (
                now
            )

        speech = (
            result["tts_speech"]
        )

        chunk_count += 1

        total_samples += (
            speech.shape[-1]
        )

    if torch.cuda.is_available():

        torch.cuda.synchronize()

    end = (
        time.perf_counter()
    )

    if first_chunk_time is None:

        ttfa_ms = None

    else:

        ttfa_ms = (
            first_chunk_time
            - start
        ) * 1000.0

    total_seconds = (
        end
        - start
    )

    audio_seconds = (
        total_samples
        / model.sample_rate

        if model.sample_rate

        else 0.0
    )

    rtf = (
        total_seconds
        / audio_seconds

        if audio_seconds > 0

        else None
    )

    result = {
        "run":
            run_number,

        "ttfa_ms":
            ttfa_ms,

        "total_seconds":
            total_seconds,

        "audio_seconds":
            audio_seconds,

        "rtf":
            rtf,

        "chunks":
            chunk_count,
    }

    print()

    print(
        f"Warm-up {run_number}: "
        f"TTFA="
        f"{ttfa_ms:.1f} ms | "
        f"Total="
        f"{total_seconds:.2f}s | "
        f"RTF="
        f"{rtf:.3f}"
    )

    return result


def run_hidden_warmups():

    print()
    print("=" * 72)
    print("AUTOMATIC TTS WARM-UP")
    print("=" * 72)

    print(
        f"Flow steps : "
        f"{DEFAULT_FLOW_STEPS}"
    )

    print(
        f"Target TTFA: "
        f"< {WARMUP_TARGET_TTFA_MS:.0f} ms"
    )

    results = []

    for run_number in range(
        1,
        WARMUP_MAX_RUNS + 1,
    ):

        result = (
            run_single_warmup(
                run_number
            )
        )

        results.append(
            result
        )

        enough_runs = (
            run_number
            >= WARMUP_MIN_RUNS
        )

        target_reached = (
            result["ttfa_ms"]
            is not None

            and

            result["ttfa_ms"]
            <= WARMUP_TARGET_TTFA_MS
        )

        if (
            enough_runs
            and target_reached
        ):

            print()
            print(
                "Warm-up target reached."
            )

            break

    print()
    print("-" * 72)

    if results:

        final = (
            results[-1]
        )

        print(
            f"Warm-up runs     : "
            f"{len(results)}"
        )

        print(
            f"Final warm TTFA  : "
            f"{final['ttfa_ms']:.1f} ms"
        )

        if (
            final["ttfa_ms"]
            is not None

            and

            final["ttfa_ms"]
            > WARMUP_TARGET_TTFA_MS
        ):

            print(
                "WARNING: target TTFA "
                "was not reached."
            )

    print("=" * 72)
    print()

    return results


# ============================================================
# FASTAPI LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app):

    global model
    global service_ready
    global warmup_results

    service_ready = False

    print()
    print("=" * 72)

    print(
        f"SARA COSYVOICE SERVER "
        f"{SERVER_VERSION}"
    )

    print("=" * 72)

    print(
        "Model :",
        MODEL_DIR,
    )

    print(
        "Voice :",
        PROMPT_WAV,
    )

    print(
        "Style :",
        DEFAULT_STYLE,
    )

    print(
        "Flow  :",
        DEFAULT_FLOW_STEPS,
        "steps",
    )

    print()

    print(
        "Loading CosyVoice3 + "
        "vLLM + TensorRT..."
    )


    # --------------------------------------------------------
    # MODEL LOAD
    # --------------------------------------------------------

    load_start = (
        time.perf_counter()
    )

    model = AutoModel(
        model_dir=str(MODEL_DIR),

        load_trt=True,

        load_vllm=True,

        fp16=False,
    )

    load_elapsed = (
        time.perf_counter()
        - load_start
    )


    # --------------------------------------------------------
    # BASE STREAM CONFIG
    # --------------------------------------------------------

    reset_cosyvoice_stream_state()


    # --------------------------------------------------------
    # RUNTIME FLOW CONTROLLER
    # --------------------------------------------------------

    flow_step_controller.install(
        model.model.flow.decoder
    )

    print()
    print(
        "Runtime Flow-step "
        "controller installed."
    )


    # --------------------------------------------------------
    # STYLE CACHE
    # --------------------------------------------------------

    cache_start = (
        time.perf_counter()
    )

    cached_profiles = (
        build_sara_style_cache()
    )

    cache_elapsed = (
        time.perf_counter()
        - cache_start
    )


    # --------------------------------------------------------
    # HIDDEN WARM-UP
    # --------------------------------------------------------

    warmup_results = (
        run_hidden_warmups()
    )


    # --------------------------------------------------------
    # RESTORE PRODUCTION DEFAULTS
    # --------------------------------------------------------

    flow_step_controller.set_steps(
        DEFAULT_FLOW_STEPS
    )

    reset_cosyvoice_stream_state()


    # --------------------------------------------------------
    # READY
    # --------------------------------------------------------

    service_ready = True

    final_warmup = (
        warmup_results[-1]

        if warmup_results

        else None
    )

    print()
    print("=" * 72)
    print("SARA COSYVOICE PRODUCTION READY")
    print("=" * 72)

    print(
        f"Version          : "
        f"{SERVER_VERSION}"
    )

    print(
        f"Model load       : "
        f"{load_elapsed:.2f} sec"
    )

    print(
        f"Style cache      : "
        f"{cache_elapsed:.2f} sec"
    )

    print(
        f"Sample rate      : "
        f"{model.sample_rate} Hz"
    )

    print(
        f"Default style    : "
        f"{DEFAULT_STYLE}"
    )

    print(
        f"Cached profiles  : "
        f"{len(cached_profiles)}"
    )

    print(
        f"Default Flow     : "
        f"{DEFAULT_FLOW_STEPS} steps"
    )

    print(
        f"Allowed Flow     : "
        f"{sorted(flow_step_controller.ALLOWED_STEPS)}"
    )

    print(
        f"Warm-up runs     : "
        f"{len(warmup_results)}"
    )

    if final_warmup is not None:

        print(
            f"Warm TTFA        : "
            f"{final_warmup['ttfa_ms']:.1f} ms"
        )

    print(
        f"Token hop        : "
        f"{model.model.token_hop_len}"
    )

    print(
        f"Token max hop    : "
        f"{model.model.token_max_hop_len}"
    )

    print(
        "Persistent WS    : True"
    )

    print(
        f"Port             : "
        f"{PORT}"
    )

    print("=" * 72)
    print()

    yield

    service_ready = False

    print()
    print(
        "Sara CosyVoice server "
        "shutting down."
    )


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title=
        "Sara CosyVoice Production Server",

    version=
        SERVER_VERSION,

    lifespan=
        lifespan,
)


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "service":
            "Sara CosyVoice",

        "version":
            SERVER_VERSION,

        "ready":
            service_ready,

        "persistent_websocket":
            True,

        "default_style":
            DEFAULT_STYLE,

        "default_flow_steps":
            DEFAULT_FLOW_STEPS,

        "allowed_flow_steps":
            sorted(
                flow_step_controller.ALLOWED_STEPS
            ),
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    final_warmup = (
        warmup_results[-1]

        if warmup_results

        else None
    )

    return {
        "ready":
            service_ready,

        "version":
            SERVER_VERSION,

        "persistent_websocket":
            True,

        "sample_rate":
            (
                model.sample_rate

                if model is not None

                else None
            ),

        "default_style":
            DEFAULT_STYLE,

        "cached_profiles":
            len(STYLE_SPK_IDS),

        "default_flow_steps":
            DEFAULT_FLOW_STEPS,

        "current_flow_steps":
            flow_step_controller.get_steps(),

        "allowed_flow_steps":
            sorted(
                flow_step_controller.ALLOWED_STEPS
            ),

        "warmup_runs":
            len(warmup_results),

        "last_warmup_ttfa_ms":
            (
                round(
                    final_warmup[
                        "ttfa_ms"
                    ],
                    1,
                )

                if (
                    final_warmup
                    is not None

                    and

                    final_warmup[
                        "ttfa_ms"
                    ]
                    is not None
                )

                else None
            ),

        "token_hop_len":
            (
                model.model.token_hop_len

                if model is not None

                else None
            ),

        "token_max_hop_len":
            (
                model.model.token_max_hop_len

                if model is not None

                else None
            ),
    }


# ============================================================
# ONE TTS REQUEST
# ============================================================

async def process_tts_request(
    websocket: WebSocket,
    data: dict,
    connection_number: int,
):

    text = str(
        data.get(
            "text",
            "",
        )
    ).strip()

    style = str(
        data.get(
            "style",
            DEFAULT_STYLE,
        )
    ).strip()

    mode = str(
        data.get(
            "mode",
            "stream",
        )
    ).strip().lower()

    requested_flow_steps = (
        data.get(
            "flow_steps",
            DEFAULT_FLOW_STEPS,
        )
    )

    request_id = str(
        data.get(
            "request_id",
            "",
        )
    ).strip()

    if not request_id:

        request_id = (
            uuid_lib.uuid4().hex[:12]
        )


    # --------------------------------------------------------
    # VALIDATE
    # --------------------------------------------------------

    if not text:

        await websocket.send_json(
            {
                "type":
                    "error",

                "request_id":
                    request_id,

                "message":
                    "Text is empty.",
            }
        )

        return


    if style not in available_styles():

        style = (
            DEFAULT_STYLE
        )


    if mode not in (
        "stream",
        "full",
    ):

        mode = "stream"


    use_stream = (
        mode == "stream"
    )


    instruction = (
        get_style_instruction(
            style
        )
    )


    cached_spk_id = (
        STYLE_SPK_IDS[
            style
        ]
    )


    # --------------------------------------------------------
    # TIMING
    # --------------------------------------------------------

    request_start = (
        time.perf_counter()
    )

    first_model_chunk_time = None
    first_pcm_ready_time = None
    first_send_complete_time = None

    packet_count = 0
    total_samples = 0

    total_model_wait = 0.0
    total_send_time = 0.0


    # --------------------------------------------------------
    # MODEL ACCESS
    # --------------------------------------------------------

    async with model_lock:

        active_flow_steps = (
            flow_step_controller.set_steps(
                requested_flow_steps
            )
        )

        stream_state = (
            reset_cosyvoice_stream_state()
        )


        print()
        print("=" * 72)
        print("SARA TTS REQUEST")
        print("=" * 72)

        print(
            f"Connection : "
            f"{connection_number}"
        )

        print(
            f"Request ID : "
            f"{request_id}"
        )

        print(
            f"Text       : "
            f"{text}"
        )

        print(
            f"Style      : "
            f"{style}"
        )

        print(
            f"Flow steps : "
            f"{active_flow_steps}"
        )

        print(
            f"Token hop  : "
            f"{stream_state['token_hop_len']}"
        )

        print("=" * 72)


        # ----------------------------------------------------
        # START MESSAGE
        # ----------------------------------------------------

        await websocket.send_json(
            {
                "type":
                    "start",

                "request_id":
                    request_id,

                "sample_rate":
                    model.sample_rate,

                "channels":
                    1,

                "sample_format":
                    "pcm_s16le",

                "style":
                    style,

                "mode":
                    mode,

                "flow_steps":
                    active_flow_steps,
            }
        )


        # ----------------------------------------------------
        # SYNTHESIS
        # ----------------------------------------------------

        generator = (
            model.inference_instruct2(
                text,

                instruction,

                str(PROMPT_WAV),

                zero_shot_spk_id=
                    cached_spk_id,

                stream=
                    use_stream,

                text_frontend=True,
            )
        )


        while True:

            wait_start = (
                time.perf_counter()
            )

            has_chunk, result = (
                await asyncio.to_thread(
                    next_chunk,
                    generator,
                )
            )

            wait_end = (
                time.perf_counter()
            )

            total_model_wait += (
                wait_end
                - wait_start
            )


            if not has_chunk:

                break


            if (
                first_model_chunk_time
                is None
            ):

                first_model_chunk_time = (
                    wait_end
                )


            speech = (
                result["tts_speech"]
            )


            # ------------------------------------------------
            # PCM CONVERSION
            # ------------------------------------------------

            pcm = (
                tensor_to_pcm16(
                    speech
                )
            )


            if (
                first_pcm_ready_time
                is None
            ):

                first_pcm_ready_time = (
                    time.perf_counter()
                )


            # ------------------------------------------------
            # AUDIO STATS
            # ------------------------------------------------

            samples = (
                speech.shape[-1]
            )

            packet_count += 1

            total_samples += (
                samples
            )


            packet_audio_seconds = (
                samples
                / model.sample_rate
            )


            # ------------------------------------------------
            # SEND PCM
            # ------------------------------------------------

            send_start = (
                time.perf_counter()
            )

            await websocket.send_bytes(
                pcm
            )

            send_end = (
                time.perf_counter()
            )

            total_send_time += (
                send_end
                - send_start
            )


            if (
                first_send_complete_time
                is None
            ):

                first_send_complete_time = (
                    send_end
                )


            print(
                f"Packet {packet_count} | "
                f"audio="
                f"{packet_audio_seconds:.2f}s | "
                f"flow="
                f"{active_flow_steps} | "
                f"hop="
                f"{model.model.token_hop_len}"
            )


    # --------------------------------------------------------
    # FINAL TIMINGS
    # --------------------------------------------------------

    end_time = (
        time.perf_counter()
    )


    total_time = (
        end_time
        - request_start
    )


    audio_duration = (
        total_samples
        / model.sample_rate

        if model.sample_rate

        else 0.0
    )


    def elapsed_ms(timestamp):

        if timestamp is None:

            return None

        return (
            timestamp
            - request_start
        ) * 1000.0


    model_ttfa_ms = (
        elapsed_ms(
            first_model_chunk_time
        )
    )

    pcm_ready_ms = (
        elapsed_ms(
            first_pcm_ready_time
        )
    )

    wire_ttfa_ms = (
        elapsed_ms(
            first_send_complete_time
        )
    )


    rtf = (
        total_time
        / audio_duration

        if audio_duration > 0

        else None
    )


    # --------------------------------------------------------
    # END MESSAGE
    # --------------------------------------------------------

    await websocket.send_json(
        {
            "type":
                "end",

            "request_id":
                request_id,

            "version":
                SERVER_VERSION,

            "style":
                style,

            "mode":
                mode,

            "flow_steps":
                active_flow_steps,

            "packets":
                packet_count,

            "audio_duration":
                round(
                    audio_duration,
                    3,
                ),

            "generation_time":
                round(
                    total_time,
                    3,
                ),

            "rtf":
                (
                    round(
                        rtf,
                        3,
                    )

                    if rtf is not None

                    else None
                ),

            "model_ttfa_ms":
                (
                    round(
                        model_ttfa_ms,
                        2,
                    )

                    if model_ttfa_ms
                    is not None

                    else None
                ),

            "pcm_ready_ms":
                (
                    round(
                        pcm_ready_ms,
                        2,
                    )

                    if pcm_ready_ms
                    is not None

                    else None
                ),

            "wire_ttfa_ms":
                (
                    round(
                        wire_ttfa_ms,
                        2,
                    )

                    if wire_ttfa_ms
                    is not None

                    else None
                ),

            "model_wait_seconds":
                round(
                    total_model_wait,
                    3,
                ),

            "websocket_send_seconds":
                round(
                    total_send_time,
                    3,
                ),
        }
    )


    print()
    print(
        f"TTFA       : "
        f"{model_ttfa_ms:.1f} ms"
    )

    print(
        f"Wire TTFA  : "
        f"{wire_ttfa_ms:.1f} ms"
    )

    print(
        f"Total      : "
        f"{total_time:.3f} s"
    )

    print(
        f"RTF        : "
        f"{rtf:.3f}"
    )

    print(
        f"Flow       : "
        f"{active_flow_steps} steps"
    )

    print("=" * 72)


# ============================================================
# PERSISTENT WEBSOCKET
# ============================================================

@app.websocket("/tts")
async def tts_socket(
    websocket: WebSocket,
):

    await websocket.accept()

    connection_id = (
        uuid_lib.uuid4().hex[:8]
    )

    request_number = 0


    print()
    print(
        f"TTS WebSocket connected: "
        f"{connection_id}"
    )


    try:

        if not service_ready:

            await websocket.send_json(
                {
                    "type":
                        "error",

                    "message":
                        "CosyVoice is still warming up.",
                }
            )

            await websocket.close()

            return


        # ====================================================
        # KEEP CONNECTION OPEN
        # ====================================================

        while True:

            raw_request = (
                await websocket.receive_text()
            )


            # ------------------------------------------------
            # PARSE JSON
            # ------------------------------------------------

            try:

                data = json.loads(
                    raw_request
                )

            except json.JSONDecodeError:

                await websocket.send_json(
                    {
                        "type":
                            "error",

                        "message":
                            "Invalid JSON request.",
                    }
                )

                continue


            # ------------------------------------------------
            # CONTROL MESSAGE
            # ------------------------------------------------

            message_type = str(
                data.get(
                    "type",
                    "tts",
                )
            ).strip().lower()


            if message_type == "ping":

                await websocket.send_json(
                    {
                        "type":
                            "pong",

                        "server":
                            SERVER_VERSION,
                    }
                )

                continue


            if message_type in (
                "close",
                "disconnect",
            ):

                await websocket.send_json(
                    {
                        "type":
                            "closing",
                    }
                )

                break


            if message_type != "tts":

                await websocket.send_json(
                    {
                        "type":
                            "error",

                        "message":
                            (
                                "Unsupported message "
                                f"type: {message_type}"
                            ),
                    }
                )

                continue


            # ------------------------------------------------
            # PROCESS TTS
            # ------------------------------------------------

            request_number += 1


            try:

                await process_tts_request(
                    websocket=
                        websocket,

                    data=
                        data,

                    connection_number=
                        request_number,
                )


            except WebSocketDisconnect:

                raise


            except Exception as exc:

                print(
                    "TTS REQUEST ERROR:",
                    repr(exc),
                )


                try:

                    await websocket.send_json(
                        {
                            "type":
                                "error",

                            "request_id":
                                data.get(
                                    "request_id"
                                ),

                            "message":
                                str(exc),
                        }
                    )

                except Exception:

                    raise


    except WebSocketDisconnect:

        pass


    except Exception as exc:

        print(
            "WEBSOCKET ERROR:",
            repr(exc),
        )


    finally:

        print(
            f"TTS WebSocket disconnected: "
            f"{connection_id}"
        )


        try:

            await websocket.close()

        except Exception:

            pass


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,

        host=HOST,

        port=PORT,

        workers=1,

        log_level="info",
    )
