"""
audio_engine.py — MODULE 2: Text-to-Speech & Duration Analyzer
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
from utils import retry, run_logger, setup_logger

logger = setup_logger("audio_engine")


class GoogleTTSProvider:
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
            speaking_rate=0.92,
            pitch=-1.5,
            effects_profile_id=["headphone-class-device"],
        )
        logger.info("[INFO] Google Cloud TTS provider initialized (km-KH-Wavenet-A)")

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


class ElevenLabsTTSProvider:
    def __init__(self) -> None:
        from elevenlabs.client import ElevenLabs
        if not config.ELEVENLABS_API_KEY:
            raise EnvironmentError("ELEVENLABS_API_KEY is not set.")
        self.client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
        self.voice_id = config.ELEVENLABS_VOICE_ID or "21m00Tcm4TlvDq8ikWAM"
        self.model_id = "eleven_multilingual_v2"
        logger.info("[INFO] ElevenLabs TTS provider initialized")

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


class GTTSProvider:
    def __init__(self) -> None:
        from gtts import gTTS
        self._gTTS = gTTS
        logger.info("[INFO] gTTS provider initialized (free tier)")

    @retry()
    def synthesize(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tts = self._gTTS(text=text, lang=config.GTTS_LANGUAGE, slow=False)
        tts.save(str(output_path))
        return output_path


def get_tts_provider(name: Optional[str] = None):
    provider_name = name or config.TTS_PROVIDER
    if provider_name == "google_tts":
        try:
            return GoogleTTSProvider()
        except Exception as exc:
            logger.warning(f"[WARN] Google Cloud TTS failed: {exc}. Falling back to gTTS.")
            return GTTSProvider()
    elif provider_name == "elevenlabs":
        try:
            return ElevenLabsTTSProvider()
        except Exception as exc:
            logger.warning(f"[WARN] ElevenLabs failed: {exc}. Falling back to gTTS.")
            return GTTSProvider()
    else:
        return GTTSProvider()


def get_audio_duration_ms(file_path: Path) -> float:
    path = Path(file_path)
    if not path.exists():
        return 0.0
    try:
        audio = MP3(str(path))
        return float(audio.info.length * 1000.0)
    except Exception:
        return 0.0


class AudioEngine:
    def __init__(self, provider_override: Optional[str] = None) -> None:
        self.provider = get_tts_provider(provider_override)

    def process_scene(
        self,
        scene: Scene,
        output_dir: Optional[Path] = None,
        skip_existing: bool = False,
    ) -> EnrichedScene:
        out_dir = output_dir or config.AUDIO_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        audio_path = out_dir / f"scene_{scene.scene_id}.mp3"

        if not (skip_existing and audio_path.exists()):
            run_logger.increment("tts_calls")
            self.provider.synthesize(scene.khmer_narration, audio_path)

        duration_ms = get_audio_duration_ms(audio_path)
        if duration_ms <= 0.0:
            duration_ms = float(scene.duration_hint_seconds * 1000)

        enriched = EnrichedScene(
            **scene.model_dump(),
            audio_path=str(audio_path),
            audio_duration_ms=duration_ms,
        )
        return enriched

    def process_all(
        self,
        scene_list: SceneList,
        output_dir: Optional[Path] = None,
        skip_existing: bool = False,
    ) -> List[EnrichedScene]:
        enriched: List[EnrichedScene] = []
        out_dir = output_dir or config.AUDIO_DIR

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("[cyan]Synthesizing Khmer TTS...[/cyan]", total=len(scene_list.scenes))
            for scene in scene_list.scenes:
                e = self.process_scene(scene, output_dir=out_dir, skip_existing=skip_existing)
                enriched.append(e)
                progress.advance(task)

        return enriched

    def process_scenes(self, scene_list: SceneList, output_dir: Optional[Path] = None, skip_existing: bool = False) -> List[EnrichedScene]:
        return self.process_all(scene_list, output_dir=output_dir, skip_existing=skip_existing)


@click.command()
@click.option("--scenes", "-s", default="output/scenes.json", help="Path to scenes.json")
@click.option("--provider", "-p", default=None, help="TTS provider override")
def main(scenes: str, provider: Optional[str]) -> None:
    from writer import SceneWriter
    writer = SceneWriter()
    scene_list = writer.load(Path(scenes))
    engine = AudioEngine(provider_override=provider)
    engine.process_all(scene_list)


if __name__ == "__main__":
    main()
