from app.config import STANDBY_PHRASES
from app.main import (
    _detect_local_fast_intent,
    matches_control_phrase,
)
from app.audio.language_router import LanguageRouter
from app.audio.hinglish_normalizer import HinglishNormalizer
from app.pipeline.voice_pipeline import VoicePipeline


def check(label, actual, expected):
    ok = actual == expected
    print(f"{'PASS' if ok else 'FAIL'} | {label}: {actual!r}")
    if not ok:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


print("=" * 68)
print("SIA FINAL CORE TEST")
print("=" * 68)

for phrase in (
    "time kya ho raha hai",
    "abhi time kya hai",
    "kitne baje hain",
    "टाइम क्या हो रहा है",
    "अभी कितने बजे हैं",
    "what time is it",
):
    check(f"time intent / {phrase}", _detect_local_fast_intent(phrase), "time")

for phrase in (
    "sleep",
    "go to sleep",
    "standby pe jao",
    "so jao",
    "सो जाओ",
):
    check(f"sleep / {phrase}", matches_control_phrase(phrase, STANDBY_PHRASES), True)

check(
    "preserve Hindi while stripping wake",
    VoicePipeline._strip_wake_prefix_preserve_unicode("See ya. टाइम क्या हो रहा है?"),
    "टाइम क्या हो रहा है?",
)

router = LanguageRouter(default_language="hinglish")
check(
    "mixed language",
    router.classify("GPU का temperature kya hai?").language,
    "hinglish",
)

normalizer = HinglishNormalizer()
clock_spoken = normalizer.to_piper_text("Abhi time 12:40 PM hai.")
print(f"PASS | clock TTS normalization: {clock_spoken!r}")
if ":" in clock_spoken:
    raise AssertionError("Clock TTS normalization must remove the colon.")

print("=" * 68)
print("ALL FINAL CORE TESTS PASSED")
print("=" * 68)
