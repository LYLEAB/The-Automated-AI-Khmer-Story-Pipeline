"""
renderer.py — MODULE 4: Video Assembly & Subtitle Renderer
Compatible with both MoviePy v1.x and v2.x.
"""
from __future__ import annotations

import os
import random
import re
import textwrap
from pathlib import Path
from typing import List, Optional, Tuple

import click
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Compatible MoviePy imports
try:
    from moviepy.editor import (
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )
except ImportError:
    from moviepy import (
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import config
from models import EnrichedScene, ExportProfile, KenBurnsPreset
from utils import setup_logger, run_logger

logger = setup_logger("renderer")


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    font_path = config.SUBTITLE_FONT_PATH
    try:
        return ImageFont.truetype(font_path, size=size)
    except (IOError, OSError):
        try:
            return ImageFont.truetype("arial.ttf", size=size)
        except Exception:
            return ImageFont.load_default()


def add_subtitle_to_frame(
    frame: np.ndarray,
    text: str,
    frame_w: int,
    frame_h: int,
) -> np.ndarray:
    if not text.strip():
        return frame

    pil_img = Image.fromarray(frame)
    font = _load_font(config.SUBTITLE_FONT_SIZE)

    wrapped = textwrap.fill(text, width=28)
    lines = wrapped.split("\n")

    line_height = config.SUBTITLE_FONT_SIZE + 8
    total_text_h = len(lines) * line_height

    bar_padding = 16
    bar_top = int(frame_h * config.SUBTITLE_POSITION_Y) - bar_padding
    bar_bottom = bar_top + total_text_h + bar_padding * 2

    overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(
        [(0, bar_top), (frame_w, bar_bottom)],
        fill=(0, 0, 0, 150),
    )
    pil_img = Image.alpha_composite(pil_img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(pil_img)

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (frame_w - text_w) // 2
        y = bar_top + bar_padding + i * line_height

        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
            draw.text((x + dx, y + dy), line, font=font, fill=config.SUBTITLE_STROKE_COLOR)
        draw.text((x, y), line, font=font, fill=config.SUBTITLE_FONT_COLOR)

    return np.array(pil_img)


def apply_ken_burns(
    clip: ImageClip,
    preset: KenBurnsPreset,
    target_w: int,
    target_h: int,
) -> ImageClip:
    zoom = config.KEN_BURNS_ZOOM_FACTOR
    duration = clip.duration or 5.0

    oversized_w = int(target_w * zoom)
    oversized_h = int(target_h * zoom)
    extra_x = oversized_w - target_w
    extra_y = oversized_h - target_h

    if preset == KenBurnsPreset.ZOOM_IN:
        def make_frame(t: float) -> np.ndarray:
            prog = t / duration if duration > 0 else 0
            scale = 1.0 + (zoom - 1.0) * prog
            cw, ch = int(target_w * scale), int(target_h * scale)
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((cw, ch), Image.LANCZOS)
            left = (cw - target_w) // 2
            top = (ch - target_h) // 2
            return np.array(img.crop((left, top, left + target_w, top + target_h)))

    elif preset == KenBurnsPreset.ZOOM_OUT:
        def make_frame(t: float) -> np.ndarray:
            prog = t / duration if duration > 0 else 0
            scale = zoom - (zoom - 1.0) * prog
            cw, ch = int(target_w * scale), int(target_h * scale)
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((cw, ch), Image.LANCZOS)
            left = (cw - target_w) // 2
            top = (ch - target_h) // 2
            return np.array(img.crop((left, top, left + target_w, top + target_h)))

    elif preset == KenBurnsPreset.PAN_LEFT:
        def make_frame(t: float) -> np.ndarray:
            prog = t / duration if duration > 0 else 0
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((oversized_w, oversized_h), Image.LANCZOS)
            left = int(extra_x * prog)
            return np.array(img.crop((left, 0, left + target_w, target_h)))

    else:
        def make_frame(t: float) -> np.ndarray:
            prog = t / duration if duration > 0 else 0
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((oversized_w, oversized_h), Image.LANCZOS)
            left = int(extra_x * (1.0 - prog))
            return np.array(img.crop((left, 0, left + target_w, target_h)))

    return clip.fl(lambda gf, t: make_frame(t), apply_to=["mask"])


def build_scene_clip(
    scene: EnrichedScene,
    target_w: int,
    target_h: int,
    image_key: str,
    subtitle_enabled: bool = True,
) -> Optional[ImageClip]:
    sid = scene.scene_id
    suffix = "_mobile.png" if image_key == "mobile" else "_laptop.png"
    img_path = config.IMAGES_DIR / f"scene_{sid}{suffix}"
    audio_path = Path(scene.audio_path) if scene.audio_path else None

    if not img_path.exists() or not audio_path or not audio_path.exists():
        return None

    duration = scene.audio_duration_s
    pil_img = Image.open(img_path).convert("RGB")
    from visual_engine import resize_and_crop
    pil_img = resize_and_crop(pil_img, target_w, target_h)

    # Base clip
    if hasattr(ImageClip, "with_duration"):
        base_clip = ImageClip(np.array(pil_img)).with_duration(duration)
    else:
        base_clip = ImageClip(np.array(pil_img), duration=duration)

    preset = scene.ken_burns_preset or random.choice(list(KenBurnsPreset))
    try:
        animated_clip = apply_ken_burns(base_clip, preset, target_w, target_h)
    except Exception:
        animated_clip = base_clip

    if subtitle_enabled and config.SUBTITLE_ENABLED:
        text = scene.khmer_narration
        animated_clip = animated_clip.fl(lambda gf, t: add_subtitle_to_frame(gf(t), text, target_w, target_h))

    audio_clip = AudioFileClip(str(audio_path))
    if hasattr(animated_clip, "with_audio"):
        final_clip = animated_clip.with_audio(audio_clip).with_fps(config.VIDEO_FPS)
    else:
        final_clip = animated_clip.set_audio(audio_clip).set_fps(config.VIDEO_FPS)

    return final_clip


def mix_background_music(video_clip, total_duration: float):
    music_path = Path(config.BACKGROUND_MUSIC_PATH)
    if not config.BACKGROUND_MUSIC_ENABLED or not music_path.exists():
        return video_clip

    try:
        music_clip = AudioFileClip(str(music_path))
        loops = int(total_duration / music_clip.duration) + 2
        clips = [music_clip] * loops
        try:
            from moviepy.editor import concatenate_audioclips
        except ImportError:
            from moviepy import concatenate_audioclips
        looped = concatenate_audioclips(clips).subclip(0, total_duration)
        narration = video_clip.audio
        mixed = CompositeAudioClip([narration, looped])
        if hasattr(video_clip, "with_audio"):
            return video_clip.with_audio(mixed)
        return video_clip.set_audio(mixed)
    except Exception as exc:
        logger.warning(f"[WARN] Background music mixing skipped: {exc}")
    return video_clip


class VideoRenderer:
    def _assemble(
        self,
        scenes: List[EnrichedScene],
        target_w: int,
        target_h: int,
        image_key: str,
        subtitle_enabled: bool,
    ):
        clips = []
        for scene in scenes:
            clip = build_scene_clip(scene, target_w, target_h, image_key, subtitle_enabled)
            if clip:
                clips.append(clip)

        if not clips:
            raise RuntimeError("No valid scene clips could be built. Check your assets.")

        final = concatenate_videoclips(clips, method="compose")
        return final

    def _export(self, video, output_path: Path, story_title: str) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        video.write_videofile(
            str(output_path),
            codec=config.VIDEO_CODEC,
            audio_codec=config.AUDIO_CODEC,
            bitrate=config.VIDEO_BITRATE,
            fps=config.VIDEO_FPS,
            logger=None,
        )
        return output_path

    def render(
        self,
        scenes: List[EnrichedScene],
        story_title: str,
        profile: ExportProfile = ExportProfile.BOTH,
    ) -> dict[str, str]:
        safe_title = re.sub(r"[^\wក-៿\-_ ]", "", story_title).strip()[:50] or "khmer_story"
        results: dict[str, str] = {}

        if profile in (ExportProfile.MOBILE, ExportProfile.BOTH):
            logger.info(f"[STEP 4/5] Rendering MOBILE 9:16 (1080x1920)...")
            mobile_video = self._assemble(scenes, config.MOBILE_WIDTH, config.MOBILE_HEIGHT, "mobile", True)
            mobile_video = mix_background_music(mobile_video, mobile_video.duration)
            mobile_path = config.VIDEO_DIR / f"{safe_title}{config.MOBILE_SUFFIX}.mp4"
            self._export(mobile_video, mobile_path, safe_title)
            mobile_video.close()
            results["mobile"] = str(mobile_path)

        if profile in (ExportProfile.LAPTOP, ExportProfile.BOTH):
            logger.info(f"[STEP 4/5] Rendering LAPTOP 16:9 (1920x1080)...")
            laptop_video = self._assemble(scenes, config.LAPTOP_WIDTH, config.LAPTOP_HEIGHT, "laptop", True)
            laptop_video = mix_background_music(laptop_video, laptop_video.duration)
            laptop_path = config.VIDEO_DIR / f"{safe_title}{config.LAPTOP_SUFFIX}.mp4"
            self._export(laptop_video, laptop_path, safe_title)
            laptop_video.close()
            results["laptop"] = str(laptop_path)

        return results
