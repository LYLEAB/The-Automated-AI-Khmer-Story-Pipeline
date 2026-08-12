"""
test_renderer.py — Unit tests for Module 4: renderer.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models import EnrichedScene, ExportProfile, KenBurnsPreset
from renderer import (
    VideoRenderer,
    add_subtitle_to_frame,
    build_scene_clip,
)


# ─────────────────────────────────────────────
# SUBTITLE RENDERING TESTS
# ─────────────────────────────────────────────

class TestSubtitleRendering:
    def test_add_subtitle_returns_same_shape(self):
        """Subtitle rendering should not change frame dimensions."""
        frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
        result = add_subtitle_to_frame(frame, "ការបរិយាយខ្មែរ", 1080, 1920)
        assert result.shape == frame.shape

    def test_subtitle_modifies_frame(self):
        """Frame with subtitle should differ from blank frame."""
        frame = np.zeros((1920, 1080, 3), dtype=np.uint8)
        result = add_subtitle_to_frame(frame, "ប្រយោគជាភាសាខ្មែរ", 1080, 1920)
        # The modified frame should not be all zeros
        assert not np.all(result == 0)

    def test_subtitle_handles_empty_text(self):
        """Empty subtitle text should not crash."""
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        result = add_subtitle_to_frame(frame, "", 1920, 1080)
        assert result.shape == frame.shape

    def test_subtitle_works_for_laptop_frame(self):
        """Subtitle should work for landscape (16:9) frames too."""
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        result = add_subtitle_to_frame(frame, "ខ្មែរ Khmer text", 1920, 1080)
        assert result.shape == (1080, 1920, 3)


# ─────────────────────────────────────────────
# BUILD SCENE CLIP TESTS
# ─────────────────────────────────────────────

class TestBuildSceneClip:
    def test_returns_none_when_image_missing(self, tmp_path):
        """Should return None if image file doesn't exist."""
        scene = EnrichedScene(
            scene_id=99,
            khmer_narration="ការបរិយាយ ។",
            visual_prompt="test",
            audio_path=str(tmp_path / "scene_99.mp3"),
            audio_duration_ms=10000.0,
        )
        # Don't create the image file
        import config
        config.IMAGES_DIR = tmp_path

        result = build_scene_clip(scene, 1080, 1920, "mobile", subtitle_enabled=False)
        assert result is None

    def test_returns_none_when_audio_missing(self, tmp_path):
        """Should return None if audio file doesn't exist."""
        scene = EnrichedScene(
            scene_id=98,
            khmer_narration="ការបរិយាយ ។",
            visual_prompt="test",
            audio_path=str(tmp_path / "nonexistent.mp3"),
            audio_duration_ms=10000.0,
        )
        # Create the image but not the audio
        img_path = tmp_path / "scene_98_mobile.png"
        Image.fromarray(np.zeros((1920, 1080, 3), dtype=np.uint8)).save(img_path)

        import config
        config.IMAGES_DIR = tmp_path

        result = build_scene_clip(scene, 1080, 1920, "mobile", subtitle_enabled=False)
        assert result is None


# ─────────────────────────────────────────────
# KEN BURNS PRESET TESTS
# ─────────────────────────────────────────────

class TestKenBurnsPresets:
    def test_all_presets_are_valid_enum_values(self):
        presets = list(KenBurnsPreset)
        assert KenBurnsPreset.ZOOM_IN in presets
        assert KenBurnsPreset.ZOOM_OUT in presets
        assert KenBurnsPreset.PAN_LEFT in presets
        assert KenBurnsPreset.PAN_RIGHT in presets

    def test_config_presets_match_enum(self):
        for preset_str in config.KEN_BURNS_PRESETS:
            assert KenBurnsPreset(preset_str) in list(KenBurnsPreset)


# ─────────────────────────────────────────────
# VIDEO RENDERER INTEGRATION TEST (mocked)
# ─────────────────────────────────────────────

class TestVideoRenderer:
    @patch("renderer.build_scene_clip")
    @patch("renderer.mix_background_music", side_effect=lambda v, d: v)
    def test_render_skips_none_clips(self, mock_music, mock_build, tmp_path):
        """Renderer should skip None clips gracefully."""
        # Return None for all scenes → should raise RuntimeError
        mock_build.return_value = None

        scenes = [
            EnrichedScene(
                scene_id=1,
                khmer_narration="ការបរិយាយ ។",
                visual_prompt="test",
                audio_duration_ms=10000.0,
            )
        ]

        import config
        config.VIDEO_DIR = tmp_path

        renderer = VideoRenderer()
        with pytest.raises(RuntimeError, match="No valid scene clips"):
            renderer.render(scenes, "test_story", ExportProfile.MOBILE)

    def test_export_profile_enum_values(self):
        assert ExportProfile.MOBILE.value == "mobile"
        assert ExportProfile.LAPTOP.value == "laptop"
        assert ExportProfile.BOTH.value == "both"
