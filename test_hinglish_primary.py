from app.config import PREFERRED_CONVERSATION_LANGUAGE, FOLLOW_USER_LANGUAGE
from app.audio.language_router import LanguageRouter

assert PREFERRED_CONVERSATION_LANGUAGE == "hinglish"
assert FOLLOW_USER_LANGUAGE is False

r = LanguageRouter(default_language=PREFERRED_CONVERSATION_LANGUAGE, follow_user_language=FOLLOW_USER_LANGUAGE)

cases = [
    ("what time is it", "hinglish"),
    ("GPU temperature kitna hai", "hinglish"),
    ("Explain RAG", "hinglish"),
    ("Explain RAG in English", "english"),
    ("हिंदी में बताओ", "hindi"),
]

for text, expected in cases:
    got = r.observe_user_text(text)
    print(f"{text!r} -> {got.language} | {got.reason}")
    assert got.language == expected, (text, got, expected)

print("HINGLISH PRIMARY POLICY: PASS")
