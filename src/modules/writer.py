"""
writer.py — MODULE 1: Script & Scene Parser
Generates structured Khmer story scenes using Google Gemini API.
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
from utils import clean_json_response, retry, run_logger, setup_logger

logger = setup_logger("writer")

SYSTEM_PROMPT = """You are an expert Khmer screenwriter and storyteller.
Your task is to write a compelling, emotionally engaging Khmer narrative story 
divided into exactly {num_scenes} visual scenes.

CRITICAL RULES:
1. ALL narration text MUST be written in authentic Khmer Unicode script.
   Do NOT use transliteration, romanization, or Latin characters in khmer_narration.
2. Each scene narration should be 2-4 sentences (approximately 15-25 seconds of speech).
3. Visual prompts MUST be in English and highly descriptive for AI image generation.
4. Scenes must flow with emotional arc: setup -> rising tension -> climax -> resolution.
5. Return ONLY valid JSON matching the schema below without markdown formatting or code fences.

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


class SceneWriter:
    def __init__(self) -> None:
        if not config.GEMINI_API_KEY:
            raise EnvironmentError("GEMINI_API_KEY is not set. Please add it to your .env file.")
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
        logger.info(f"[INFO] SceneWriter initialized with model: {config.GEMINI_WRITER_MODEL}")

    @retry(max_attempts=config.MAX_RETRY_ATTEMPTS)
    def _call_llm(self, prompt_text: str) -> str:
        run_logger.increment("gemini_calls")
        response = self.model.generate_content(prompt_text)
        return response.text

    def generate(self, story_prompt: str, num_scenes: int = 6) -> SceneList:
        logger.info(f"[STEP 1/5] Generating {num_scenes}-scene script for: '{story_prompt}'")
        formatted_prompt = SYSTEM_PROMPT.format(
            num_scenes=num_scenes,
            prompt=story_prompt,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True,
        ) as progress:
            task = progress.add_task("[cyan]Writing story script with Gemini...[/cyan]", total=None)
            raw_response = self._call_llm(formatted_prompt)
            progress.update(task, completed=True)

        cleaned_json = clean_json_response(raw_response)

        try:
            data = json.loads(cleaned_json)
        except json.JSONDecodeError as exc:
            logger.error(f"[ERROR] Failed to parse LLM JSON response: {exc}")
            raise

        scene_list = SceneList(**data)
        logger.info(f"[SUCCESS] Script generated: '{scene_list.story_title}' ({len(scene_list.scenes)} scenes)")
        return scene_list

    def save(self, scene_list: SceneList, output_path: Optional[Path] = None) -> Path:
        target = output_path or (config.OUTPUT_DIR / "scenes.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(scene_list.model_dump_json(indent=2))
        logger.info(f"[INFO] Saved scenes to {target}")
        return target

    def load(self, input_path: Optional[Path] = None) -> SceneList:
        target = input_path or (config.OUTPUT_DIR / "scenes.json")
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SceneList(**data)


@click.command()
@click.option("--prompt", "-p", required=True, help="Story topic or title in Khmer/English")
@click.option("--scenes", "-s", default=6, help="Number of scenes (default: 6)")
@click.option("--output", "-o", default=None, help="Output JSON path")
def main(prompt: str, scenes: int, output: Optional[str]) -> None:
    writer = SceneWriter()
    out_path = Path(output) if output else None
    scene_list = writer.generate(prompt, scenes)
    writer.save(scene_list, out_path)


if __name__ == "__main__":
    main()
