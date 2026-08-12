"""
test_visual_engine.py — Unit tests for Module 3: visual_engine.py
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models import EnrichedScene
from visual_engine import (
    VisualEngine,
    build_full_prompt,
    resize_and_crop,
    save_image_variants,
)


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

@pytest.fixture
def sample_enriched_scene() -> EnrichedScene:
    return EnrichedScene(
        scene_id=1,
        khmer_narration="កាលពីមុនដ៏យូរណាស់មក ក្នុងព្រៃស្មៅស្ងប់ស្ងាត់ មានក្មេងស្រីម្នាក់ ដែលមានហ្ឫទ័យក្លាហាន។",
        visual_prompt="Ancient Khmer village at dusk, golden temple silhouettes",
        mood="mysterious",
        duration_hint_seconds=18,
        audio_path="/fake/audio/scene_1.mp3",
        audio_duration_ms=18500.0,
    )


@pytest.fixture
def sample_pil_image() -> Image.Image:
    """A 768×1344 test image (similar to SDXL output)."""
    return Image.fromarray(
        np.random.randint(0, 255, (1344, 768, 3), dtype=np.uint8)
    )


# ─────────────────────────────────────────────
# PROMPT BUILDING
# ─────────────────────────────────────────────

class TestBuildFullPrompt:
    def test_appends_style_suffix(self):
        prompt = "Ancient Khmer temple at dawn"
        full = build_full_prompt(prompt)
        assert config.IMAGE_STYLE_SUFFIX in full
        assert "Ancient Khmer temple at dawn" in full

    def test_strips_whitespace(self):
        full = build_full_prompt("  test prompt  ")
        assert full.startswith("test prompt")

    def test_combined_prompt_is_non_empty(self):
        full = build_full_prompt("any prompt")
        assert len(full) > 10


# ─────────────────────────────────────────────
# IMAGE PROCESSING
# ─────────────────────────────────────────────

class TestResizeAndCrop:
    def test_output_size_is_exact(self, sample_pil_image):
        """resize_and_crop should produce exactly the target dimensions."""
        result = resize_and_crop(sample_pil_image, 1080, 1920)
        assert result.size == (1080, 1920)

    def test_landscape_crop(self, sample_pil_image):
        result = resize_and_crop(sample_pil_image, 1920, 1080)
        assert result.size == (1920, 1080)

    def test_small_input_is_upscaled(self):
        small = Image.fromarray(np.zeros((100, 50, 3), dtype=np.uint8))
        result = resize_and_crop(small, 1080, 1920)
        assert result.size == (1080, 1920)


class TestSaveImageVariants:
    def test_saves_mobile_and_laptop_versions(self, sample_pil_image, tmp_path):
        """save_image_variants should create both PNG files."""
        import config
        original_images_dir = config.IMAGES_DIR
        config.IMAGES_DIR = tmp_path

        try:
            paths = save_image_variants(sample_pil_image, scene_id=5)
            assert "mobile" in paths
            assert "laptop" in paths
            assert Path(paths["mobile"]).exists()
            assert Path(paths["laptop"]).exists()
        finally:
            config.IMAGES_DIR = original_images_dir

    def test_mobile_image_has_correct_dimensions(self, sample_pil_image, tmp_path):
        import config
        config.IMAGES_DIR = tmp_path
        paths = save_image_variants(sample_pil_image, scene_id=1)
        mobile = Image.open(paths["mobile"])
        assert mobile.size == (config.MOBILE_WIDTH, config.MOBILE_HEIGHT)
        config.IMAGES_DIR = original = Path("output/images")

    def test_laptop_image_has_correct_dimensions(self, sample_pil_image, tmp_path):
        import config
        config.IMAGES_DIR = tmp_path
        paths = save_image_variants(sample_pil_image, scene_id=2)
        laptop = Image.open(paths["laptop"])
        assert laptop.size == (config.LAPTOP_WIDTH, config.LAPTOP_HEIGHT)


# ─────────────────────────────────────────────
# VISUAL ENGINE ORCHESTRATOR
# ─────────────────────────────────────────────

class TestVisualEngine:
    @patch("visual_engine.get_image_provider")
    def test_process_scene_skips_existing_images(
        self, mock_provider_factory, sample_enriched_scene, tmp_path, sample_pil_image
    ):
        """Should skip generation if mobile+laptop images already exist."""
        import config
        config.IMAGES_DIR = tmp_path

        # Pre-create both image files
        (tmp_path / "scene_1_mobile.png").touch()
        (tmp_path / "scene_1_laptop.png").touch()

        mock_provider = MagicMock()
        mock_provider_factory.return_value = mock_provider

        engine = VisualEngine()
        result = engine.process_scene(sample_enriched_scene, skip_existing=True)

        # Provider.generate should NOT have been called
        mock_provider.generate.assert_not_called()
        assert result.scene_id == 1

    @patch("visual_engine.get_image_provider")
    def test_process_scene_generates_and_saves(
        self, mock_provider_factory, sample_enriched_scene, tmp_path, sample_pil_image
    ):
        """Should call provider and save images when not skipping."""
        import config
        config.IMAGES_DIR = tmp_path

        mock_provider = MagicMock()
        mock_provider.generate.return_value = sample_pil_image
        mock_provider_factory.return_value = mock_provider

        engine = VisualEngine()
        result = engine.process_scene(sample_enriched_scene, skip_existing=False)

        mock_provider.generate.assert_called_once()
        assert result.image_path is not None
        assert Path(result.image_path).exists()

    @patch("visual_engine.get_image_provider")
    def test_process_all_returns_correct_count(
        self, mock_provider_factory, tmp_path, sample_pil_image
    ):
        """process_all should return one result per input scene."""
        import config
        config.IMAGES_DIR = tmp_path

        mock_provider = MagicMock()
        mock_provider.generate.return_value = sample_pil_image
        mock_provider_factory.return_value = mock_provider

        scenes = [
            EnrichedScene(
                scene_id=i,
                khmer_narration=f"ការបរិយាយ {i} ប្រយោគខ្មែរ ត្រូវ​ការ​ច្រើន​ ។",
                visual_prompt=f"Khmer scene {i}",
                audio_duration_ms=15000.0,
            )
            for i in range(1, 4)
        ]

        engine = VisualEngine()
        results = engine.process_all(scenes)
        assert len(results) == 3
