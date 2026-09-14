import time
from typing import Generator, Optional

from ollama import Client

from app.config import (
    LLM_HOST,
    LLM_MODEL,
    LLM_CONTEXT_SIZE,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    LLM_KEEP_ALIVE,
    LLM_THINK,
    SHOW_INFERENCE_TIME,
)
from app.error_handler import ErrorHandler


# ============================================================
# CLIENT
# ============================================================

client = Client(host=LLM_HOST)
error_handler = ErrorHandler()


# ============================================================
# CPU / GPU OFFLOAD CONFIGURATION
# ============================================================

# ------------------------------------------------------------
# HYBRID QWEN MODE
# ------------------------------------------------------------
#
# 0:
#     CPU only
#
# Higher values:
#     More transformer layers are offloaded to NVIDIA GPU.
#
# Full GPU residency was causing severe VRAM pressure when
# CosyVoice + vLLM + TensorRT were also resident.
#
# We start with 8 GPU layers as a conservative A/B test.
#
# Goal:
#     Keep Qwen reasonably fast
#     while leaving enough VRAM for CosyVoice.
# ------------------------------------------------------------

LLM_NUM_GPU = 4


# ============================================================
# MODEL SELECTION
# ============================================================

def get_model_name(
    model_name: Optional[str] = None,
) -> str:

    return model_name or LLM_MODEL


# ============================================================
# GENERATION OPTIONS
# ============================================================

def get_generation_options() -> dict:

    return {
        "num_ctx":
            LLM_CONTEXT_SIZE,

        "num_predict":
            LLM_MAX_TOKENS,

        "temperature":
            LLM_TEMPERATURE,

        "top_k":
            20,

        "top_p":
            0.9,

        "repeat_penalty":
            1.05,

        # Hybrid CPU/GPU Qwen offload.
        "num_gpu":
            LLM_NUM_GPU,
    }


# ============================================================
# NORMAL CHAT
# ============================================================

def chat(
    messages: list,
    model_name: Optional[str] = None,
):

    model = get_model_name(
        model_name
    )

    start = time.perf_counter()

    try:

        response = client.chat(
            model=model,

            messages=messages,

            think=LLM_THINK,

            stream=False,

            keep_alive=LLM_KEEP_ALIVE,

            options=get_generation_options(),
        )

    except Exception as exc:

        error_handler.handle(
            exc
        )

        return (
            "I'm unable to answer right now.",
            0.0,
        )


    inference_time = (
        time.perf_counter()
        - start
    )


    response_text = (
        response[
            "message"
        ][
            "content"
        ].strip()
    )


    if SHOW_INFERENCE_TIME:

        print(
            f"\n[LLM] "
            f"model={model} "
            f"gpu_layers={LLM_NUM_GPU} "
            f"total={inference_time:.3f}s"
        )


    return (
        response_text,
        inference_time,
    )


# ============================================================
# STREAMING CHAT
# ============================================================

def chat_stream(
    messages: list,
    model_name: Optional[str] = None,
) -> Generator[
    str,
    None,
    None,
]:

    model = get_model_name(
        model_name
    )


    start = (
        time.perf_counter()
    )


    first_token_time = None

    total_characters = 0

    chunks_received = 0


    try:

        stream = client.chat(
            model=model,

            messages=messages,

            think=LLM_THINK,

            stream=True,

            keep_alive=LLM_KEEP_ALIVE,

            options=get_generation_options(),
        )


        for chunk in stream:

            message = (
                chunk.get(
                    "message",
                    {},
                )
            )


            content = (
                message.get(
                    "content",
                    "",
                )
            )


            if not content:

                continue


            now = (
                time.perf_counter()
            )


            # =================================================
            # FIRST TOKEN
            # =================================================

            if first_token_time is None:

                first_token_time = now


                if SHOW_INFERENCE_TIME:

                    ttft = (
                        first_token_time
                        - start
                    )


                    print(
                        f"\n[LLM] "
                        f"model={model} "
                        f"gpu_layers={LLM_NUM_GPU} "
                        f"TTFT={ttft:.3f}s"
                    )


            chunks_received += 1

            total_characters += (
                len(content)
            )


            yield content


    except Exception as exc:

        error_handler.handle(
            exc
        )


        yield (
            "I'm unable to answer right now."
        )

        return


    # ========================================================
    # FINAL STATISTICS
    # ========================================================

    end = (
        time.perf_counter()
    )


    total_time = (
        end
        - start
    )


    if first_token_time is None:

        ttft = total_time

        generation_time = 0.0

    else:

        ttft = (
            first_token_time
            - start
        )

        generation_time = (
            end
            - first_token_time
        )


    if generation_time > 0:

        characters_per_second = (
            total_characters
            / generation_time
        )

    else:

        characters_per_second = 0.0


    if SHOW_INFERENCE_TIME:

        print()

        print(
            f"[LLM] complete "
            f"model={model} "
            f"gpu_layers={LLM_NUM_GPU} "
            f"TTFT={ttft:.3f}s "
            f"total={total_time:.3f}s "
            f"chunks={chunks_received} "
            f"chars/s="
            f"{characters_per_second:.1f}"
        )


# ============================================================
# FULL WARMUP
# ============================================================

def warmup(
    model_name: Optional[str] = None,
):

    """
    Initialize Qwen using the same hybrid CPU/GPU offload
    configuration used by real conversation requests.

    Two short warmup passes are used because the first request
    may initialize model memory, GPU buffers, context state,
    and Ollama runtime structures.

    IMPORTANT:
    The same LLM_NUM_GPU value is used here so warmup cannot
    accidentally load Qwen using a different CPU/GPU layout.
    """

    model = get_model_name(
        model_name
    )


    messages = [
        {
            "role":
                "system",

            "content":
                (
                    "You are a fast conversational "
                    "voice assistant. "
                    "Reply briefly."
                ),
        },

        {
            "role":
                "user",

            "content":
                "Hi",
        },
    ]


    print(
        f"[LLM] warming "
        f"{model} "
        f"with {LLM_NUM_GPU} GPU layers..."
    )


    overall_start = (
        time.perf_counter()
    )


    for pass_number in range(
        1,
        3,
    ):

        start = (
            time.perf_counter()
        )


        try:

            client.chat(
                model=model,

                messages=messages,

                think=False,

                stream=False,

                keep_alive=
                    LLM_KEEP_ALIVE,

                options={
                    "num_ctx":
                        LLM_CONTEXT_SIZE,

                    "num_predict":
                        4,

                    "temperature":
                        0.0,

                    # Same hybrid layout as real inference.
                    "num_gpu":
                        LLM_NUM_GPU,
                },
            )


        except Exception as exc:

            error_handler.handle(
                exc
            )

            return False


        elapsed = (
            time.perf_counter()
            - start
        )


        if SHOW_INFERENCE_TIME:

            print(
                f"[LLM] "
                f"warmup pass={pass_number} "
                f"gpu_layers={LLM_NUM_GPU} "
                f"time={elapsed:.3f}s"
            )


    total = (
        time.perf_counter()
        - overall_start
    )


    print(
        f"[LLM] ready "
        f"model={model} "
        f"gpu_layers={LLM_NUM_GPU} "
        f"startup={total:.3f}s"
    )


    return True


# ============================================================
# QUICK TEST
# ============================================================

def test_model(
    prompt: str = (
        "Say hello in one short sentence."
    ),
    model_name: Optional[str] = None,
):

    model = get_model_name(
        model_name
    )


    print()

    print("=" * 60)

    print(
        f"MODEL: {model}"
    )

    print(
        f"GPU LAYERS: {LLM_NUM_GPU}"
    )

    print("=" * 60)


    messages = [
        {
            "role":
                "system",

            "content":
                (
                    "You are a fast conversational "
                    "voice assistant. "
                    "Reply briefly and directly. "
                    "Do not describe hidden reasoning "
                    "or internal thoughts."
                ),
        },

        {
            "role":
                "user",

            "content":
                prompt,
        },
    ]


    response_parts = []


    for text in chat_stream(
        messages=messages,
        model_name=model,
    ):

        print(
            text,
            end="",
            flush=True,
        )


        response_parts.append(
            text
        )


    print()

    print("=" * 60)


    return "".join(
        response_parts
    )

