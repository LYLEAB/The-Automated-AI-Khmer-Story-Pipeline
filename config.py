"""
config.py — Central configuration for the Automated AI Khmer Story Pipeline.
All tunable constants, model identifiers, and export profiles live here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# PROJECT PATHS
# ─────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent
OUTPUT_DIR = ROOT_DIR / "output"
AUDIO_DIR = OUTPUT_DIR / "audio"
IMAGES_DIR = OUTPUT_DIR / "images"
VIDEO_DIR = OUTPUT_DIR / "video"
METADATA_DIR = OUTPUT_DIR / "metadata"
ASSETS_DIR = ROOT_DIR / "assets"
STATE_FILE = OUTPUT_DIR / "state.json"
RUN_LOG_FILE = OUTPUT_DIR / "run_log.json"

# ─────────────────────────────────────────────
# API KEYS (loaded from .env)
# ─────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "")
STABILITY_API_KEY: str = os.getenv("STABILITY_API_KEY", "")

# ─────────────────────────────────────────────
# AI MODEL IDENTIFIERS
# ─────────────────────────────────────────────
GEMINI_WRITER_MODEL = "gemini-1.5-pro"
GEMINI_PUBLISHER_MODEL = "gemini-2.5-flash"
GEMINI_IMAGEN_MODEL = "imagen-3.0-generate-002"

# ─────────────────────────────────────────────
# TTS CONFIGURATION
# ─────────────────────────────────────────────
# Provider priority: "google_tts" | "elevenlabs" | "gtts"
TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "google_tts")
GOOGLE_TTS_LANGUAGE_CODE = "km-KH"
GOOGLE_TTS_VOICE_NAME = "km-KH-Wavenet-A"   # Best available Khmer WaveNet voice
GOOGLE_TTS_AUDIO_ENCODING = "MP3"
GTTS_LANGUAGE = "km"                         # gTTS free fallback language code

# ─────────────────────────────────────────────
# IMAGE GENERATION CONFIGURATION
# ─────────────────────────────────────────────
# Provider: "gemini_imagen" | "stability_ai"
IMAGE_PROVIDER: str = os.getenv("IMAGE_PROVIDER", "gemini_imagen")
IMAGE_SEED = 42          # Fixed seed for visual consistency across scenes
STABILITY_ENGINE_ID = "stable-diffusion-xl-1024-v1-0"
STABILITY_API_HOST = "https://api.stability.ai"

# Style anchors appended to EVERY visual prompt for cinematic consistency
IMAGE_STYLE_SUFFIX = (
    "traditional Khmer Angkorian art style, highly detailed oil painting, "
    "dramatic cinematic lighting, golden hour atmosphere, intricate stone temple "
    "architecture, lush tropical jungle, rich emerald and amber tones, "
    "epic storytelling mood, ultra-detailed, 8K resolution"
)

# ─────────────────────────────────────────────
# VIDEO EXPORT PROFILES
# ─────────────────────────────────────────────
VIDEO_FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
VIDEO_BITRATE = "4000k"
AUDIO_BITRATE = "192k"
CROSSFADE_DURATION = 0.3        # seconds between scene transitions

# 📱 MOBILE / TikTok / Facebook Reels — Portrait 9:16
MOBILE_WIDTH = 1080
MOBILE_HEIGHT = 1920
MOBILE_SUFFIX = "_mobile_9x16"

# 💻 LAPTOP / Desktop / YouTube — Landscape 16:9
LAPTOP_WIDTH = 1920
LAPTOP_HEIGHT = 1080
LAPTOP_SUFFIX = "_laptop_16x9"

# ─────────────────────────────────────────────
# KEN BURNS EFFECT SETTINGS
# ─────────────────────────────────────────────
KEN_BURNS_ZOOM_FACTOR = 1.12    # Max zoom level for zoom presets (1.0 = no zoom)
KEN_BURNS_PRESETS = [
    "zoom_in",
    "zoom_out",
    "pan_left",
    "pan_right",
]

# ─────────────────────────────────────────────
# SUBTITLE CONFIGURATION
# ─────────────────────────────────────────────
SUBTITLE_ENABLED = True
SUBTITLE_FONT_SIZE = 42         # px — for 1080-wide mobile export
SUBTITLE_FONT_COLOR = "white"
SUBTITLE_STROKE_COLOR = "black"
SUBTITLE_STROKE_WIDTH = 2
SUBTITLE_POSITION_Y = 0.82      # Fraction of frame height from top
# Noto Sans Khmer font — must be installed or placed in assets/fonts/
SUBTITLE_FONT_PATH = str(ASSETS_DIR / "fonts" / "NotoSansKhmer-Regular.ttf")

# ─────────────────────────────────────────────
# BACKGROUND MUSIC
# ─────────────────────────────────────────────
BACKGROUND_MUSIC_ENABLED = bool(os.getenv("BACKGROUND_MUSIC_PATH", ""))
BACKGROUND_MUSIC_PATH: str = os.getenv(
    "BACKGROUND_MUSIC_PATH", str(ASSETS_DIR / "background_music.mp3")
)
BACKGROUND_MUSIC_VOLUME_DB = -18    # dB below narration

# ─────────────────────────────────────────────
# INTRO / OUTRO
# ─────────────────────────────────────────────
INTRO_VIDEO_PATH = str(ASSETS_DIR / "intro.mp4")
OUTRO_VIDEO_PATH = str(ASSETS_DIR / "outro.mp4")
INTRO_OUTRO_ENABLED = False     # Set to True once you have these assets

# ─────────────────────────────────────────────
# PIPELINE BEHAVIOR
# ─────────────────────────────────────────────
RESUME_ON_RESTART: bool = os.getenv("RESUME_ON_RESTART", "true").lower() == "true"
MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 2.0
MAX_SCENES = 12                 # Hard cap on scenes per story
MIN_SCENE_DURATION_SECONDS = 5  # Minimum audio clip duration

# ─────────────────────────────────────────────
# SOCIAL MEDIA HASHTAGS (default sets)
# ─────────────────────────────────────────────
DEFAULT_KHMER_HASHTAGS = [
    "#រឿងខ្មែរ", "#និទានខ្មែរ", "#ប្រវត្តិខ្មែរ",
    "#ស្តីអំពីខ្មែរ", "#ប្រជុំរឿង", "#រឿងខ្មែរហ្វេសប៊ុក",
]
DEFAULT_ENGLISH_HASHTAGS = [
    "#KhmerStory", "#KhmerFolklore", "#MoralStory", "#KhmerCulture",
    "#KhmerHistory", "#AncientKhmer", "#CambodianLegend", "#KhmerArt",
    "#KhmerLiterature", "#KhmerNarration",
]
DEFAULT_TIKTOK_HASHTAGS = [
    "#fyp", "#foryoupage", "#storytime", "#animatedstory",
    "#khmer", "#cambodia", "#storytelling",
]
