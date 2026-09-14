from __future__ import annotations

import json
import urllib.request

from local_wikipedia import (
    LocalWikipedia,
    ZIM_PATH,
)


OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "alexa-qwen3-1.7b-dpo:v1"

wiki = LocalWikipedia(ZIM_PATH)


def build_context(
    question: str,
    max_chars: int = 1800,
):
    result = wiki.search(
        question,
        limit=2,
    )

    if not result["grounded"]:
        return result, ""

    blocks = []

    for article in result["results"]:
        text = article["text"]

        blocks.append(
            f"ARTICLE: {article['title']}\n"
            f"{text}"
        )

    context = "\n\n".join(blocks)

    return (
        result,
        context[:max_chars],
    )


def ask_rag(question: str):
    result, context = build_context(
        question
    )

    print()
    print("=" * 80)
    print("QUESTION:", question)
    print("SUBJECT:", result["subject"])
    print("GROUNDED:", result["grounded"])
    print("METHOD:", result["method"])

    if not context:
        print()
        print(
            "ANSWER: I don't have enough "
            "reliable information about that "
            "in my local knowledge base."
        )
        return

    print()
    print("CONTEXT:")
    print(context[:1000])
    print()

    payload = {
        "model": MODEL,

        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Sara, an offline conversational voice assistant. "
                    "Use only the supplied local knowledge for factual claims. "
                    "Answer the user's actual question, not everything in the article. "
                    "Synthesize the information in your own words. "
                    "Do not copy long passages from the source. "
                    "For simple factual questions, answer in 1 or 2 short sentences. "
                    "For explanation questions, use at most 3 short sentences unless "
                    "the user explicitly asks for detail. "
                    "Start directly with the answer. "
                    "Do not add unnecessary history, statistics, dates, or side facts. "
                    "If the local knowledge is insufficient, say that clearly. "
                    "Never invent missing information. "
                    "Do not mention Wikipedia, RAG, retrieval, source, or context "
                    "unless the user explicitly asks."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"LOCAL KNOWLEDGE:\n{context}\n\n"
                    f"USER QUESTION:\n{question}"
                ),
            },
        ],

        "stream": False,
        "think": False,

        "options": {
            "temperature": 0.25,
            "num_ctx": 4096,
            "num_predict": 100,
        },
    }

    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode(
            "utf-8"
        ),
        headers={
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=120,
    ) as response:
        data = json.loads(
            response.read().decode(
                "utf-8"
            )
        )

    answer = (
        data.get("message", {})
        .get("content", "")
        .strip()
    )

    print("ANSWER:", answer)


tests = [
    "What is photosynthesis?",
    "Who was Albert Einstein?",
    "What is NVIDIA?",
    "Tell me about India",
    "What is CUDA?",
]

for q in tests:
    ask_rag(q)
