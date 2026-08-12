# 🎬 Automated AI Khmer Story Pipeline

> A fully automated Python pipeline that transforms a story prompt into a publish-ready vertical video with AI-generated Khmer narration, synchronized visuals, and social media metadata — in one command.

![Python](https://img.shields.io/badge/Python-3.10+-blue) 
![Gemini](https://img.shields.io/badge/AI-Google_Gemini-orange)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ What It Does

```
"រឿងកុលាបប៉ៃលិន"  ──►  [AI Writer]  ──►  [TTS Engine]  ──►  [Image Generator]
                                                               ▼
        TikTok/Reels 📱  ◄──  [Video Renderer]  ◄──  [Enriched Scenes]
        YouTube/Desktop 💻
                              ▼
                     [Publisher]  ──►  caption.txt + metadata.json
```

In a single run, the pipeline:
1. **Writes** a full Khmer story broken into scenes (Gemini 2.5 Pro)
2. **Narrates** each scene in authentic Khmer (`km-KH` WaveNet TTS)
3. **Visualizes** each scene with cinematic AI images (Gemini Imagen 3)
4. **Assembles** a video with Ken Burns effect + Khmer subtitle burn-in
5. **Exports TWO videos** — Mobile 9:16 (TikTok/Reels) + Laptop 16:9 (YouTube)
6. **Generates** hashtags, bilingual captions, and posting strategy

---

## 🗂️ Project Structure

```
The-Automated-AI-Khmer-Story-Pipeline/
├── main.py              # ← START HERE — full pipeline orchestrator
├── writer.py            # Module 1: Gemini story/scene generator
├── audio_engine.py      # Module 2: Khmer TTS + duration extraction
├── visual_engine.py     # Module 3: AI image generation
├── renderer.py          # Module 4: Video assembly (Ken Burns, subtitles, music)
├── publisher.py         # Module 5: Social media metadata generator
├── config.py            # Central settings & export profiles
├── models.py            # Pydantic V2 data models
├── utils.py             # Logger, retry, state persistence
├── requirements.txt
├── .env.example         # ← Copy to .env and fill API keys
├── tests/               # pytest unit tests for all modules
└── output/              # Generated artifacts (audio, images, video, metadata)
```

---

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.10+
- FFmpeg installed and on PATH: https://ffmpeg.org/download.html
- ImageMagick (optional, for some MoviePy text features)
- At minimum: a **Gemini API key** (for writing + publisher)
- For best audio quality: **Google Cloud TTS** service account or **ElevenLabs** key

### 2. Install

```bash
# Clone or enter the project directory
cd "The-Automated-AI-Khmer-Story-Pipeline"

# Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate    # macOS/Linux

# Install all dependencies
pip install -r requirements.txt
```

### 3. Configure API Keys

```bash
# Copy the template
copy .env.example .env

# Edit .env and add your keys:
# GEMINI_API_KEY=your_key_here
# TTS_PROVIDER=gtts            # free option, no key needed
# IMAGE_PROVIDER=gemini_imagen
```

### 4. Download Khmer Font (for subtitles)

```bash
# Create fonts directory
mkdir assets\fonts

# Download Noto Sans Khmer font from Google Fonts:
# https://fonts.google.com/noto/specimen/Noto+Sans+Khmer
# Place NotoSansKhmer-Regular.ttf in assets/fonts/
```

### 5. Run the Pipeline

```bash
# Full run — exports BOTH mobile 9:16 and laptop 16:9 videos
python main.py --prompt "រឿងកុលាបប៉ៃលិន" --scenes 6

# Quick test with 3 scenes only
python main.py --prompt "A brave Khmer princess who saves her village" --scenes 3 --test

# Mobile only
python main.py --prompt "..." --scenes 6 --profile mobile

# Batch mode (one story per line in stories.txt)
python main.py --batch stories.txt --scenes 6
```

---

## 📹 Video Export Profiles

| Profile | Resolution | Aspect Ratio | Platform |
|---------|-----------|--------------|----------|
| **Mobile** | 1080 × 1920 | 9:16 Portrait | TikTok, Facebook Reels, Instagram Reels |
| **Laptop** | 1920 × 1080 | 16:9 Landscape | YouTube, Facebook Watch, Desktop Preview |

Both are exported in the same run (`--profile both` is the default).

---

## 🧠 AI Providers

### TTS (Text-to-Speech)
| Provider | Quality | Cost | Config |
|----------|---------|------|--------|
| Google Cloud TTS | ⭐⭐⭐⭐⭐ | Paid | `TTS_PROVIDER=google_tts` |
| ElevenLabs | ⭐⭐⭐⭐⭐ | Paid | `TTS_PROVIDER=elevenlabs` |
| gTTS | ⭐⭐⭐ | **Free** | `TTS_PROVIDER=gtts` |

### Image Generation
| Provider | Quality | Cost | Config |
|----------|---------|------|--------|
| Gemini Imagen 3 | ⭐⭐⭐⭐⭐ | Paid | `IMAGE_PROVIDER=gemini_imagen` |
| Stability AI SDXL | ⭐⭐⭐⭐ | Paid | `IMAGE_PROVIDER=stability_ai` |

---

## ⚙️ Features

- 🔄 **Resumable pipeline** — crashes restart from the last completed scene
- 🎬 **Ken Burns effect** — 4 cinematic motion presets (zoom in/out, pan left/right)
- 📝 **Khmer subtitle burn-in** — Noto Sans Khmer font with drop shadow
- 🎵 **Background music mixing** — ambient audio at -18 dB beneath narration
- 📊 **Run analytics** — API call counts and timing logged to `output/run_log.json`
- 🌐 **Batch mode** — process multiple stories overnight from a text file
- 💾 **Pydantic V2 validation** — all data models are type-safe and schema-validated

---

## 🧪 Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific module's tests
pytest tests/test_writer.py -v
pytest tests/test_audio_engine.py -v
```

Tests use mocked API calls — no real API keys needed for testing.

---

## 📦 Module Reference

Run any module standalone for testing:

```bash
# Generate scenes only
python writer.py --prompt "រឿងកុលាបប៉ៃលិន" --scenes 6

# Generate audio only (requires scenes.json)
python audio_engine.py --scenes output/scenes.json

# Generate images only
python visual_engine.py --scenes output/scenes.json

# Render video only (requires state.json)
python renderer.py --state output/state.json --profile both

# Generate metadata only
python publisher.py --title "រឿងកុលាបប៉ៃលិន" --title-en "Kulap Pailin"
```

---

## 📁 Output Structure

After a successful run:
```
output/
├── scenes.json              # LLM-generated story scenes
├── state.json               # Pipeline state (for resuming)
├── run_log.json             # API calls, timing analytics
├── audio/
│   ├── scene_1.mp3
│   ├── scene_2.mp3
│   └── ...
├── images/
│   ├── scene_1_mobile.png   # 1080×1920
│   ├── scene_1_laptop.png   # 1920×1080
│   └── ...
├── video/
│   ├── រឿងកុលាបប៉ៃលិន_mobile_9x16.mp4
│   └── រឿងកុលាបប៉ៃលិន_laptop_16x9.mp4
└── metadata/
    ├── metadata.json
    └── caption.txt           # Copy-paste ready for TikTok/Facebook
```

---

## 📜 License

MIT — Feel free to use, modify, and distribute.
