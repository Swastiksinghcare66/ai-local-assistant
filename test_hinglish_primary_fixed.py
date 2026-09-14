from app.audio.language_router import LanguageRouter

router = LanguageRouter(
    default_language="hinglish",
    follow_user_language=False,
)

tests = [
    ("what time is it", "hinglish", "preferred_default"),
    ("GPU temperature kitna hai", "hinglish", "preferred_default"),
    ("Explain RAG", "hinglish", "preferred_default"),
    ("Explain RAG in English", "english", "explicit_english_request"),
    ("English me explain karo", "english", "explicit_english_request"),
    ("Reply in English please", "english", "explicit_english_request"),
    ("हिंदी में बताओ", "hindi", "explicit_hindi_request"),
    ("Explain it in Hindi", "hindi", "explicit_hindi_request"),
    ("Hinglish me samjhao", "hinglish", "explicit_hinglish_request"),
]

for text, expected_language, expected_reason in tests:
    got = router.observe_user_text(text)
    print(
        repr(text),
        "->",
        got.language,
        "|",
        got.reason,
    )
    assert got.language == expected_language, (
        text,
        got,
        expected_language,
    )
    assert got.reason == expected_reason, (
        text,
        got,
        expected_reason,
    )

print()
print("HINGLISH PRIMARY + EXPLICIT OVERRIDE POLICY: PASS")
