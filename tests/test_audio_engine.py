"""
test_audio_engine.py — Unit tests for Module 2: audio_engine.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import EnrichedScene, Scene, SceneList
from audio_engine import (
    AudioEngine,
    GTTSProvider,
    get_audio_duration_ms,
)


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

SAMPLE_SCENE = {
    "scene_id": 1,
    "khmer_narration": "កាលពីមុនដ៏យូរណាស់មក ក្នុងព្រៃស្មៅស្ងប់ស្ងាត់ មានក្មេងស្រីម្នាក់ ដែលមានហ្ឫទ័យក្លាហាន។",
    "visual_prompt": "Ancient Khmer village at dusk",
    "mood": "mysterious",
    "duration_hint_seconds": 18,
}

SAMPLE_SCENE_LIST_DATA = {
    "story_title": "រឿងកុលាបប៉ៃលិន",
    "story_title_en": "Kulap Pailin",
    "total_scenes": 2,
    "scenes": [
        SAMPLE_SCENE,
        {
            "scene_id": 2,
            "khmer_narration": "នាងបានដើរចូលទៅក្នុងព្រៃ ហើយឃើញចំការផ្កាកុលាបដ៏ស្រស់ស្អាត។",
            "visual_prompt": "Magical rose garden in Khmer forest",
            "mood": "joyful",
            "duration_hint_seconds": 20,
        },
    ],
}


@pytest.fixture
def sample_scene() -> Scene:
    return Scene.model_validate(SAMPLE_SCENE)


@pytest.fixture
def sample_scene_list() -> SceneList:
    return SceneList.model_validate(SAMPLE_SCENE_LIST_DATA)


# ─────────────────────────────────────────────
# DURATION EXTRACTION TESTS
# ─────────────────────────────────────────────

class TestGetAudioDurationMs:
    def test_returns_float(self, tmp_path):
        """Should return 0.0 for a non-existent file (graceful fallback)."""
        fake_path = tmp_path / "fake.mp3"
        duration = get_audio_duration_ms(fake_path)
        assert isinstance(duration, float)
        assert duration == 0.0

    @patch("audio_engine.MP3")
    def test_returns_duration_from_mutagen(self, mock_mp3, tmp_path):
        """Should correctly convert seconds to milliseconds."""
        mock_info = MagicMock()
        mock_info.length = 18.5   # seconds
        mock_mp3.return_value.info = mock_info

        fake_path = tmp_path / "scene_1.mp3"
        fake_path.write_bytes(b"fake mp3 data")

        duration = get_audio_duration_ms(fake_path)
        assert duration == pytest.approx(18500.0, rel=1e-3)

    @patch("audio_engine.MP3", side_effect=Exception("corrupt file"))
    def test_falls_back_to_zero_on_error(self, mock_mp3, tmp_path):
        """Should return 0.0 if mutagen raises an exception."""
        fake_path = tmp_path / "bad.mp3"
        fake_path.write_bytes(b"not an mp3")
        assert get_audio_duration_ms(fake_path) == 0.0


# ─────────────────────────────────────────────
# GTTS PROVIDER TESTS
# ─────────────────────────────────────────────

class TestGTTSProvider:
    @patch("audio_engine.gTTS" if False else "gtts.gTTS")
    def test_gtts_synthesize_saves_file(self, tmp_path):
        """gTTS provider should call save() with the correct path."""
        with patch("audio_engine.GTTSProvider.synthesize") as mock_synth:
            mock_synth.return_value = tmp_path / "scene_1.mp3"
            provider = GTTSProvider()
            result = provider.synthesize(
                "test text", tmp_path / "scene_1.mp3"
            )
            mock_synth.assert_called_once()


# ─────────────────────────────────────────────
# AUDIO ENGINE TESTS
# ─────────────────────────────────────────────

class TestAudioEngine:
    @patch("audio_engine.get_tts_provider")
    @patch("audio_engine.get_audio_duration_ms")
    def test_process_scene_creates_enriched_scene(
        self, mock_duration, mock_provider_factory, sample_scene, tmp_path
    ):
        """process_scene should return an EnrichedScene with audio_path and duration."""
        # Arrange
        mock_provider = MagicMock()
        mock_provider.synthesize.return_value = tmp_path / "scene_1.mp3"
        mock_provider_factory.return_value = mock_provider
        mock_duration.return_value = 18500.0

        # Create the expected audio file so skip_existing=True works
        audio_file = tmp_path / "scene_1.mp3"
        audio_file.write_bytes(b"fake audio data")

        import config
        original_audio_dir = config.AUDIO_DIR
        config.AUDIO_DIR = tmp_path

        try:
            engine = AudioEngine()
            result = engine.process_scene(sample_scene, skip_existing=False)

            assert isinstance(result, EnrichedScene)
            assert result.scene_id == 1
            assert result.audio_duration_ms == pytest.approx(18500.0)
        finally:
            config.AUDIO_DIR = original_audio_dir

    @patch("audio_engine.get_tts_provider")
    @patch("audio_engine.get_audio_duration_ms")
    def test_process_all_returns_correct_count(
        self, mock_duration, mock_provider_factory, sample_scene_list, tmp_path
    ):
        """process_all should return one EnrichedScene per scene in SceneList."""
        mock_provider = MagicMock()
        mock_provider_factory.return_value = mock_provider
        mock_duration.return_value = 15000.0

        import config
        original_audio_dir = config.AUDIO_DIR
        config.AUDIO_DIR = tmp_path

        # Pre-create fake audio files so skip_existing=True skips synthesis
        for i in range(1, 3):
            (tmp_path / f"scene_{i}.mp3").write_bytes(b"fake")

        try:
            engine = AudioEngine()
            results = engine.process_all(sample_scene_list)
            assert len(results) == 2
            assert all(isinstance(e, EnrichedScene) for e in results)
        finally:
            config.AUDIO_DIR = original_audio_dir

    @patch("audio_engine.get_tts_provider")
    @patch("audio_engine.get_audio_duration_ms")
    def test_audio_duration_s_property(
        self, mock_duration, mock_provider_factory, sample_scene, tmp_path
    ):
        """audio_duration_s should return milliseconds / 1000."""
        mock_provider_factory.return_value = MagicMock()
        mock_duration.return_value = 20000.0

        import config
        config.AUDIO_DIR = tmp_path
        (tmp_path / "scene_1.mp3").write_bytes(b"fake")

        engine = AudioEngine()
        result = engine.process_scene(sample_scene, skip_existing=True)
        assert result.audio_duration_s == pytest.approx(20.0)
