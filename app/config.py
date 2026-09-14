"""
Sara - Central Configuration
----------------------------

Assistant identity:
    Sara

Wake word:
    SIA

All major models and runtime behaviour should be selectable here
without rewriting the pipeline.
"""

from pathlib import Path


# ============================================================
# PATHS
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

MODELS_DIR = (
    PROJECT_ROOT
    / "models"
)


# ============================================================
# USER / ASSISTANT
# ============================================================

USER_NAME = "Swastik"

# Conversational/personality identity.
# The assistant may still introduce itself as Sara.
ASSISTANT_NAME = "Sara"


# ============================================================
# PERFORMANCE
# ============================================================

PERFORMANCE_PROFILE = "fast"


# ============================================================
# LLM
# ============================================================

LLM_PROVIDER = "ollama"

LLM_MODEL = "gemma3:4b"

LLM_HOST = "http://127.0.0.1:11434"

LLM_CONTEXT_SIZE = 4096

LLM_MAX_TOKENS = 160

LLM_TEMPERATURE = 0.7

LLM_KEEP_ALIVE = "30m"

LLM_THINK = False

LLM_STREAMING = True

# Use compact runtime instructions for the SFT+DPO conversational model.
USE_TUNED_RUNTIME_PROMPT = True


# ============================================================
# STT
# ============================================================

STT_PROVIDER = "parakeet"

STT_MODEL = (
    "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
)

STT_MODEL_DIR = (
    MODELS_DIR
    / "parakeet"
    / STT_MODEL
)

STT_SAMPLE_RATE = 16000

STT_NUM_THREADS = 8


# ------------------------------------------------------------
# MULTILINGUAL CONVERSATION STT
# ------------------------------------------------------------
# Parakeet remains the wake-word recognizer. Once SIA is awake,
# Faster-Whisper handles Hindi/Hinglish/English conversation locally.
MULTILINGUAL_STT_ENABLED = True
MULTILINGUAL_STT_MODEL = "small"
MULTILINGUAL_STT_MODEL_DIR = (
    MODELS_DIR
    / "faster_whisper"
    / "small"
)
MULTILINGUAL_STT_DEVICE = "cpu"
MULTILINGUAL_STT_COMPUTE_TYPE = "int8"
MULTILINGUAL_STT_CPU_THREADS = 8
MULTILINGUAL_STT_NUM_WORKERS = 1
MULTILINGUAL_STT_BEAM_SIZE = 1
MULTILINGUAL_STT_FALLBACK_TO_PARAKEET = True
MULTILINGUAL_STT_INITIAL_PROMPT = ""


# ============================================================
# TTS / LANGUAGE ROUTING
# ============================================================

# English path stays on the existing high-quality Chatterbox/CosyVoice-style
# backend. Hindi/Hinglish can use Piper locally.
TTS_PROVIDER = "chatterbox_turbo"
TTS_FALLBACK_PROVIDER = "piper"

# Hinglish is the preferred conversational language when the user's language
# is ambiguous. Clear English/Hindi turns can still be followed automatically.
PREFERRED_CONVERSATION_LANGUAGE = "hinglish"
FOLLOW_USER_LANGUAGE = True
HINGLISH_TTS_ENABLED = True


# ------------------------------------------------------------
# CHATTERBOX / ENGLISH PATH
# ------------------------------------------------------------

CHATTERBOX_HOST = "127.0.0.1"
CHATTERBOX_PORT = 5050
CHATTERBOX_TIMEOUT = 30.0


# ------------------------------------------------------------
# PIPER HINDI / HINGLISH PATH
# ------------------------------------------------------------

PIPER_ENABLED = True
PIPER_VOICE_ID = "hi_IN-priyamvada-medium"
PIPER_MODEL_DIR = MODELS_DIR / "piper"
PIPER_MODEL_PATH = PIPER_MODEL_DIR / f"{PIPER_VOICE_ID}.onnx"
PIPER_CONFIG_PATH = PIPER_MODEL_DIR / f"{PIPER_VOICE_ID}.onnx.json"

# Keep Piper on CPU so it does not compete with Qwen/CosyVoice for RTX 4060 VRAM.
PIPER_USE_CUDA = False

# Piper Hindi is sent directly to the firmware native 16 kHz PCM16 path.
# The voice is natively 22.05 kHz; PiperTTSClient resamples exactly once.
PIPER_TARGET_SAMPLE_RATE = 16000

# Direct Piper -> ESP32 playback tuning.
# Piper is resampled once from its native 22.05 kHz voice rate to the
# firmware's native 16 kHz PCM16 contract.  A conservative automatic
# gain stage keeps the Hindi voice audible without exceeding int16 range.
PIPER_PACKET_MS = 20
PIPER_TARGET_PEAK = 24000

# Realism-oriented speech levelling. Unlike the first build, this does not
# normalize every generated chunk independently; gain is smoothed to avoid
# audible pumping.
PIPER_MAX_GAIN = 2.5
PIPER_TARGET_RMS = 4300
PIPER_GAIN_SMOOTHING = 0.82
PIPER_DSP_ENABLED = True
PIPER_PROSODY_ENABLED = True

# Legacy aliases retained for older code that imports these names.
TTS_MODEL = "en_US-lessac-medium"
TTS_VOICE = "default"
TTS_STREAMING = True
TTS_OUTPUT_FORMAT = "pcm"
TTS_FIRST_CHUNK_CHARS = 20
TTS_NORMAL_CHUNK_CHARS = 70
TTS_MAX_CHUNK_CHARS = 110


# ============================================================
# STARTUP SPEECH
# ============================================================

STARTUP_SPEECH_ENABLED = True


# Spoken before model warmup.

STARTUP_INIT_TEXT = (
    "Your AI assistant initiation engaged."
)


# Spoken after model warmup and initialization.

STARTUP_READY_TEXT = (
    "Your AI assistant is ready to help!"
)


# Dynamic PC date/time greeting will be added in runtime.

STARTUP_GREETING_ENABLED = True


# ============================================================
# ASSISTANT MODES
# ============================================================

MODE_STANDBY = "standby"

MODE_ACTIVE = "active"

MODE_OFFLINE = "offline"


# Assistant starts in standby after startup greeting.

DEFAULT_ASSISTANT_MODE = MODE_STANDBY


# ============================================================
# WAKE / IDENTITY
# ============================================================

WAKE_WORD_ENABLED = True

WAKE_WORD_PROVIDER = "parakeet"


# ------------------------------------------------------------
# PRIMARY WAKE WORD
# ------------------------------------------------------------
#
# Spoken wake word:
#
#     SIA
#
# Internally keep this lowercase because WakeListener
# normalizes STT output before matching.
#

WAKE_WORD = "sia"


# ------------------------------------------------------------
# STT WAKE ALIASES
# ------------------------------------------------------------
#
# Parakeet is a general speech recognizer rather than a
# dedicated keyword-spotting model.
#
# Spoken "SIA" may therefore be transcribed differently.
#
# These aliases are treated as equivalent to SIA.
#
# IMPORTANT:
# "sir" can occasionally cause a false wake if somebody
# genuinely begins a sentence with the word "sir".
#
# For the current PC prototype this improves wake reliability.
# A dedicated wake-word model can remove this workaround later.
#

WAKE_WORD_ALIASES = [
    "sia",
    "sya",
    "siah",
    "sir",
    "see ya",

    "siya",
    "seeya",
]


# Maximum region/window used by older wake-listener logic.
# The revised complete-utterance PC listener may not depend
# heavily on this value, but it remains for compatibility.

WAKE_LISTEN_WINDOW_SECONDS = 3.0


# Kept for backward compatibility with older rolling-window
# wake implementations.

WAKE_CHECK_INTERVAL_SECONDS = 0.40


# Minimum RMS activity allowed before considering wake speech.

WAKE_MIN_RMS = 0.005


# ============================================================
# ACTIVE MODE
# ============================================================

# Once SIA wakes Sara, the user does not need to repeat
# the wake word before every request.

ACTIVE_CONTINUOUS_CONVERSATION = True


# Phrases that move the assistant from ACTIVE back to STANDBY.

STANDBY_PHRASES = [
    "standby",
    "go to standby",
    "go standby",
    "standby mode",
    "wait for me",
    "wait here",
    "sleep",
    "go to sleep",
    "you can sleep",
    "you can go to sleep",
    "sleep now",
    "bas ab sleep",
    "ab sleep",
    "standby pe jao",
    "standby par jao",
    "so jao",
    "ab so jao",
    "bas ab so jao",
    "à¤¸à¥‹ à¤œà¤¾à¤“",
    "à¤…à¤¬ à¤¸à¥‹ à¤œà¤¾à¤“",
    "à¤¬à¤¸ à¤…à¤¬ à¤¸à¥‹ à¤œà¤¾à¤“",
    "à¤¸à¥à¤Ÿà¥ˆà¤‚à¤¡à¤¬à¤¾à¤¯",
    "à¤¸à¥à¤Ÿà¥ˆà¤‚à¤¡à¤¬à¤¾à¤¯ à¤ªà¤° à¤œà¤¾à¤“",
]


# Default fallback text. app.main chooses English/Hindi/Hinglish dynamically.
STANDBY_RESPONSE = "Okay, going to standby."


# ============================================================
# OFFLINE / POWER DOWN
# ============================================================

OFFLINE_PHRASES = [
    "go offline",
    "power down",
    "shutdown assistant",
    "exit assistant",
    "exit program",
]


# ============================================================
# TWO-STEP SHUTDOWN VERIFICATION
# ============================================================

SHUTDOWN_VERIFICATION_ENABLED = True


# IMPORTANT:
# Keep the verification code as a STRING.
#
# This allows codes such as:
# "0042"

SHUTDOWN_VERIFICATION_CODE = "4827"


# Maximum failed verification attempts before shutdown
# request is cancelled.

SHUTDOWN_MAX_ATTEMPTS = 3


# Seconds allowed for the user to provide the code.

SHUTDOWN_CODE_TIMEOUT_SECONDS = 10.0


# Spoken challenge.

SHUTDOWN_VERIFY_PROMPT = (
    "Please provide the shutdown verification code."
)


# User may abort shutdown verification.

SHUTDOWN_CANCEL_PHRASES = [
    "cancel",
    "cancel shutdown",
    "cancel power down",
    "never mind",
    "stay active",
    "don't shutdown",
]


SHUTDOWN_CANCEL_RESPONSE = (
    "Shutdown cancelled. I will remain active."
)


SHUTDOWN_FAILURE_RESPONSE = (
    "Verification failed. I will remain active."
)


SHUTDOWN_RETRY_RESPONSE = (
    "That code is incorrect. Please try again."
)


SHUTDOWN_SUCCESS_RESPONSE = (
    "Verification successful. "
    "Going offline. See you later, {user}."
)


# ------------------------------------------------------------
# SECURITY / PRIVACY
# ------------------------------------------------------------

# Verification code should never be passed to the LLM.

SHUTDOWN_CODE_SEND_TO_LLM = False


# Verification code should never enter conversation memory.

SHUTDOWN_CODE_SAVE_TO_MEMORY = False


# Verification code should never be written to chat logs.

SHUTDOWN_CODE_SAVE_TO_LOGS = False


# ============================================================
# HANDS-FREE SPEECH CAPTURE
# ============================================================

VOICE_BLOCK_SECONDS = 0.10


# After a wake-only utterance such as:
#
#     "SIA"
#
# wait this long for the actual command.

VOICE_COMMAND_WAIT_SECONDS = 4.0


# End the command after this much sustained silence.

VOICE_END_SILENCE_SECONDS = 0.90


# Absolute maximum duration of one spoken utterance.

VOICE_MAX_UTTERANCE_SECONDS = 15.0


# Base energy threshold.
#
# Current PC tests showed a noise floor around 0.00001 and
# working speech onset around 0.011-0.015, so 0.010 remains
# a reasonable starting point.

VOICE_MIN_RMS = 0.010


# Dynamic threshold:
#
#     noise_floor Ã— multiplier
#
# but never below VOICE_MIN_RMS.

VOICE_NOISE_MULTIPLIER = 2.8


# ============================================================
# VAD
# ============================================================

VAD_ENABLED = True

VAD_PROVIDER = "energy"


# ============================================================
# BARGE-IN / INTERRUPTION
# ============================================================

# Later AEC integration will allow the microphone to remain
# active while Sara is speaking.

BARGE_IN_ENABLED = True


# Calling SIA while Sara is speaking should eventually
# interrupt playback once barge-in/AEC is integrated.

BARGE_IN_IDENTITY_TRIGGER = True


# ============================================================
# AEC
# ============================================================

# Acoustic Echo Cancellation will later be connected between
# speaker playback and microphone input.

AEC_ENABLED = False

AEC_PROVIDER = "webrtc"

AEC_SAMPLE_RATE = 16000

AEC_STREAM_DELAY_MS = 0


# ============================================================
# MEMORY
# ============================================================

MEMORY_ENABLED_DEFAULT = True

MEMORY_SAVE_WHEN_DISABLED = False

MAX_HISTORY = 10

MAX_CONTEXT_MESSAGES = 10

ALLOW_UNLIMITED_CONTEXT = False


# ============================================================
# FUNCTION CALLING
# ============================================================

FUNCTION_CALLING_ENABLED = True

TOOL_ALLOWLIST_ENABLED = True

ALLOWED_TOOLS = [
    "calculator",
    "get_time",
    "system_status",
]


CONFIRM_SENSITIVE_TOOLS = True

MAX_TOOL_CALLS_PER_TURN = 3


# ============================================================
# AUDIO
# ============================================================

# None = operating-system default microphone.
#
# If a wrong microphone is selected later, set this to the
# sounddevice input-device index.

AUDIO_INPUT_DEVICE = None

AUDIO_OUTPUT_DEVICE = None

MIC_SAMPLE_RATE = 16000

MIC_CHANNELS = 1

PLAYBACK_CHANNELS = 1


# ============================================================
# RESPONSE STYLE
# ============================================================

RESPONSE_STYLE = "concise"

SYSTEM_RESPONSE_HINT = (
    "Respond briefly and directly unless the user explicitly "
    "asks for a detailed explanation."
)


# ============================================================
# DEBUG / TIMING
# ============================================================

DEBUG = True

SHOW_INFERENCE_TIME = True

SHOW_PIPELINE_TIMINGS = True

SAVE_CHAT_LOGS = True


# ============================================================
# BACKWARD-COMPATIBILITY ALIASES
# ============================================================

HOST = LLM_HOST

MODEL_NAME = LLM_MODEL

TEMPERATURE = LLM_TEMPERATURE

MAX_TOKENS = LLM_MAX_TOKENS
