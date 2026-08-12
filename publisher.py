"""
publisher.py — MODULE 5: Metadata & Publishing Formatter
=========================================================
Uses Gemini to generate polished social media metadata for the finished video:
  • 3 catchy Khmer title variants (with emoji)
  • Bilingual (Khmer + English) description (~150 words each)
  • 25+ optimized hashtags (Khmer + English + TikTok virality tags)
  • Platform-specific post notes (TikTok vs. Facebook Reels)
  • Best posting time recommendation

Saves output to:
  • output/metadata/metadata.json  — structured data
  • output/metadata/caption.txt   — copy-paste ready post caption

Usage (standalone):
    python publisher.py --title "រឿងកុលាបប៉ៃលិន" --title-en "Kulap Pailin"
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import click
import google.generativeai as genai
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from models import PublishMetadata, SceneList
from utils import clean_json_response, log, retry, run_logger, setup_logger, console

logger = setup_logger("publisher")


# ─────────────────────────────────────────────
# PUBLISHER SYSTEM PROMPT
# ─────────────────────────────────────────────

PUBLISHER_PROMPT = """You are an expert Khmer social media content creator specializing 
in viral storytelling content for TikTok and Facebook Reels.

Generate optimized social media metadata for the following Khmer story video.

Story Title (Khmer): {story_title}
Story Title (English): {story_title_en}
Story Summary: {summary}
Scene count: {num_scenes}
Total duration: ~{duration_seconds:.0f} seconds

OUTPUT: Return ONLY valid JSON (no markdown) matching this exact schema:
{{
  "title_variants": [
    "🎭 <Khmer title variant 1 with emoji>",
    "📖 <Khmer title variant 2 with emoji>",
    "✨ <Khmer title variant 3 with emoji>"
  ],
  "description_khmer": "<150-200 word Khmer description — emotional, hook-driven, ends with CTA>",
  "description_english": "<100-150 word English description — storytelling tone, cultural context>",
  "hashtags": [
    "<hashtag1>", "<hashtag2>", "... up to 30 hashtags total"
  ],
  "best_post_time": "<e.g. '7:00 PM – 9:00 PM Phnom Penh time (peak Khmer audience)'>",
  "platform_notes": {{
    "tiktok": "<TikTok-specific advice: hook in first 3s, caption length, etc.>",
    "facebook": "<Facebook-specific advice: description length, thumbnail tip, etc.>"
  }}
}}

HASHTAG RULES:
- Include 8 Khmer-script hashtags: {khmer_hashtags}
- Include 10 English hashtags: {english_hashtags}
- Include 7 TikTok virality hashtags: {tiktok_hashtags}
- Add 5 more creative, story-specific hashtags

DESCRIPTION RULES:
- Start Khmer description with an emotional hook in the first sentence
- Include a call-to-action at the end (e.g., "Subscribe", "Share with friends")
- English description should emphasize cultural richness and educational value
"""


# ─────────────────────────────────────────────
# PUBLISHER
# ─────────────────────────────────────────────

class MetadataPublisher:
    """Generates social media metadata using Gemini."""

    def __init__(self) -> None:
        if not config.GEMINI_API_KEY:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        genai.configure(api_key=config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name=config.GEMINI_PUBLISHER_MODEL,
            generation_config=genai.GenerationConfig(
                temperature=0.9,
                top_p=0.95,
                response_mime_type="application/json",
            ),
        )
        logger.info(f"[info]Publisher initialized with model: {config.GEMINI_PUBLISHER_MODEL}[/info]")

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
        """
        Generate a full PublishMetadata object for the given story.

        Args:
            story_title: Khmer story title.
            story_title_en: English translation of the title.
            summary: Optional story summary for context.
            num_scenes: Number of scenes in the video.
            duration_seconds: Total video duration in seconds.

        Returns:
            Validated PublishMetadata Pydantic model.
        """
        prompt = PUBLISHER_PROMPT.format(
            story_title=story_title,
            story_title_en=story_title_en or story_title,
            summary=summary or f"A traditional Khmer story about {story_title_en or story_title}",
            num_scenes=num_scenes,
            duration_seconds=duration_seconds,
            khmer_hashtags=" ".join(config.DEFAULT_KHMER_HASHTAGS),
            english_hashtags=" ".join(config.DEFAULT_ENGLISH_HASHTAGS),
            tiktok_hashtags=" ".join(config.DEFAULT_TIKTOK_HASHTAGS),
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("📢 Generating social media metadata…", total=None)
            raw = self._call_llm(prompt)
            progress.update(task, completed=True)

        cleaned = clean_json_response(raw)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Publisher LLM returned invalid JSON: {exc}") from exc

        metadata = PublishMetadata.model_validate(data)
        logger.info(
            f"[success]✓ Metadata generated: "
            f"{len(metadata.hashtags)} hashtags, "
            f"{len(metadata.title_variants)} title variants[/success]"
        )
        return metadata

    def save(
        self,
        metadata: PublishMetadata,
        story_title: str,
        video_paths: Optional[dict] = None,
    ) -> dict[str, Path]:
        """
        Save metadata to JSON and a copy-paste ready caption TXT file.

        Args:
            metadata: The generated PublishMetadata.
            story_title: Used in the output filename.
            video_paths: Optional dict of {'mobile': path, 'laptop': path}.

        Returns:
            Dict with 'json' and 'txt' paths.
        """
        config.METADATA_DIR.mkdir(parents=True, exist_ok=True)

        # Full metadata JSON
        json_path = config.METADATA_DIR / "metadata.json"
        full_data = metadata.model_dump()
        if video_paths:
            full_data["video_exports"] = video_paths
        full_data["story_title"] = story_title

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(full_data, f, indent=2, ensure_ascii=False)

        # Caption TXT — copy-paste ready
        caption_path = config.METADATA_DIR / "caption.txt"
        caption_lines = [
            f"{'='*60}",
            f"📱 TIKTOK / FACEBOOK REELS CAPTION",
            f"{'='*60}",
            "",
            "🏷️  TITLES (choose one):",
            *[f"  {t}" for t in metadata.title_variants],
            "",
            "📝 KHMER DESCRIPTION:",
            metadata.description_khmer,
            "",
            "📝 ENGLISH DESCRIPTION:",
            metadata.description_english,
            "",
            "🔖 HASHTAGS:",
            " ".join(metadata.hashtags),
            "",
            f"⏰ BEST POST TIME: {metadata.best_post_time}",
            "",
            "📱 PLATFORM NOTES:",
            f"  TikTok: {metadata.platform_notes.get('tiktok', '')}",
            f"  Facebook: {metadata.platform_notes.get('facebook', '')}",
            "",
            "📹 VIDEO EXPORTS:",
        ]
        if video_paths:
            for k, v in video_paths.items():
                caption_lines.append(f"  [{k.upper()}] {v}")
        caption_lines.append(f"{'='*60}")

        with open(caption_path, "w", encoding="utf-8") as f:
            f.write("\n".join(caption_lines))

        logger.info(f"[success]✓ Metadata saved → {json_path.name}[/success]")
        logger.info(f"[success]✓ Caption saved  → {caption_path.name}[/success]")
        return {"json": json_path, "txt": caption_path}

    def print_preview(self, metadata: PublishMetadata) -> None:
        """Print a rich-formatted preview of the generated metadata."""
        console.print(
            Panel(
                f"[bold yellow]Title Options:[/bold yellow]\n"
                + "\n".join(f"  {t}" for t in metadata.title_variants)
                + f"\n\n[bold cyan]Hashtags ({len(metadata.hashtags)}):[/bold cyan]\n"
                + " ".join(metadata.hashtags[:15]) + " …"
                + f"\n\n[bold green]Post Time:[/bold green] {metadata.best_post_time}",
                title="[bold magenta]📢 Social Media Preview[/bold magenta]",
                border_style="magenta",
            )
        )


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

@click.command()
@click.option("--title", "-t", required=True, help="Khmer story title")
@click.option("--title-en", default="", help="English story title")
@click.option("--summary", default="", help="Brief story summary")
@click.option("--scenes", default=0, type=int, help="Number of scenes")
@click.option("--duration", default=0.0, type=float, help="Video duration in seconds")
def main(
    title: str,
    title_en: str,
    summary: str,
    scenes: int,
    duration: float,
) -> None:
    """MODULE 5: Generate social media metadata for the story video."""
    from utils import ensure_output_dirs
    ensure_output_dirs()

    publisher = MetadataPublisher()
    metadata = publisher.generate(
        story_title=title,
        story_title_en=title_en,
        summary=summary,
        num_scenes=scenes,
        duration_seconds=duration,
    )
    publisher.print_preview(metadata)
    publisher.save(metadata, story_title=title)


if __name__ == "__main__":
    main()
