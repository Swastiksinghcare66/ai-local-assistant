from app.audio.language_router import LanguageRouter
from app.audio.hinglish_normalizer import HinglishNormalizer

router = LanguageRouter(default_language="hinglish", follow_user_language=True)
normalizer = HinglishNormalizer()

tests = [
    "GPU ka temperature kya hai?",
    "Mujhe RAG simple way me samjhao",
    "Explain backpropagation in English",
    "हिंदी में बताओ कि RAG क्या है",
    "okay",
]

for text in tests:
    d = router.observe_user_text(text)
    print(f"INPUT: {text}")
    print(f" -> {d.language} | {d.confidence:.2f} | {d.reason}")

print()
example = "हाँ, GPU का temperature अभी थोड़ा high है. CUDA model memory check करते हैं."
print("NORMALIZER INPUT :", example)
print("PIPER TEXT       :", normalizer.to_piper_text(example))
