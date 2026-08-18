"""
Central configuration for the Automated AI Khmer Story Pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directories
ROOT_DIR = Path(__file__).resolve().parent
if ROOT_DIR.name == "core":
    ROOT_DIR = ROOT_DIR.parent.parent

OUTPUT_DIR = ROOT_DIR / "output"
AUDIO_DIR = OUTPUT_DIR / "audio"
IMAGES_DIR = OUTPUT_DIR / "images"
VIDEO_DIR = OUTPUT_DIR / "video"
METADATA_DIR = OUTPUT_DIR / "metadata"
ASSETS_DIR = ROOT_DIR / "assets"
STATE_FILE = OUTPUT_DIR / "state.json"
RUN_LOG_FILE = OUTPUT_DIR / "run_log.json"

# API Keys
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "")
STABILITY_API_KEY: str = os.getenv("STABILITY_API_KEY", "")

# Cloudflare R2 / S3 Storage (Optional)
R2_ACCOUNT_ID: str = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID: str = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY: str = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME: str = os.getenv("R2_BUCKET_NAME", "khmer-story-pipeline")
R2_PUBLIC_URL: str = os.getenv("R2_PUBLIC_URL", "")

# Supabase (Optional)
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")

# AI Model Identifiers (Google AI Studio)
GEMINI_WRITER_MODEL = os.getenv("GEMINI_WRITER_MODEL", "gemini-1.5-flash")
GEMINI_PUBLISHER_MODEL = os.getenv("GEMINI_PUBLISHER_MODEL", "gemini-1.5-flash")
GEMINI_IMAGEN_MODEL = os.getenv("GEMINI_IMAGEN_MODEL", "imagen-3.0-generate-002")

# TTS Settings
TTS_PROVIDER: str = os.getenv("TTS_PROVIDER", "gtts")
GOOGLE_TTS_LANGUAGE_CODE = "km-KH"
GOOGLE_TTS_VOICE_NAME = "km-KH-Wavenet-A"
GOOGLE_TTS_AUDIO_ENCODING = "MP3"
GTTS_LANGUAGE = "km"

# Image Generation
IMAGE_PROVIDER: str = os.getenv("IMAGE_PROVIDER", "gemini_imagen")
IMAGE_SEED = 42
STABILITY_ENGINE_ID = "stable-diffusion-xl-1024-v1-0"
STABILITY_API_HOST = "https://api.stability.ai"

IMAGE_STYLE_SUFFIX = (
    "traditional Khmer Angkorian art style, highly detailed painting, "
    "cinematic lighting, golden hour atmosphere, intricate stone temple architecture, "
    "lush tropical environment, rich emerald and amber tones, ultra-detailed, 8k resolution"
)

# Video Export Profiles
VIDEO_FPS = 30
VIDEO_CODEC = "libx264"
AUDIO_CODEC = "aac"
VIDEO_BITRATE = "4000k"
AUDIO_BITRATE = "192k"
CROSSFADE_DURATION = 0.3

# Mobile 9:16
MOBILE_WIDTH = 1080
MOBILE_HEIGHT = 1920
MOBILE_SUFFIX = "_mobile_9x16"

# Laptop 16:9
LAPTOP_WIDTH = 1920
LAPTOP_HEIGHT = 1080
LAPTOP_SUFFIX = "_laptop_16x9"

# Ken Burns Motion
KEN_BURNS_ZOOM_FACTOR = 1.12
KEN_BURNS_PRESETS = ["zoom_in", "zoom_out", "pan_left", "pan_right"]

# Subtitles
SUBTITLE_ENABLED = True
SUBTITLE_FONT_SIZE = 42
SUBTITLE_FONT_COLOR = "white"
SUBTITLE_STROKE_COLOR = "black"
SUBTITLE_STROKE_WIDTH = 2
SUBTITLE_POSITION_Y = 0.82
SUBTITLE_FONT_PATH = str(ASSETS_DIR / "fonts" / "NotoSansKhmer-Regular.ttf")

# Background Music
BACKGROUND_MUSIC_ENABLED = bool(os.getenv("BACKGROUND_MUSIC_PATH", ""))
BACKGROUND_MUSIC_PATH: str = os.getenv("BACKGROUND_MUSIC_PATH", str(ASSETS_DIR / "audio" / "background_music.mp3"))
BACKGROUND_MUSIC_VOLUME_DB = -18

# Intro / Outro
INTRO_VIDEO_PATH = str(ASSETS_DIR / "intro.mp4")
OUTRO_VIDEO_PATH = str(ASSETS_DIR / "outro.mp4")
INTRO_OUTRO_ENABLED = False

# Pipeline Behavior
RESUME_ON_RESTART: bool = os.getenv("RESUME_ON_RESTART", "true").lower() == "true"
MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 2.0
MAX_SCENES = 12
MIN_SCENE_DURATION_SECONDS = 5

# Hashtags
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
