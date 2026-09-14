from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WebSearchResult:
    ok: bool
    query: str
    results: list[dict[str, Any]]
    error: str | None = None


def search_web(
    query: str,
    max_results: int = 6,
) -> WebSearchResult:
    """
    Uses DDGS as the first local web-search provider.

    Install:
        pip install -U ddgs

    This function does not ask Qwen to fabricate web results.
    If retrieval fails, it returns ok=False.
    """

    query = str(query or "").strip()

    if not query:
        return WebSearchResult(
            ok=False,
            query=query,
            results=[],
            error="Empty search query.",
        )

    try:
        from ddgs import DDGS
    except Exception:
        return WebSearchResult(
            ok=False,
            query=query,
            results=[],
            error=(
                "Web search provider is not installed. "
                "Install it with: pip install -U ddgs"
            ),
        )

    try:
        raw = DDGS(timeout=8).text(
            query,
            region="in-en",
            safesearch="moderate",
            max_results=max_results,
            backend="auto",
        )

        cleaned = []

        for item in raw or []:
            if not isinstance(item, dict):
                continue

            title = str(item.get("title") or "").strip()
            url = str(
                item.get("href")
                or item.get("url")
                or ""
            ).strip()
            body = str(
                item.get("body")
                or item.get("snippet")
                or ""
            ).strip()

            if not (title or body or url):
                continue

            cleaned.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": body,
                }
            )

        if not cleaned:
            return WebSearchResult(
                ok=False,
                query=query,
                results=[],
                error="No useful web results were returned.",
            )

        return WebSearchResult(
            ok=True,
            query=query,
            results=cleaned,
        )

    except Exception as exc:
        return WebSearchResult(
            ok=False,
            query=query,
            results=[],
            error=str(exc),
        )
