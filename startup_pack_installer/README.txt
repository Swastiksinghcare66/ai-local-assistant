SARA SIGNATURE STARTUP PACK
===========================

Original sound design for Sara.

Tracks:
- sara_morning_sunrise.wav
- sara_afternoon_drive.wav
- sara_evening_neon.wav
- sara_night_legend.wav
- sara_startup_pack_preview.wav

Behavior:
- 05:00-11:59 -> morning
- 12:00-16:59 -> afternoon
- 17:00-21:59 -> evening
- 22:00-04:59 -> night
- Music starts first.
- Sara enters ~0.68 s later.
- Startup voice style is fixed to energetic_friendly.
- Normal adaptive voice behavior resumes after startup.
- Old three-line INIT / READY / GREETING sequence is replaced by one dynamic greeting.

Install:
1. Put install_sara_startup_experience.py, startup_experience.py, and the four time WAV files together.
2. From D:\Alexa_lite\Alexa_lite run:
   python <path>\install_sara_startup_experience.py
3. Verify:
   python -m py_compile .\app\main.py
   python -m py_compile .\app\audio\startup_experience.py
4. Run:
   python -m app.main
