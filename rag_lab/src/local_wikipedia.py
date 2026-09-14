from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path

from bs4 import BeautifulSoup
from libzim.reader import Archive
from libzim.search import Query, Searcher


ZIM_PATH = Path(
    r"D:\Alexa_lite\Alexa_lite\rag_lab\data"
    r"\wikipedia_en_simple_all_nopic_2026-05.zim"
)


class LocalWikipedia:
    def __init__(self, zim_path: Path):
        self.archive = Archive(str(zim_path))
        self.searcher = Searcher(self.archive)

    @staticmethod
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
            q = re.sub(
                pattern,
                "",
                q,
                flags=re.I,
            )

        q = q.strip(" ?.!,:;")
        return q

    @staticmethod
    def _path_candidates(subject: str):
        base = re.sub(r"\s+", "_", subject.strip())

        candidates = [
            base,
            base[:1].upper() + base[1:],
        ]

        # remove duplicates but preserve order
        return list(dict.fromkeys(candidates))

    @staticmethod
    def _clean_html(raw: bytes) -> str:
        soup = BeautifulSoup(
            raw.decode(
                "utf-8",
                errors="ignore",
            ),
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
            value = " ".join(
                p.stripped_strings
            )

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
            return "\n\n".join(
                paragraphs
            )

        # fallback
        text = " ".join(
            soup.stripped_strings
        )

        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

    def _read_path(self, path: str):
        try:
            entry = self.archive.get_entry_by_path(path)
            item = entry.get_item()

            text = self._clean_html(
                bytes(item.content)
            )

            return {
                "title": entry.title,
                "path": path,
                "text": text,
            }

        except Exception:
            return None

    def _exact_lookup(self, subject: str):
        for path in self._path_candidates(subject):
            result = self._read_path(path)

            if result is not None:
                return result

        return None

    @staticmethod
    def _score_title(
        subject: str,
        title: str,
        rank: int,
    ) -> float:
        s = subject.casefold().strip()
        t = title.casefold().strip()

        score = 0.0

        if t == s:
            score += 100

        similarity = SequenceMatcher(
            None,
            s,
            t,
        ).ratio()

        score += similarity * 50

        subject_words = set(
            re.findall(r"\w+", s)
        )

        title_words = set(
            re.findall(r"\w+", t)
        )

        if subject_words:
            overlap = (
                len(subject_words & title_words)
                / len(subject_words)
            )

            score += overlap * 40

        if t.startswith(s):
            score += 20

        bad_terms = [
            "disambiguation",
            "list of",
            "album",
            "song",
            "film",
        ]

        for term in bad_terms:
            if term in t and term not in s:
                score -= 35

        score += max(
            0,
            10 - rank,
        )

        return score

    def search(
        self,
        question: str,
        limit: int = 3,
    ):
        subject = self._clean_question(
            question
        )

        # ----------------------------------------
        # 1. Exact article path first
        # ----------------------------------------

        exact = self._exact_lookup(subject)

        if exact is not None:
            return {
                "query": question,
                "subject": subject,
                "grounded": True,
                "method": "exact",
                "results": [exact],
            }

        # ----------------------------------------
        # 2. Full-text search fallback
        # ----------------------------------------

        result = self.searcher.search(
            Query().set_query(subject)
        )

        estimated = (
            result.getEstimatedMatches()
        )

        if estimated <= 0:
            return {
                "query": question,
                "subject": subject,
                "grounded": False,
                "method": "none",
                "results": [],
            }

        paths = list(
            result.getResults(
                0,
                min(20, estimated),
            )
        )

        candidates = []

        for rank, path in enumerate(paths):
            article = self._read_path(path)

            if article is None:
                continue

            score = self._score_title(
                subject,
                article["title"],
                rank,
            )

            article["score"] = score
            candidates.append(article)

        candidates.sort(
            key=lambda x: x["score"],
            reverse=True,
        )

        # Important:
        # reject weak unrelated search results.
        candidates = [
            x
            for x in candidates
            if x["score"] >= 55
        ]

        return {
            "query": question,
            "subject": subject,
            "grounded": bool(candidates),
            "method": "search",
            "results": candidates[:limit],
        }


if __name__ == "__main__":
    wiki = LocalWikipedia(ZIM_PATH)

    tests = [
        "Who was Albert Einstein?",
        "Tell me about India",
        "What is photosynthesis?",
        "What is artificial intelligence?",
        "What is NVIDIA?",
        "What is CUDA?",
    ]

    for question in tests:
        print()
        print("=" * 80)
        print("QUESTION:", question)

        result = wiki.search(question)

        print("SUBJECT:", result["subject"])
        print("GROUNDED:", result["grounded"])
        print("METHOD:", result["method"])

        if not result["results"]:
            print("NO RELIABLE LOCAL ARTICLE")
            continue

        for i, article in enumerate(
            result["results"],
            start=1,
        ):
            print()
            print(
                f"[{i}]",
                article["title"],
            )

            if "score" in article:
                print(
                    "SCORE:",
                    round(
                        article["score"],
                        2,
                    ),
                )

            print(
                article["text"][:900]
            )
