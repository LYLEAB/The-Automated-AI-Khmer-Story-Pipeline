# Automated AI Khmer Story Pipeline

A production-grade Python pipeline and FastAPI web service that transforms a story prompt into publish-ready videos with AI-generated Khmer narration, synchronized visuals, dynamic motion, Khmer subtitles, and social media metadata.

---

## Overview

```text
"រឿងកុលាបប៉ៃលិន"  -->  [AI Writer]  -->  [TTS Engine]  -->  [Image Generator]
                                                                  |
         TikTok/Reels  <--  [Video Renderer]  <--  [Enriched Scenes]
       YouTube/Desktop
                                  |
                        [Publisher]  -->  caption.txt + metadata.json
```

### Pipeline Capabilities:
1. **Scripting**: Generates structured Khmer story scenes using Google AI Studio Gemini models.
2. **Narration**: Generates authentic Khmer speech (`km-KH` WaveNet TTS / ElevenLabs / gTTS) and measures millisecond-accurate audio durations.
3. **Visuals**: Creates stylized Angkorian/cinematic visuals via Gemini Imagen 3 or Stability AI SDXL.
4. **Assembly**: Combines assets with cinematic Ken Burns motion effects, crossfade transitions, and burned-in Khmer Unicode subtitles.
5. **Dual Export**: Renders both Mobile 9:16 (1080x1920) and Landscape 16:9 (1920x1080) in one pass.
6. **Publishing**: Produces SEO-optimized bilingual descriptions, clean titles, and targeted hashtags.

---

## Architecture & Project Structure

```text
The-Automated-AI-Khmer-Story-Pipeline/
├── src/
│   ├── core/
│   │   ├── config.py           # Central configuration and AI Studio settings
│   │   ├── models.py           # Pydantic V2 data structures
│   │   ├── utils.py            # Structured logging and retry decorators
│   │   └── storage.py          # Cloudflare R2 and Supabase storage handler
│   ├── modules/
│   │   ├── writer.py           # Gemini Script & Scene Generator
│   │   ├── audio_engine.py     # Tiered Khmer TTS Engine
│   │   ├── visual_engine.py    # Imagen 3 / SDXL generator
│   │   ├── renderer.py         # Video stitching, Ken Burns, Subtitles
│   │   └── publisher.py        # Social media metadata and SEO
│   ├── api/
│   │   ├── server.py           # FastAPI REST and SSE live streaming API
│   │   └── supabase_client.py  # Supabase job history persistence
│   └── main.py                 # Pipeline CLI orchestrator
├── web/                        # Static frontend (Vercel / Cloudflare Pages ready)
│   ├── index.html
│   ├── app.js
│   └── style.css
├── assets/
│   └── fonts/
│       └── NotoSansKhmer-Regular.ttf
├── Dockerfile                  # Container definition with FFmpeg & Python
├── requirements.txt            # Python dependencies
├── main.py                     # Root CLI entry point
└── api.py                      # Root API entry point
```

---

## Getting Started

### 1. Prerequisites

- Python 3.10+
- FFmpeg installed and available in system PATH
- Google Gemini API key (from Google AI Studio)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/LYLEAB/The-Automated-AI-Khmer-Story-Pipeline.git
cd The-Automated-AI-Khmer-Story-Pipeline

# Create and activate a virtual environment
python -m venv venv
# On Windows:
venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

Copy `.env.example` to `.env` and provide your credentials:

```bash
cp .env.example .env
```

```ini
GEMINI_API_KEY=your_gemini_api_key_here
TTS_PROVIDER=gtts            # Options: google_tts | elevenlabs | gtts
IMAGE_PROVIDER=gemini_imagen # Options: gemini_imagen | stability_ai
```

---

## Usage

### Command Line Interface (CLI)

```bash
# Full run with default settings (6 scenes, both export profiles)
python main.py --prompt "រឿងកុលាបប៉ៃលិន" --scenes 6

# Quick test run (capped at 3 scenes)
python main.py --prompt "A brave Khmer princess" --scenes 3 --test

# Mobile-only export
python main.py --prompt "រឿងកុលាបប៉ៃលិន" --scenes 6 --profile mobile

# Batch mode from a text file
python main.py --batch stories.txt
```

### Web Application & REST API

```bash
# Start the FastAPI server locally
uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser to access the web generation interface.

---

## Production Deployment

### 1. Backend (Render / Railway / Cloud Run)
Deploy the repository using the provided `Dockerfile` or Python environment. Set your environment variables (`GEMINI_API_KEY`, etc.) in your hosting provider's dashboard.

### 2. Frontend (Cloudflare Pages / Vercel)
Deploy the `web/` folder to Cloudflare Pages or Vercel. Set `API_BASE` in `web/app.js` to point to your live backend domain.

### 3. Storage (Cloudflare R2)
Optionally configure Cloudflare R2 credentials in `.env` (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_PUBLIC_URL`) for zero-egress CDN video distribution.

---

## Running Tests

```bash
# Run the complete test suite
pytest tests/ -v
```

---

## License

MIT License
