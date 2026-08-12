"""
test_writer.py — Unit tests for Module 1: writer.py
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Scene, SceneList
from writer import SceneWriter, SYSTEM_PROMPT


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

SAMPLE_JSON = {
    "story_title": "រឿងកុលាបប៉ៃលិន",
    "story_title_en": "Kulap Pailin",
    "total_scenes": 3,
    "scenes": [
        {
            "scene_id": 1,
            "khmer_narration": "កាលពីមុនដ៏យូរណាស់មក ក្នុងព្រៃស្មៅស្ងប់ស្ងាត់ មានក្មេងស្រីម្នាក់ ដែលមានហ្ឫទ័យក្លាហាន។",
            "visual_prompt": "Ancient Khmer village at dusk, golden temple silhouettes, oil painting style",
            "mood": "mysterious",
            "duration_hint_seconds": 18,
        },
        {
            "scene_id": 2,
            "khmer_narration": "នាងបានដើរចូលទៅក្នុងព្រៃ ហើយឃើញចំការផ្កាកុលាបដ៏ស្រស់ស្អាត ដែលភ្លឺរចង្គ្រោះនៅក្រោមពន្លឺព្រះអាទិត្យ។",
            "visual_prompt": "Magical rose garden in an ancient Khmer forest, mystical light rays",
            "mood": "joyful",
            "duration_hint_seconds": 20,
        },
        {
            "scene_id": 3,
            "khmer_narration": "នាងបានយល់ថា ភាពក្លាហាន និងចិត្តស្មោះ គឺជាគ្រឿងប្រដាប់ដ៏វិសេសបំផុតរបស់មនុស្ស។",
            "visual_prompt": "Triumphant Khmer princess with glowing rose, ancient stone temple background",
            "mood": "triumphant",
            "duration_hint_seconds": 22,
        },
    ],
}


@pytest.fixture
def mock_scene_list() -> SceneList:
    return SceneList.model_validate(SAMPLE_JSON)


# ─────────────────────────────────────────────
# PYDANTIC MODEL TESTS
# ─────────────────────────────────────────────

class TestSceneModel:
    def test_valid_scene_parses_correctly(self):
        scene = Scene.model_validate(SAMPLE_JSON["scenes"][0])
        assert scene.scene_id == 1
        assert scene.mood.value == "mysterious"

    def test_khmer_unicode_validation_passes(self):
        """Should accept text with Khmer Unicode characters."""
        scene = Scene.model_validate(SAMPLE_JSON["scenes"][0])
        assert any("\u1780" <= ch <= "\u17FF" for ch in scene.khmer_narration)

    def test_non_khmer_narration_raises(self):
        """Should reject narration with no Khmer characters."""
        bad = SAMPLE_JSON["scenes"][0].copy()
        bad["khmer_narration"] = "This is only English text without Khmer."
        with pytest.raises(Exception):
            Scene.model_validate(bad)

    def test_scene_id_must_be_positive(self):
        bad = SAMPLE_JSON["scenes"][0].copy()
        bad["scene_id"] = 0
        with pytest.raises(Exception):
            Scene.model_validate(bad)


class TestSceneListModel:
    def test_valid_scene_list_parses(self, mock_scene_list):
        assert mock_scene_list.total_scenes == 3
        assert len(mock_scene_list.scenes) == 3
        assert mock_scene_list.story_title == "រឿងកុលាបប៉ៃលិន"

    def test_all_scene_ids_sequential(self, mock_scene_list):
        ids = [s.scene_id for s in mock_scene_list.scenes]
        assert ids == sorted(ids)


# ─────────────────────────────────────────────
# SCENE WRITER TESTS (mocked API)
# ─────────────────────────────────────────────

class TestSceneWriter:
    @patch("writer.genai")
    def test_writer_initializes_with_api_key(self, mock_genai):
        """Writer should configure genai and create a model."""
        import config
        config.GEMINI_API_KEY = "test-key-123"
        writer = SceneWriter()
        mock_genai.configure.assert_called_once_with(api_key="test-key-123")

    @patch("writer.genai")
    def test_generate_returns_valid_scene_list(self, mock_genai):
        """Mocked LLM should return a valid SceneList."""
        import config
        config.GEMINI_API_KEY = "test-key-123"

        # Mock the model response
        mock_response = MagicMock()
        mock_response.text = json.dumps(SAMPLE_JSON)
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        writer = SceneWriter()
        result = writer.generate("រឿងកុលាបប៉ៃលិន", num_scenes=3)

        assert isinstance(result, SceneList)
        assert result.total_scenes == 3
        assert result.story_title == "រឿងកុលាបប៉ៃលិន"

    @patch("writer.genai")
    def test_save_creates_json_file(self, mock_genai, mock_scene_list, tmp_path):
        """save() should write a valid UTF-8 JSON file."""
        import config
        config.GEMINI_API_KEY = "test-key"

        mock_genai.GenerativeModel.return_value = MagicMock()
        writer = SceneWriter()

        out_path = tmp_path / "scenes.json"
        writer.save(mock_scene_list, out_path)

        assert out_path.exists()
        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["story_title"] == "រឿងកុលាបប៉ៃលិន"
        # Verify Khmer Unicode is stored properly (not escaped)
        raw = out_path.read_text(encoding="utf-8")
        assert "រឿង" in raw

    @patch("writer.genai")
    def test_load_roundtrip(self, mock_genai, mock_scene_list, tmp_path):
        """save() → load() should return identical data."""
        import config
        config.GEMINI_API_KEY = "test-key"
        mock_genai.GenerativeModel.return_value = MagicMock()
        writer = SceneWriter()

        out_path = tmp_path / "scenes.json"
        writer.save(mock_scene_list, out_path)
        loaded = writer.load(out_path)

        assert loaded.story_title == mock_scene_list.story_title
        assert len(loaded.scenes) == len(mock_scene_list.scenes)


# ─────────────────────────────────────────────
# SYSTEM PROMPT TESTS
# ─────────────────────────────────────────────

class TestSystemPrompt:
    def test_prompt_contains_num_scenes_placeholder(self):
        assert "{num_scenes}" in SYSTEM_PROMPT

    def test_prompt_contains_prompt_placeholder(self):
        assert "{prompt}" in SYSTEM_PROMPT

    def test_prompt_formatted_correctly(self):
        formatted = SYSTEM_PROMPT.format(num_scenes=5, prompt="test story")
        assert "5" in formatted
        assert "test story" in formatted


# ─────────────────────────────────────────────
# UTILS: clean_json_response
# ─────────────────────────────────────────────

class TestCleanJsonResponse:
    def test_strips_json_code_fence(self):
        from utils import clean_json_response
        raw = '```json\n{"key": "value"}\n```'
        assert clean_json_response(raw) == '{"key": "value"}'

    def test_strips_plain_code_fence(self):
        from utils import clean_json_response
        raw = '```\n{"key": "value"}\n```'
        assert clean_json_response(raw) == '{"key": "value"}'

    def test_passthrough_clean_json(self):
        from utils import clean_json_response
        raw = '{"key": "value"}'
        assert clean_json_response(raw) == '{"key": "value"}'
