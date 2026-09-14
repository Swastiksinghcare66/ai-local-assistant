from __future__ import annotations

from datetime import datetime
from pathlib import Path
import random
import winsound

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STARTUP_AUDIO_DIR = PROJECT_ROOT / "assets" / "audio" / "startup"

def startup_period(now: datetime | None = None) -> str:
    now = now or datetime.now()
    h = now.hour
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "night"

_AUDIO_FILES = {
    "morning": "sara_morning_sunrise.wav",
    "afternoon": "sara_afternoon_drive.wav",
    "evening": "sara_evening_neon.wav",
    "night": "sara_night_legend.wav",
}

_GREETING_POOLS = {
    "morning": (
        "Good morning, {user}! Sara's online. Let's make today count.",
        "Morning, {user}! I'm online, energized, and ready. Let's go!",
        "Good morning, {user}! Systems are alive. Let's build something brilliant.",
    ),
    "afternoon": (
        "Good afternoon, {user}! Sara's online. Let's keep the momentum going.",
        "Afternoon, {user}! I'm online, energized, and ready for what's next.",
        "Good afternoon, {user}! Everything's ready. Let's make this session count.",
    ),
    "evening": (
        "Good evening, {user}! Sara's online. Let's make this session count.",
        "Evening, {user}! I'm online and ready. Let's create something brilliant.",
        "Good evening, {user}! Systems are glowing. Let's make something great.",
    ),
    "night": (
        "Late-night mode, {user}! Sara's online. Let's make something legendary.",
        "Still building, {user}? Perfect. I'm online. Let's make the night count.",
        "Night mode, {user}! Sara's awake, energized, and ready. Let's go!",
    ),
}

def build_dynamic_startup_greeting(user_name: str, now: datetime | None = None) -> str:
    period = startup_period(now)
    user = str(user_name or "").strip() or "there"
    return random.choice(_GREETING_POOLS[period]).format(user=user)

def startup_audio_path(now: datetime | None = None) -> Path:
    return STARTUP_AUDIO_DIR / _AUDIO_FILES[startup_period(now)]

def play_startup_soundscape(now: datetime | None = None) -> Path | None:
    path = startup_audio_path(now)
    if not path.exists():
        print(f"[STARTUP AUDIO] missing: {path}")
        return None
    try:
        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
        print(f"[STARTUP AUDIO] {path.name}")
        return path
    except Exception as exc:
        print(f"[STARTUP AUDIO] failed: {type(exc).__name__}: {exc}")
        return None
