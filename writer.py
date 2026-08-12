"""
writer.py — MODULE 1: Script & Scene Parser
=============================================
Calls the Google Gemini API to generate a structured Khmer story broken into
discrete visual scenes, then validates and saves the output as a Pydantic-typed
SceneList model and a JSON file.

Usage (standalone):
    python writer.py --prompt "រឿងកុលាបប៉ៃលិន" --scenes 6
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click
import google.generativeai as genai
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from models import Scene, SceneList
from utils import clean_json_response, log, retry, run_logger, setup_logger

logger = setup_logger("writer")


# ─────────────────────────────────────────────
# LLM SYSTEM PROMPT
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert Khmer storyteller and screenwriter.
Your task is to write a compelling, emotionally engaging Khmer narrative story 
divided into exactly {num_scenes} visual scenes.

CRITICAL RULES:
1. ALL narration text MUST be written in authentic Khmer Unicode script (ភាសាខ្មែរ).
   Do NOT use transliteration, romanization, or Latin characters in khmer_narration.
2. Each scene narration should be 2-4 sentences (approximately 15-25 seconds of speech).
3. Visual prompts MUST be in English and highly descriptive for AI image generation.
4. Scenes must flow with emotional arc: setup → rising tension → climax → resolution.
5. Return ONLY valid JSON — no markdown, no extra text, no code fences.

OUTPUT FORMAT (strict JSON schema):
{{
  "story_title": "<Khmer title>",
  "story_title_en": "<English title translation>",
  "total_scenes": {num_scenes},
  "scenes": [
    {{
      "scene_id": 1,
      "khmer_narration": "<Khmer text here>",
      "visual_prompt": "<English image generation prompt here>",
      "mood": "<one of: mysterious|joyful|dramatic|peaceful|tense|melancholic|triumphant|romantic>",
      "duration_hint_seconds": <integer 10-30>
    }}
  ]
}}

Story topic/prompt: {prompt}
Story style: Traditional Khmer folklore/literature, moral resolution, Angkorian era setting.
"""


# ─────────────────────────────────────────────
# CORE WRITER CLASS
# ─────────────────────────────────────────────

class SceneWriter:
    """Generates a structured Khmer story using the Gemini LLM."""

    def __init__(self) -> None:
        if not config.GEMINI_API_KEY:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. Please add it to your .env file."
            )
        genai.configure(api_key=config.GEMINI_API_KEY)
        self.model = genai.GenerativeModel(
            model_name=config.GEMINI_WRITER_MODEL,
            generation_config=genai.GenerationConfig(
                temperature=0.85,
                top_p=0.95,
                top_k=40,
                response_mime_type="application/json",
            ),
        )
        logger.info(f"[info]SceneWriter initialized with model: {config.GEMINI_WRITER_MODEL}[/info]")

    @retry(max_attempts=config.MAX_RETRY_ATTEMPTS)
    def _call_llm(self, prompt_text: str) -> str:
        """Send the prompt to Gemini and return the raw response text."""
        run_logger.increment("gemini_calls")
        response = self.model.generate_content(prompt_text)
        return response.text

    def generate(self, story_prompt: str, num_scenes: int = 6) -> SceneList:
        """
        Generate a complete SceneList from a story prompt.

        Args:
            story_prompt: The story topic or prompt (Khmer or English).
            num_scenes: Target number of scenes (clamped to config.MAX_SCENES).

        Returns:
            A validated SceneList Pydantic model.
        """
        num_scenes = min(num_scenes, config.MAX_SCENES)
        full_prompt = SYSTEM_PROMPT.format(
            num_scenes=num_scenes,
            prompt=story_prompt,
        )

        logger.info(f"[info]Generating {num_scenes} scenes for: '{story_prompt}'[/info]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("✍️  Writing story with Gemini…", total=None)
            raw_response = self._call_llm(full_prompt)
            progress.update(task, completed=True)

        # Clean LLM response and parse JSON
        cleaned = clean_json_response(raw_response)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error(f"[error]Failed to parse LLM JSON response: {exc}[/error]")
            logger.debug(f"Raw response:\n{raw_response[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {exc}") from exc

        # Validate with Pydantic
        try:
            scene_list = SceneList.model_validate(data)
        except Exception as exc:
            logger.error(f"[error]Pydantic validation failed: {exc}[/error]")
            raise ValueError(f"SceneList schema validation failed: {exc}") from exc

        logger.info(
            f"[success]✓ Generated {len(scene_list.scenes)} scenes for "
            f"'{scene_list.story_title}'[/success]"
        )
        run_logger.increment("total_scene_count", len(scene_list.scenes))
        return scene_list

    def save(self, scene_list: SceneList, output_path: Optional[Path] = None) -> Path:
        """
        Save the SceneList to a JSON file.

        Args:
            scene_list: The validated SceneList to save.
            output_path: Custom path (defaults to output/scenes.json).

        Returns:
            The path where the file was saved.
        """
        path = output_path or config.OUTPUT_DIR / "scenes.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                scene_list.model_dump(),
                f,
                indent=2,
                ensure_ascii=False,   # Keep Khmer Unicode as-is (not escaped)
            )
        logger.info(f"[success]✓ Scenes saved → {path}[/success]")
        return path

    def load(self, json_path: Optional[Path] = None) -> SceneList:
        """
        Load and validate a SceneList from an existing JSON file.

        Args:
            json_path: Path to scenes JSON (defaults to output/scenes.json).

        Returns:
            A validated SceneList Pydantic model.
        """
        path = json_path or config.OUTPUT_DIR / "scenes.json"
        if not path.exists():
            raise FileNotFoundError(f"Scene file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SceneList.model_validate(data)


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

@click.command()
@click.option("--prompt", "-p", required=True, help="Story topic or prompt (Khmer/English)")
@click.option("--scenes", "-s", default=6, show_default=True, help="Number of scenes to generate")
@click.option("--output", "-o", default=None, help="Custom output JSON path")
def main(prompt: str, scenes: int, output: Optional[str]) -> None:
    """MODULE 1: Generate a structured Khmer story scene list using Gemini."""
    from utils import ensure_output_dirs
    ensure_output_dirs()

    writer = SceneWriter()
    scene_list = writer.generate(story_prompt=prompt, num_scenes=scenes)
    out_path = Path(output) if output else None
    saved_path = writer.save(scene_list, out_path)

    from rich.table import Table
    from utils import console

    table = Table(title=f"📖 {scene_list.story_title}", border_style="magenta")
    table.add_column("Scene", style="bold cyan", width=6)
    table.add_column("Mood", style="yellow", width=12)
    table.add_column("Duration (s)", width=12)
    table.add_column("Khmer Narration (preview)", style="white")

    for scene in scene_list.scenes:
        preview = scene.khmer_narration[:80] + ("…" if len(scene.khmer_narration) > 80 else "")
        table.add_row(
            str(scene.scene_id),
            scene.mood.value,
            str(scene.duration_hint_seconds),
            preview,
        )

    console.print(table)
    console.print(f"\n[success]✓ Saved to: {saved_path}[/success]")


if __name__ == "__main__":
    main()
