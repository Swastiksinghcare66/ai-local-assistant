from pathlib import Path

from bs4 import BeautifulSoup
from libzim.reader import Archive
from libzim.search import Query, Searcher


ZIM_PATH = Path(
    r"D:\Alexa_lite\Alexa_lite\rag_lab\data"
    r"\wikipedia_en_simple_all_nopic_2026-05.zim"
)


def clean_html(raw: bytes) -> str:
    soup = BeautifulSoup(
        raw.decode("utf-8", errors="ignore"),
        "html.parser",
    )

    for tag in soup(
        ["script", "style", "noscript"]
    ):
        tag.decompose()

    return " ".join(
        soup.stripped_strings
    )


print("Opening ZIM...")
archive = Archive(str(ZIM_PATH))
searcher = Searcher(archive)
print("ZIM OPENED")


def test_query(query_text: str, limit: int = 3):
    query = Query().set_query(query_text)

    search = searcher.search(query)
    count = search.getEstimatedMatches()

    print()
    print("=" * 78)
    print("QUERY:", query_text)
    print("ESTIMATED MATCHES:", count)

    if count <= 0:
        print("NO RESULTS")
        return

    paths = list(
        search.getResults(
            0,
            min(limit, count),
        )
    )

    for i, path in enumerate(
        paths,
        start=1,
    ):
        try:
            entry = archive.get_entry_by_path(
                path
            )

            item = entry.get_item()

            raw = bytes(
                item.content
            )

            text = clean_html(raw)

            print()
            print(f"[{i}] TITLE:", entry.title)
            print("PATH:", path)
            print("TEXT:")
            print(text[:1200])

        except Exception as exc:
            print(
                f"[{i}] ERROR:",
                type(exc).__name__,
                str(exc),
            )


tests = [
    "Albert Einstein",
    "India",
    "photosynthesis",
    "artificial intelligence",
    "CUDA",
]

for q in tests:
    test_query(q)
