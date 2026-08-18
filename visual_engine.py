"""
visual_engine.py — MODULE 3: Visual Asset Generator
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
from utils import retry, run_logger, setup_logger

logger = setup_logger("visual_engine")


def build_full_prompt(visual_prompt: str) -> str:
    return f"{visual_prompt.strip()}, {config.IMAGE_STYLE_SUFFIX}"


def resize_and_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def save_image_variants(img: Image.Image, scene_id: int) -> dict[str, str]:
    paths: dict[str, str] = {}
    config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    mobile_img = resize_and_crop(img.copy(), config.MOBILE_WIDTH, config.MOBILE_HEIGHT)
    mobile_path = config.IMAGES_DIR / f"scene_{scene_id}_mobile.png"
    mobile_img.save(str(mobile_path), "PNG", optimize=True)
    paths["mobile"] = str(mobile_path)

    laptop_img = resize_and_crop(img.copy(), config.LAPTOP_WIDTH, config.LAPTOP_HEIGHT)
    laptop_path = config.IMAGES_DIR / f"scene_{scene_id}_laptop.png"
    laptop_img.save(str(laptop_path), "PNG", optimize=True)
    paths["laptop"] = str(laptop_path)
    return paths


class GeminiImagenProvider:
    def __init__(self) -> None:
        import google.generativeai as genai
        if not config.GEMINI_API_KEY:
            raise EnvironmentError("GEMINI_API_KEY is not set.")
        genai.configure(api_key=config.GEMINI_API_KEY)
        self.model_name = config.GEMINI_IMAGEN_MODEL
        logger.info(f"[INFO] Imagen provider initialized ({self.model_name})")

    @retry(max_attempts=3)
    def generate(self, prompt: str) -> Image.Image:
        run_logger.increment("image_calls")
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            result = client.models.generate_images(
                model=self.model_name,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    output_mime_type="image/png",
                    aspect_ratio="1:1",
                ),
            )
            image_bytes = result.generated_images[0].image.image_bytes
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            return Image.new("RGB", (1024, 1024), color=(30, 40, 50))


class StabilityAIProvider:
    def __init__(self) -> None:
        if not config.STABILITY_API_KEY:
            raise EnvironmentError("STABILITY_API_KEY is not set.")
        self.api_key = config.STABILITY_API_KEY
        self.engine_id = config.STABILITY_ENGINE_ID
        self.api_host = config.STABILITY_API_HOST
        logger.info(f"[INFO] Stability AI provider initialized ({self.engine_id})")

    @retry()
    def generate(self, prompt: str) -> Image.Image:
        run_logger.increment("image_calls")
        url = f"{self.api_host}/v1/generation/{self.engine_id}/text-to-image"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "text_prompts": [
                {"text": prompt, "weight": 1.0},
                {"text": "blurry, low quality, distorted, text, watermark", "weight": -1.0},
            ],
            "cfg_scale": 7.5,
            "height": 1024,
            "width": 1024,
            "samples": 1,
            "steps": 30,
            "seed": config.IMAGE_SEED,
        }
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        artifact = data["artifacts"][0]
        image_bytes = base64.b64decode(artifact["base64"])
        return Image.open(io.BytesIO(image_bytes)).convert("RGB")


def get_image_provider(name: Optional[str] = None):
    provider_name = name or config.IMAGE_PROVIDER
    if provider_name == "stability_ai":
        try:
            return StabilityAIProvider()
        except Exception:
            return GeminiImagenProvider()
    return GeminiImagenProvider()


class VisualEngine:
    def __init__(self, provider_override: Optional[str] = None) -> None:
        self.provider = get_image_provider(provider_override)

    def process_scene(self, scene: EnrichedScene, skip_existing: bool = False) -> EnrichedScene:
        config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        sid = scene.scene_id
        m_path = config.IMAGES_DIR / f"scene_{sid}_mobile.png"
        l_path = config.IMAGES_DIR / f"scene_{sid}_laptop.png"

        if skip_existing and m_path.exists() and l_path.exists():
            scene.image_path = str(m_path)
            return scene

        full_prompt = build_full_prompt(scene.visual_prompt)
        img = self.provider.generate(full_prompt)
        paths = save_image_variants(img, scene.scene_id)
        scene.image_path = paths["mobile"]
        return scene

    def process_all(
        self,
        scenes: List[EnrichedScene],
        skip_existing: bool = False,
    ) -> List[EnrichedScene]:
        config.IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        import concurrent.futures

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task("[cyan]Generating scene artwork...[/cyan]", total=len(scenes))
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(self.process_scene, scene, skip_existing): scene
                    for scene in scenes
                }
                for future in concurrent.futures.as_completed(futures):
                    future.result() # updates the scene object in-place
                    progress.advance(task)
                    
        return scenes

    def process_scenes(self, scenes: List[EnrichedScene], skip_existing: bool = False) -> List[EnrichedScene]:
        return self.process_all(scenes, skip_existing=skip_existing)


@click.command()
@click.option("--scenes", "-s", default="output/scenes.json", help="Path to scenes.json")
def main(scenes: str) -> None:
    from writer import SceneWriter
    writer = SceneWriter()
    scene_list = writer.load(Path(scenes))
    enriched = [EnrichedScene(**s.model_dump()) for s in scene_list.scenes]
    engine = VisualEngine()
    engine.process_all(enriched)


if __name__ == "__main__":
    main()
