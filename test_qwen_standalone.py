import time

from app.llm_client import (
    warmup,
    chat_stream,
    LLM_NUM_GPU,
)

MODEL = "qwen3:1.7b"

print("=" * 72)
print("SARA - QWEN STANDALONE STREAM TEST")
print("=" * 72)

print(f"Model      : {MODEL}")
print(f"GPU layers : {LLM_NUM_GPU}")
print()

print("[1] WARMUP")
start = time.perf_counter()

result = warmup(MODEL)

warmup_time = time.perf_counter() - start

print(f"Warmup result : {result}")
print(f"Warmup time   : {warmup_time:.3f} s")
print()

print("[2] STREAMING TEST")

messages = [
    {
        "role": "system",
        "content": (
            "You are Sara, a concise conversational AI assistant. "
            "Answer naturally in one or two short sentences."
        ),
    },
    {
        "role": "user",
        "content": (
            "Introduce yourself briefly and tell me whether "
            "the software test appears to be working."
        ),
    },
]

start = time.perf_counter()
first_token_time = None
parts = []

print("Sara: ", end="", flush=True)

for chunk in chat_stream(
    messages,
    model_name=MODEL,
):
    if first_token_time is None:
        first_token_time = time.perf_counter()

    parts.append(chunk)
    print(chunk, end="", flush=True)

end = time.perf_counter()

print()
print()

if first_token_time is not None:
    ttft_ms = (
        first_token_time - start
    ) * 1000.0
else:
    ttft_ms = None

total_seconds = end - start
response = "".join(parts)

print("=" * 72)
print("RESULT")
print("=" * 72)
print(f"TTFT           : {ttft_ms} ms")
print(f"Total time     : {total_seconds:.3f} s")
print(f"Response chars : {len(response)}")
print(f"Response empty : {not bool(response.strip())}")
print("=" * 72)
