from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path.cwd()
MAIN = ROOT / "app" / "main.py"
MODULE_DST = ROOT / "app" / "audio" / "startup_experience.py"
AUDIO_DST = ROOT / "assets" / "audio" / "startup"

HERE = Path(__file__).resolve().parent

if not MAIN.exists():
    raise SystemExit(
        "Run this installer from the Sara project root, e.g. D:\\Alexa_lite\\Alexa_lite"
    )

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = MAIN.with_name(f"main.py.before_startup_experience_{stamp}.bak")
shutil.copy2(MAIN, backup)
print(f"[BACKUP] {backup}")

AUDIO_DST.mkdir(parents=True, exist_ok=True)
MODULE_DST.parent.mkdir(parents=True, exist_ok=True)

for name in (
    "sara_morning_sunrise.wav",
    "sara_afternoon_drive.wav",
    "sara_evening_neon.wav",
    "sara_night_legend.wav",
):
    src = HERE / name
    if not src.exists():
        raise SystemExit(f"Missing audio file beside installer: {src}")
    shutil.copy2(src, AUDIO_DST / name)
    print(f"[AUDIO] {AUDIO_DST / name}")

module_src = HERE / "startup_experience.py"
if not module_src.exists():
    raise SystemExit(f"Missing runtime module beside installer: {module_src}")
shutil.copy2(module_src, MODULE_DST)
print(f"[MODULE] {MODULE_DST}")

text = MAIN.read_text(encoding="utf-8-sig")

start_marker = "        if STARTUP_SPEECH_ENABLED:\\n"
end_marker = "        mode = DEFAULT_ASSISTANT_MODE\\n"

start = text.find(start_marker)
end = text.find(end_marker, start if start >= 0 else 0)

if start < 0 or end < 0:
    raise SystemExit(
        "Assets were installed, but main.py was NOT patched because the expected "
        "startup markers were not found. The backup remains available."
    )

replacement = """        # ========================================================
        # SARA SIGNATURE STARTUP EXPERIENCE
        # Time-aware music + one excited greeting.
        # Replaces the old INIT / READY / GREETING three-line sequence.
        # ========================================================
        if STARTUP_GREETING_ENABLED:
            from app.audio.startup_experience import (
                build_dynamic_startup_greeting,
                play_startup_soundscape,
            )

            greeting = build_dynamic_startup_greeting(
                USER_NAME
            )

            print()
            print(
                f"[STARTUP EXPERIENCE] {greeting}"
            )

            play_startup_soundscape()

            # Let the signature motif establish itself before Sara enters.
            await asyncio.sleep(0.68)

            # Startup is deliberately energetic.
            # Normal adaptive mood resumes immediately after startup.
            await pipeline.speak_text(
                greeting,
                style="energetic_friendly",
                wait_for_playback=True,
            )

"""

new_text = text[:start] + replacement + text[end:]
MAIN.write_text(new_text, encoding="utf-8")

print("[PATCH] app\\main.py updated")
print("[STYLE] startup = energetic_friendly")
print("[GREETING] time-aware morning / afternoon / evening / night")
print("[DONE] Sara Signature Startup Experience installed")
