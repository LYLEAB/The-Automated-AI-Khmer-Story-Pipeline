"""
test_publisher.py — Unit tests for Module 5: publisher.py
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from models import PublishMetadata
from publisher import MetadataPublisher


# ─────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────

SAMPLE_METADATA = {
    "title_variants": [
        "🎭 រឿងកុលាបប៉ៃលិន — ព្រឹត្តិការណ៍ដ៏អស្ចារ្យ",
        "📖 ភ្លើងក្ដីស្រឡាញ់ — កុលាបប៉ៃលិន",
        "✨ ប្រជុំរឿងខ្មែរ — ការចងហ្ឫទ័យ",
    ],
    "description_khmer": "ការពិព័រណ៌ ​ ការពិព័រណ៌ ​ ការពិព័រណ៌ ​ ខ្មែរ ​ ខ្មែរ ​ ។",
    "description_english": "A timeless Khmer folktale about love, courage, and redemption.",
    "hashtags": [
        "#រឿងខ្មែរ", "#KhmerStory", "#fyp", "#Cambodia", "#KhmerCulture",
        "#MoralStory", "#KhmerFolklore", "#storytime", "#animatedstory",
        "#foryoupage",
    ],
    "best_post_time": "7:00 PM – 9:00 PM Phnom Penh time",
    "platform_notes": {
        "tiktok": "Hook in the first 3 seconds. Keep caption under 150 chars.",
        "facebook": "Use the thumbnail at 1:01 for Facebook Reels preview.",
    },
}


@pytest.fixture
def sample_metadata() -> PublishMetadata:
    return PublishMetadata.model_validate(SAMPLE_METADATA)


# ─────────────────────────────────────────────
# PYDANTIC MODEL TESTS
# ─────────────────────────────────────────────

class TestPublishMetadataModel:
    def test_valid_metadata_parses(self, sample_metadata):
        assert len(sample_metadata.title_variants) == 3
        assert len(sample_metadata.hashtags) == 10
        assert "tiktok" in sample_metadata.platform_notes

    def test_title_variants_required(self):
        bad = SAMPLE_METADATA.copy()
        bad["title_variants"] = []
        with pytest.raises(Exception):
            PublishMetadata.model_validate(bad)

    def test_hashtags_list_is_preserved(self, sample_metadata):
        assert "#KhmerStory" in sample_metadata.hashtags
        assert "#fyp" in sample_metadata.hashtags


# ─────────────────────────────────────────────
# PUBLISHER LLM TESTS (mocked)
# ─────────────────────────────────────────────

class TestMetadataPublisher:
    @patch("publisher.genai")
    def test_generate_returns_valid_metadata(self, mock_genai):
        """Publisher should return a valid PublishMetadata given mocked LLM response."""
        import config
        config.GEMINI_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.text = json.dumps(SAMPLE_METADATA)
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        publisher = MetadataPublisher()
        result = publisher.generate(
            story_title="រឿងកុលាបប៉ៃលិន",
            story_title_en="Kulap Pailin",
            num_scenes=3,
            duration_seconds=60.0,
        )

        assert isinstance(result, PublishMetadata)
        assert len(result.title_variants) == 3
        assert len(result.hashtags) > 5

    @patch("publisher.genai")
    def test_save_creates_json_and_txt(self, mock_genai, sample_metadata, tmp_path):
        """save() should create both metadata.json and caption.txt."""
        import config
        config.GEMINI_API_KEY = "test-key"
        config.METADATA_DIR = tmp_path

        mock_genai.GenerativeModel.return_value = MagicMock()
        publisher = MetadataPublisher()

        paths = publisher.save(sample_metadata, "រឿងកុលាបប៉ៃលិន")

        assert paths["json"].exists()
        assert paths["txt"].exists()

    @patch("publisher.genai")
    def test_saved_json_contains_khmer_unicode(self, mock_genai, sample_metadata, tmp_path):
        """Saved JSON should store Khmer Unicode as-is, not escaped."""
        import config
        config.GEMINI_API_KEY = "test-key"
        config.METADATA_DIR = tmp_path

        mock_genai.GenerativeModel.return_value = MagicMock()
        publisher = MetadataPublisher()
        paths = publisher.save(sample_metadata, "រឿងកុលាបប៉ៃលិន")

        raw = paths["json"].read_text(encoding="utf-8")
        assert "#រឿងខ្មែរ" in raw   # Khmer hashtag stored as Unicode, not \\u...

    @patch("publisher.genai")
    def test_caption_txt_contains_hashtags(self, mock_genai, sample_metadata, tmp_path):
        """caption.txt should include the hashtag section."""
        import config
        config.GEMINI_API_KEY = "test-key"
        config.METADATA_DIR = tmp_path

        mock_genai.GenerativeModel.return_value = MagicMock()
        publisher = MetadataPublisher()
        paths = publisher.save(sample_metadata, "test")

        caption = paths["txt"].read_text(encoding="utf-8")
        assert "HASHTAGS" in caption
        assert "#KhmerStory" in caption

    @patch("publisher.genai")
    def test_invalid_llm_json_raises_value_error(self, mock_genai):
        """Publisher should raise ValueError if LLM returns non-JSON."""
        import config
        config.GEMINI_API_KEY = "test-key"

        mock_response = MagicMock()
        mock_response.text = "This is not JSON at all!"
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model

        publisher = MetadataPublisher()
        with pytest.raises(ValueError, match="invalid JSON"):
            publisher.generate("test title")
