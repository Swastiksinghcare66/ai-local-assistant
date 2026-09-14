from __future__ import annotations

import json
import re
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

from bs4 import BeautifulSoup
from libzim.reader import Archive
from libzim.search import Query, Searcher


ZIM_PATH = Path(
    r"D:\Alexa_lite\Alexa_lite\rag_lab\data"
    r"\wikipedia_en_simple_all_nopic_2026-05.zim"
)

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL = "alexa-qwen3-1.7b-dpo:v1"

_archive = None
_searcher = None


def _get_wiki():
    global _archive, _searcher

    if _archive is None:
        print("[LOCAL RAG] Opening Wikipedia ZIM...")
        _archive = Archive(str(ZIM_PATH))
        _searcher = Searcher(_archive)
        print("[LOCAL RAG] Wikipedia ready")

    return _archive, _searcher


def _clean_question(question: str) -> str:
    q = question.strip()

    patterns = [
        r"^(what is|what are)\s+",
        r"^(who is|who was|who were)\s+",
        r"^(where is|where was)\s+",
        r"^(tell me about)\s+",
        r"^(explain)\s+",
        r"^(define)\s+",
    ]

    for pattern in patterns:
        q = re.sub(pattern, "", q, flags=re.I)

    return q.strip(" ?.!,:;")


def _clean_html(raw: bytes) -> str:
    soup = BeautifulSoup(
        raw.decode("utf-8", errors="ignore"),
        "html.parser",
    )

    for tag in soup(
        [
            "script",
            "style",
            "noscript",
            "nav",
            "table",
            "figure",
        ]
    ):
        tag.decompose()

    paragraphs = []

    for p in soup.find_all("p"):
        value = " ".join(p.stripped_strings)

        value = re.sub(
            r"\[\s*\d+\s*\]",
            "",
            value,
        )

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

        if len(value) >= 60:
            paragraphs.append(value)

    if paragraphs:
        return "\n\n".join(paragraphs)

    return re.sub(
        r"\s+",
        " ",
        " ".join(soup.stripped_strings),
    ).strip()


def _read_article(path: str):
    archive, _ = _get_wiki()

    try:
        entry = archive.get_entry_by_path(path)
        item = entry.get_item()

        return {
            "title": entry.title,
            "path": path,
            "text": _clean_html(bytes(item.content)),
        }

    except Exception:
        return None


def _exact_lookup(subject: str):
    base = re.sub(
        r"\s+",
        "_",
        subject.strip(),
    )

    paths = list(
        dict.fromkeys(
            [
                base,
                base[:1].upper() + base[1:],
            ]
        )
    )

    for path in paths:
        result = _read_article(path)

        if result:
            return result

    return None


def _title_score(subject: str, title: str, rank: int):
    s = subject.casefold().strip()
    t = title.casefold().strip()

    score = 0.0

    if s == t:
        score += 100

    score += (
        SequenceMatcher(None, s, t).ratio()
        * 50
    )

    subject_words = set(
        re.findall(r"\w+", s)
    )

    title_words = set(
        re.findall(r"\w+", t)
    )

    if subject_words:
        score += (
            len(subject_words & title_words)
            / len(subject_words)
        ) * 40

    if t.startswith(s):
        score += 20

    for bad in [
        "disambiguation",
        "album",
        "song",
        "film",
        "list of",
    ]:
        if bad in t and bad not in s:
            score -= 35

    score += max(0, 10 - rank)

    return score


def retrieve(question: str):
    subject = _clean_question(question)

    exact = _exact_lookup(subject)

    if exact:
        print(
            f"[LOCAL RAG] exact article: "
            f"{exact['title']}"
        )
        return exact

    _, searcher = _get_wiki()

    search = searcher.search(
        Query().set_query(subject)
    )

    count = search.getEstimatedMatches()

    if count <= 0:
        print("[LOCAL RAG] no results")
        return None

    candidates = []

    for rank, path in enumerate(
        list(
            search.getResults(
                0,
                min(20, count),
            )
        )
    ):
        article = _read_article(path)

        if not article:
            continue

        score = _title_score(
            subject,
            article["title"],
            rank,
        )

        if score >= 55:
            article["score"] = score
            candidates.append(article)

    if not candidates:
        print(
            f"[LOCAL RAG] no reliable article "
            f"for: {subject}"
        )
        return None

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    best = candidates[0]

    print(
        f"[LOCAL RAG] search article: "
        f"{best['title']} "
        f"score={best['score']:.1f}"
    )

    return best


def answer_from_local_knowledge(
    question: str,
) -> str | None:

    article = retrieve(question)

    if article is None:
        return None

    # Voice assistant context should stay small.
    context = article["text"][:1800]

    payload = {
        "model": MODEL,

        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Sara, an offline voice assistant. "
                    "Answer only the user's actual question using "
                    "the supplied local factual information. "
                    "Do not add facts that are not supported by it. "
                    "Preserve distinctions and numerical counts exactly; "
                    "do not merge separate categories. "
                    "Synthesize the answer in your own words. ""For normal factual questions, keep the complete answer under 45 words. ""Do not enumerate lists, neighbours, products, dates, or side facts unless ""the user specifically asks for them. "
                    "For a basic factual question use 1 or 2 short sentences. "
                    "Use at most 3 sentences unless the user asks for detail. "
                    "Start directly with the answer. "
                    "Do not mention Wikipedia, retrieval, RAG, context, "
                    "or local database."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"LOCAL FACTS:\n{context}\n\n"
                    f"QUESTION:\n{question}"
                ),
            },
        ],

        "stream": False,
        "think": False,

        "options": {
            "temperature": 0.2,
            "num_ctx": 4096,
            "num_predict": 70,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=60,
        ) as response:
            data = json.loads(
                response.read().decode("utf-8")
            )

        answer = (
            data.get("message", {})
            .get("content", "")
            .strip()
        )

        if not answer:
            return None

        print(
            f"[LOCAL RAG] answer generated "
            f"({len(answer)} chars)"
        )

        return answer

    except Exception as exc:
        print(
            "[LOCAL RAG] Ollama error:",
            type(exc).__name__,
            exc,
        )
        return None
