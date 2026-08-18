"""
publisher.py — MODULE 5: Metadata & Publishing Formatter
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import click
import google.generativeai as genai
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from models import PublishMetadata, SceneList
from utils import clean_json_response, retry, run_logger, setup_logger

logger = setup_logger("publisher")

PUBLISHER_PROMPT = """You are a professional digital media strategist specializing in Khmer video distribution.
Generate optimized social media metadata for the following story video.

Story Title (Khmer): {story_title}
Story Title (English): {story_title_en}
Story Summary: {summary}
Scene count: {num_scenes}
Total duration: ~{duration_seconds:.0f} seconds

OUTPUT: Return ONLY valid JSON (no markdown code fences, no emojis in text):
{{
  "title_variants": [
    "<Professional Khmer title variant 1>",
    "<Professional Khmer title variant 2>",
    "<Professional Khmer title variant 3>"
  ],
  "description_khmer": "<150-200 word Khmer description with strong narrative hook and call to action>",
  "description_english": "<100-150 word English description with cultural and historical context>",
  "hashtags": [
    "<hashtag1>", "<hashtag2>", "... up to 30 hashtags total"
  ],
  "best_post_time": "18:00 - 21:00 Phnom Penh time (peak engagement window)",
  "platform_notes": {{
    "tiktok": "Use high-contrast hook in the first 3 seconds.",
    "facebook": "Include full Khmer description for search discovery."
  }}
}}
"""


class MetadataPublisher:
    def __init__(self) -> None:
        if not config.GEMINI_API_KEY:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        genai.configure(api_key=config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name=config.GEMINI_PUBLISHER_MODEL,
            generation_config=genai.GenerationConfig(
                temperature=0.8,
                top_p=0.95,
                response_mime_type="application/json",
            ),
        )

    @retry()
    def _call_llm(self, prompt: str) -> str:
        run_logger.increment("gemini_calls")
        response = self.model.generate_content(prompt)
        return response.text

    def generate(
        self,
        story_title: str,
        story_title_en: str = "",
        summary: str = "",
        num_scenes: int = 0,
        duration_seconds: float = 0.0,
    ) -> PublishMetadata:
        prompt = PUBLISHER_PROMPT.format(
            story_title=story_title,
            story_title_en=story_title_en or story_title,
            summary=summary or f"Traditional Khmer story: {story_title}",
            num_scenes=num_scenes,
            duration_seconds=duration_seconds,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Generating metadata...[/cyan]", total=None)
            raw = self._call_llm(prompt)
            progress.update(task, completed=True)

        cleaned = clean_json_response(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON from LLM: {exc}")

        metadata = PublishMetadata(**data)
        return metadata

    def save(self, metadata: PublishMetadata, story_title: Optional[str] = None) -> dict[str, Path]:
        config.METADATA_DIR.mkdir(parents=True, exist_ok=True)
        json_path = config.METADATA_DIR / "metadata.json"
        txt_path = config.METADATA_DIR / "caption.txt"

        with open(json_path, "w", encoding="utf-8") as f:
            f.write(metadata.model_dump_json(indent=2))

        caption_text = (
            f"{metadata.title_variants[0]}\n\n"
            f"{metadata.description_khmer}\n\n"
            f"--- HASHTAGS ---\n"
            f"{' '.join(metadata.hashtags)}\n"
        )
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(caption_text)

        return {"json": json_path, "txt": txt_path}


@click.command()
@click.option("--title", "-t", required=True, help="Khmer story title")
@click.option("--title-en", default="", help="English translation of title")
@click.option("--summary", default="", help="Story summary text")
@click.option("--scenes", default=6, help="Number of scenes")
@click.option("--duration", default=90.0, help="Total video duration in seconds")
def main(title: str, title_en: str, summary: str, scenes: int, duration: float) -> None:
    pub = MetadataPublisher()
    metadata = pub.generate(
        story_title=title,
        story_title_en=title_en,
        summary=summary,
        num_scenes=scenes,
        duration_seconds=duration,
    )
    pub.save(metadata, title)


if __name__ == "__main__":
    main()
