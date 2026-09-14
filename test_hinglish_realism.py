from app.audio.hinglish_normalizer import HinglishNormalizer

n = HinglishNormalizer()

tests = [
    "Haan, GPU ka temperature abhi 72 degrees pe hai. Cooling check karte hain.",
    "CUDA 12.8 model ko GPU pe load karte hain, phir latency check karenge.",
    "RTX 4060 me 8 GB VRAM hai aur inference around 35 ms le raha hai.",
    "Machine learning aur deep learning ka difference simple way me samjhao.",
    "Let's restart the server, phir dekhte hain ki problem fix hui ya nahi.",
]

for t in tests:
    print("INPUT :", t)
    print("PIPER :", n.to_piper_text(t))
    print()
