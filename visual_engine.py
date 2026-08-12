"""
visual_engine.py — MODULE 3: Visual Asset Generator
=====================================================
Generates one AI image per scene using a tiered provider strategy:
  1. Google Gemini Imagen 3 (via google-genai SDK) — primary
  2. Stability AI / SDXL (via REST API)            — fallback

Each visual_prompt is augmented with cinematic style anchors before sending.
Generated images are resized/cropped to the required output resolutions using Pillow.

Both portrait (1080×1920) and landscape (1920×1080) versions are saved so the
renderer can use them for the mobile and laptop export profiles.

Usage (standalone):
    python visual_engine.py --scenes output/scenes.json
"""

from __future__ import annotations

import base64
import io
import random
from pathlib import Path
from typing import List, Optional

import click
import requests
from PIL import Image
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import config
from models import EnrichedScene, SceneList
from utils import log, retry, run_logger, setup_logger

logger = setup_logger("visual_engine")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def build_full_prompt(visual_prompt: str) -> str:
    """Append consistent style anchors to an image generation prompt."""
    return f"{visual_prompt.strip()}, {config.IMAGE_STYLE_SUFFIX}"


def resize_and_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """
    Resize and center-crop an image to exact target dimensions,
    preserving aspect ratio as much as possible.
    """
    src_w, src_h = img.size
    # Scale so the shortest side fills the target
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    # Center crop
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def save_image_variants(img: Image.Image, scene_id: int) -> dict[str, str]:
    """
    Save both mobile (portrait 9:16) and laptop (landscape 16:9) versions.

    Returns:
        Dict with 'mobile' and 'laptop' keys pointing to saved file paths.
    """
    paths: dict[str, str] = {}

    # Mobile portrait: 1080×1920
    mobile_img = resize_and_crop(img.copy(), config.MOBILE_WIDTH, config.MOBILE_HEIGHT)
    mobile_path = config.IMAGES_DIR / f"scene_{scene_id}_mobile.png"
    mobile_img.save(str(mobile_path), "PNG", optimize=True)
    paths["mobile"] = str(mobile_path)

    # Laptop landscape: 1920×1080
    laptop_img = resize_and_crop(img.copy(), config.LAPTOP_WIDTH, config.LAPTOP_HEIGHT)
    laptop_path = config.IMAGES_DIR / f"scene_{scene_id}_laptop.png"
    laptop_img.save(str(laptop_path), "PNG", optimize=True)
    paths["laptop"] = str(laptop_path)

    return paths


# ─────────────────────────────────────────────
# IMAGE PROVIDER: GOOGLE GEMINI IMAGEN
# ─────────────────────────────────────────────

class GeminiImagenProvider:
    """Google Gemini Imagen 3 — primary image generation provider."""

    def __init__(self) -> None:
        import google.generativeai as genai
        if not config.GEMINI_API_KEY:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        genai.configure(api_key=config.GEMINI_API_KEY)
        # Imagen is accessed via the new google-genai SDK
        try:
            from google import genai as new_genai
            self.client = new_genai.Client(api_key=config.GEMINI_API_KEY)
            self.model = config.GEMINI_IMAGEN_MODEL
            logger.info(f"[info]Gemini Imagen provider ready ({self.model})[/info]")
        except ImportError:
            raise ImportError(
                "Install 'google-genai' package for Imagen support: pip install google-genai"
            )

    @retry()
    def generate(self, prompt: str, scene_id: int) -> Image.Image:
        from google.genai import types
        response = self.client.models.generate_images(
            model=self.model,
            prompt=prompt,
            config=types.GenerateImagesConfig(
                number_of_images=1,
                aspect_ratio="9:16",        # Native portrait for mobile
                safety_filter_level="BLOCK_ONLY_HIGH",
                person_generation="ALLOW_ADULT",
            ),
        )
        # Extract image bytes from response
        image_bytes = response.generated_images[0].image.image_bytes
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")


# ─────────────────────────────────────────────
# IMAGE PROVIDER: STABILITY AI / SDXL
# ─────────────────────────────────────────────

class StabilityAIProvider:
    """Stability AI SDXL — high-quality fallback image generator."""

    def __init__(self) -> None:
        if not config.STABILITY_API_KEY:
            raise EnvironmentError("STABILITY_API_KEY is not set.")
        self.api_key = config.STABILITY_API_KEY
        self.api_host = config.STABILITY_API_HOST
        self.engine_id = config.STABILITY_ENGINE_ID
        logger.info(f"[info]Stability AI provider ready ({self.engine_id})[/info]")

    @retry()
    def generate(self, prompt: str, scene_id: int) -> Image.Image:
        url = f"{self.api_host}/v1/generation/{self.engine_id}/text-to-image"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "text_prompts": [
                {"text": prompt, "weight": 1.0},
                {"text": "blurry, low quality, deformed, western art, cartoon", "weight": -1.0},
            ],
            "cfg_scale": 7,
            "height": 1344,     # Closest SDXL size to 9:16
            "width": 768,
            "samples": 1,
            "steps": 30,
            "seed": config.IMAGE_SEED + scene_id,   # Vary seed per scene
        }
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        img_b64 = data["artifacts"][0]["base64"]
        img_bytes = base64.b64decode(img_b64)
        return Image.open(io.BytesIO(img_bytes)).convert("RGB")


# ─────────────────────────────────────────────
# IMAGE PROVIDER FACTORY
# ─────────────────────────────────────────────

def get_image_provider():
    """Return the configured image provider with graceful fallback."""
    provider_name = config.IMAGE_PROVIDER.lower()

    if provider_name == "gemini_imagen":
        try:
            return GeminiImagenProvider()
        except Exception as exc:
            logger.warning(f"[warning]Gemini Imagen unavailable ({exc}), trying Stability AI…[/warning]")

    try:
        return StabilityAIProvider()
    except Exception as exc:
        raise RuntimeError(
            f"No image generation provider available. "
            f"Set IMAGE_PROVIDER and API keys in your .env file. Error: {exc}"
        ) from exc


# ─────────────────────────────────────────────
# VISUAL ENGINE
# ─────────────────────────────────────────────

class VisualEngine:
    """
    Orchestrates AI image generation for all scenes.
    Saves both portrait and landscape variants of each image.
    """

    def __init__(self) -> None:
        self.provider = get_image_provider()

    def get_image_paths(self, scene_id: int) -> dict[str, Path]:
        return {
            "mobile": config.IMAGES_DIR / f"scene_{scene_id}_mobile.png",
            "laptop": config.IMAGES_DIR / f"scene_{scene_id}_laptop.png",
        }

    def process_scene(
        self,
        scene: EnrichedScene,
        skip_existing: bool = True,
    ) -> EnrichedScene:
        """
        Generate and save image assets for a single scene.

        Args:
            scene: An EnrichedScene (already has audio data).
            skip_existing: Skip generation if images already exist.

        Returns:
            EnrichedScene with image_path (mobile portrait) populated.
        """
        paths = self.get_image_paths(scene.scene_id)
        mobile_path = paths["mobile"]

        if skip_existing and mobile_path.exists() and paths["laptop"].exists():
            logger.info(f"[info]Scene {scene.scene_id}: Images already exist, skipping.[/info]")
            return scene.model_copy(update={"image_path": str(mobile_path)})

        full_prompt = build_full_prompt(scene.visual_prompt)
        logger.info(
            f"[scene]Scene {scene.scene_id}: Generating image…[/scene]\n"
            f"  Prompt: {full_prompt[:100]}…"
        )

        config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        img = self.provider.generate(full_prompt, scene.scene_id)
        saved = save_image_variants(img, scene.scene_id)
        run_logger.increment("image_gen_calls")

        logger.info(
            f"[success]✓ Scene {scene.scene_id}: Images saved "
            f"(mobile: {Path(saved['mobile']).name}, laptop: {Path(saved['laptop']).name})[/success]"
        )
        return scene.model_copy(update={"image_path": saved["mobile"]})

    def process_all(
        self,
        enriched_scenes: List[EnrichedScene],
        done_scene_ids: Optional[List[int]] = None,
    ) -> List[EnrichedScene]:
        """
        Generate images for all scenes.

        Args:
            enriched_scenes: Scenes with audio data already attached.
            done_scene_ids: Already-completed scene IDs (for resumable runs).

        Returns:
            Updated list of EnrichedScenes with image_path populated.
        """
        skip_ids = set(done_scene_ids or [])
        result: List[EnrichedScene] = []

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task(
                "🎨  Generating scene images…", total=len(enriched_scenes)
            )
            for scene in enriched_scenes:
                skip = scene.scene_id in skip_ids
                updated = self.process_scene(scene, skip_existing=skip)
                result.append(updated)
                progress.advance(task)

        logger.info(f"[success]✓ All {len(result)} scene images generated.[/success]")
        return result


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

@click.command()
@click.option(
    "--scenes", "-s",
    default=str(config.OUTPUT_DIR / "scenes.json"),
    show_default=True,
    help="Path to scenes.json",
)
def main(scenes: str) -> None:
    """MODULE 3: Generate AI images for all scenes."""
    import json
    from utils import ensure_output_dirs, console
    from models import SceneList
    from rich.table import Table

    ensure_output_dirs()
    scenes_path = Path(scenes)
    if not scenes_path.exists():
        logger.error(f"[error]Scenes file not found: {scenes_path}[/error]")
        raise SystemExit(1)

    with open(scenes_path, "r", encoding="utf-8") as f:
        scene_list = SceneList.model_validate(json.load(f))

    # Wrap plain Scenes into EnrichedScenes for this standalone run
    enriched = [EnrichedScene(**s.model_dump()) for s in scene_list.scenes]

    engine = VisualEngine()
    result = engine.process_all(enriched)

    table = Table(title="🎨 Image Generation Results", border_style="magenta")
    table.add_column("Scene", style="bold cyan", width=6)
    table.add_column("Mobile (9:16)", width=30)
    table.add_column("Laptop (16:9)", width=30)

    for e in result:
        sid = e.scene_id
        mobile = config.IMAGES_DIR / f"scene_{sid}_mobile.png"
        laptop = config.IMAGES_DIR / f"scene_{sid}_laptop.png"
        table.add_row(
            str(sid),
            f"✓ {mobile.name}" if mobile.exists() else "✗ missing",
            f"✓ {laptop.name}" if laptop.exists() else "✗ missing",
        )
    console.print(table)


if __name__ == "__main__":
    main()
