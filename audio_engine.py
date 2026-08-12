"""
audio_engine.py — MODULE 2: Text-to-Speech & Duration Analyzer
===============================================================
Converts Khmer narration text to MP3 audio files using a tiered TTS strategy:
  1. Google Cloud TTS (km-KH-Wavenet-A) — highest quality
  2. ElevenLabs Multilingual v2           — excellent fallback
  3. gTTS (lang='km')                     — free, lower quality fallback

After generation, uses mutagen to extract millisecond-accurate audio durations
and attaches them to EnrichedScene objects for precise video synchronization.

Usage (standalone):
    python audio_engine.py --scenes output/scenes.json
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import click
from mutagen.mp3 import MP3
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import config
from models import EnrichedScene, Scene, SceneList
from utils import log, retry, run_logger, setup_logger

logger = setup_logger("audio_engine")


# ─────────────────────────────────────────────
# TTS PROVIDER: GOOGLE CLOUD TTS
# ─────────────────────────────────────────────

class GoogleTTSProvider:
    """Google Cloud Text-to-Speech — km-KH WaveNet voice."""

    def __init__(self) -> None:
        from google.cloud import texttospeech
        if config.GOOGLE_APPLICATION_CREDENTIALS:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = config.GOOGLE_APPLICATION_CREDENTIALS
        self.client = texttospeech.TextToSpeechClient()
        self.voice = texttospeech.VoiceSelectionParams(
            language_code=config.GOOGLE_TTS_LANGUAGE_CODE,
            name=config.GOOGLE_TTS_VOICE_NAME,
        )
        self.audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=0.92,     # Slightly slower for storytelling feel
            pitch=-1.5,             # Slightly deeper, more dramatic
            effects_profile_id=["headphone-class-device"],
        )
        logger.info("[info]Google Cloud TTS provider ready (km-KH-Wavenet-A)[/info]")

    @retry()
    def synthesize(self, text: str, output_path: Path) -> Path:
        from google.cloud import texttospeech
        synthesis_input = texttospeech.SynthesisInput(text=text)
        response = self.client.synthesize_speech(
            input=synthesis_input,
            voice=self.voice,
            audio_config=self.audio_config,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.audio_content)
        return output_path


# ─────────────────────────────────────────────
# TTS PROVIDER: ELEVENLABS
# ─────────────────────────────────────────────

class ElevenLabsTTSProvider:
    """ElevenLabs Multilingual v2 TTS — high-quality fallback."""

    def __init__(self) -> None:
        from elevenlabs.client import ElevenLabs
        if not config.ELEVENLABS_API_KEY:
            raise EnvironmentError("ELEVENLABS_API_KEY is not set.")
        self.client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
        self.voice_id = config.ELEVENLABS_VOICE_ID or "21m00Tcm4TlvDq8ikWAM"  # Default Rachel
        self.model_id = "eleven_multilingual_v2"
        logger.info("[info]ElevenLabs TTS provider ready[/info]")

    @retry()
    def synthesize(self, text: str, output_path: Path) -> Path:
        audio_generator = self.client.text_to_speech.convert(
            voice_id=self.voice_id,
            text=text,
            model_id=self.model_id,
            output_format="mp3_44100_128",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            for chunk in audio_generator:
                f.write(chunk)
        return output_path


# ─────────────────────────────────────────────
# TTS PROVIDER: gTTS (FREE FALLBACK)
# ─────────────────────────────────────────────

class GTTSProvider:
    """gTTS — free, no-key Khmer TTS. Lower audio quality."""

    def __init__(self) -> None:
        from gtts import gTTS  # noqa: F401 — verify import
        logger.info("[warning]gTTS (free fallback) provider active — lower audio quality[/warning]")

    @retry()
    def synthesize(self, text: str, output_path: Path) -> Path:
        from gtts import gTTS
        tts = gTTS(text=text, lang=config.GTTS_LANGUAGE, slow=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tts.save(str(output_path))
        return output_path


# ─────────────────────────────────────────────
# TTS PROVIDER FACTORY
# ─────────────────────────────────────────────

def get_tts_provider():
    """
    Return the configured TTS provider, falling back gracefully if APIs fail.
    Priority: google_tts → elevenlabs → gtts
    """
    provider_name = config.TTS_PROVIDER.lower()

    if provider_name == "google_tts":
        try:
            return GoogleTTSProvider()
        except Exception as exc:
            logger.warning(f"[warning]Google TTS unavailable ({exc}), trying ElevenLabs…[/warning]")

    if provider_name in ("google_tts", "elevenlabs"):
        try:
            return ElevenLabsTTSProvider()
        except Exception as exc:
            logger.warning(f"[warning]ElevenLabs unavailable ({exc}), falling back to gTTS…[/warning]")

    logger.warning("[warning]Using gTTS fallback — set TTS_PROVIDER in .env for better quality[/warning]")
    return GTTSProvider()


# ─────────────────────────────────────────────
# DURATION EXTRACTION
# ─────────────────────────────────────────────

def get_audio_duration_ms(mp3_path: Path) -> float:
    """
    Use mutagen to extract the exact duration of an MP3 file in milliseconds.
    Falls back to 0.0 if the file cannot be read.
    """
    try:
        audio = MP3(str(mp3_path))
        return audio.info.length * 1000.0   # seconds → milliseconds
    except Exception as exc:
        logger.warning(f"[warning]Could not read duration for {mp3_path.name}: {exc}[/warning]")
        return 0.0


# ─────────────────────────────────────────────
# AUDIO ENGINE
# ─────────────────────────────────────────────

class AudioEngine:
    """
    Orchestrates TTS generation for all scenes in a SceneList.
    Attaches millisecond-accurate durations to each EnrichedScene.
    """

    def __init__(self) -> None:
        self.provider = get_tts_provider()

    def get_audio_path(self, scene_id: int) -> Path:
        return config.AUDIO_DIR / f"scene_{scene_id}.mp3"

    def process_scene(self, scene: Scene, skip_existing: bool = True) -> EnrichedScene:
        """
        Generate TTS audio for a single scene and return an EnrichedScene.

        Args:
            scene: The source Scene (from SceneList).
            skip_existing: If True, skip generation if the MP3 already exists.

        Returns:
            EnrichedScene with audio_path and audio_duration_ms populated.
        """
        audio_path = self.get_audio_path(scene.scene_id)

        if skip_existing and audio_path.exists():
            logger.info(f"[info]Scene {scene.scene_id}: Audio already exists, skipping TTS.[/info]")
        else:
            logger.info(f"[scene]Scene {scene.scene_id}: Synthesizing TTS audio…[/scene]")
            self.provider.synthesize(scene.khmer_narration, audio_path)
            run_logger.increment("tts_calls")
            logger.info(f"[success]✓ Scene {scene.scene_id}: Audio saved → {audio_path.name}[/success]")

        # Always re-read duration from file for accuracy
        duration_ms = get_audio_duration_ms(audio_path)
        run_logger.increment("total_audio_seconds", duration_ms / 1000.0)

        return EnrichedScene(
            **scene.model_dump(),
            audio_path=str(audio_path),
            audio_duration_ms=duration_ms,
        )

    def process_all(
        self,
        scene_list: SceneList,
        done_scene_ids: Optional[List[int]] = None,
    ) -> List[EnrichedScene]:
        """
        Process all scenes in a SceneList, returning a list of EnrichedScene objects.

        Args:
            scene_list: The story scene list to process.
            done_scene_ids: List of already-completed scene IDs (for resumable runs).

        Returns:
            List of EnrichedScene with audio data attached.
        """
        skip_ids = set(done_scene_ids or [])
        enriched: List[EnrichedScene] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task(
                "🎙️  Generating TTS audio…", total=len(scene_list.scenes)
            )
            for scene in scene_list.scenes:
                skip = scene.scene_id in skip_ids
                enriched_scene = self.process_scene(scene, skip_existing=skip)
                enriched.append(enriched_scene)
                progress.advance(task)

        total_duration_s = sum(e.audio_duration_s for e in enriched)
        logger.info(
            f"[success]✓ All {len(enriched)} audio files ready. "
            f"Total narration duration: {total_duration_s:.1f}s[/success]"
        )
        return enriched


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

@click.command()
@click.option(
    "--scenes", "-s",
    default=str(config.OUTPUT_DIR / "scenes.json"),
    show_default=True,
    help="Path to scenes.json from writer.py",
)
def main(scenes: str) -> None:
    """MODULE 2: Generate TTS audio for all scenes in scenes.json."""
    from utils import ensure_output_dirs, console
    from models import SceneList
    import json

    ensure_output_dirs()

    scenes_path = Path(scenes)
    if not scenes_path.exists():
        logger.error(f"[error]Scenes file not found: {scenes_path}[/error]")
        raise SystemExit(1)

    with open(scenes_path, "r", encoding="utf-8") as f:
        scene_list = SceneList.model_validate(json.load(f))

    engine = AudioEngine()
    enriched = engine.process_all(scene_list)

    from rich.table import Table
    table = Table(title="🎙️ Audio Generation Results", border_style="cyan")
    table.add_column("Scene", style="bold cyan", width=6)
    table.add_column("File", width=20)
    table.add_column("Duration (s)", width=14)
    table.add_column("Size", width=10)

    for e in enriched:
        p = Path(e.audio_path) if e.audio_path else None
        size = f"{p.stat().st_size / 1024:.1f} KB" if p and p.exists() else "—"
        table.add_row(
            str(e.scene_id),
            p.name if p else "—",
            f"{e.audio_duration_s:.2f}",
            size,
        )
    console.print(table)


if __name__ == "__main__":
    main()
