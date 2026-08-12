"""
renderer.py — MODULE 4: Programmatic Video Assembly & Renderer
==============================================================
Stitches scene images and audio together into publish-ready MP4 videos.

Features:
  • Ken Burns effect (4 cinematic motion presets) on every image
  • Exact audio-synchronized scene durations (from mutagen measurements)
  • Crossfade transitions between scenes
  • Khmer subtitle burn-in using Pillow + Noto Sans Khmer font
  • Optional background ambient music mixing (via pydub)
  • DUAL EXPORT:
      - Mobile  portrait  1080×1920 (9:16)  → for TikTok / Facebook Reels
      - Laptop  landscape 1920×1080 (16:9)  → for desktop / YouTube preview

Usage (standalone):
    python renderer.py --state output/state.json
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
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)
from moviepy.audio.fx.all import audio_loop, volumex
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

import config
from models import EnrichedScene, ExportProfile, KenBurnsPreset
from utils import log, setup_logger, run_logger

logger = setup_logger("renderer")


# ─────────────────────────────────────────────
# SUBTITLE RENDERING (Pillow)
# ─────────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """Load Noto Sans Khmer font, falling back to default if unavailable."""
    font_path = config.SUBTITLE_FONT_PATH
    try:
        return ImageFont.truetype(font_path, size=size)
    except (IOError, OSError):
        logger.warning(
            f"[warning]Khmer font not found at {font_path}. "
            "Download NotoSansKhmer-Regular.ttf to assets/fonts/ for proper rendering.[/warning]"
        )
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
    """
    Burn a Khmer subtitle onto a single video frame using Pillow.

    Args:
        frame: RGB numpy array (H, W, 3) from MoviePy.
        text: Khmer subtitle text for this frame.
        frame_w: Frame width in pixels.
        frame_h: Frame height in pixels.

    Returns:
        Modified RGB numpy array with subtitle burned in.
    """
    pil_img = Image.fromarray(frame)
    draw = ImageDraw.Draw(pil_img)
    font = _load_font(config.SUBTITLE_FONT_SIZE)

    # Word-wrap subtitle text
    wrapped = textwrap.fill(text, width=28)
    lines = wrapped.split("\n")

    # Calculate total text block height
    line_height = config.SUBTITLE_FONT_SIZE + 8
    total_text_h = len(lines) * line_height

    # Semi-transparent background bar
    bar_padding = 16
    bar_top = int(frame_h * config.SUBTITLE_POSITION_Y) - bar_padding
    bar_bottom = bar_top + total_text_h + bar_padding * 2
    overlay = Image.new("RGBA", pil_img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(
        [(0, bar_top), (frame_w, bar_bottom)],
        fill=(0, 0, 0, 140),   # 55% opacity black bar
    )
    pil_img = Image.alpha_composite(pil_img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(pil_img)

    # Render each text line centered
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (frame_w - text_w) // 2
        y = bar_top + bar_padding + i * line_height

        # Drop shadow / stroke
        for dx, dy in [(-2, -2), (2, -2), (-2, 2), (2, 2)]:
            draw.text(
                (x + dx, y + dy),
                line,
                font=font,
                fill=config.SUBTITLE_STROKE_COLOR,
            )
        draw.text((x, y), line, font=font, fill=config.SUBTITLE_FONT_COLOR)

    return np.array(pil_img)


# ─────────────────────────────────────────────
# KEN BURNS EFFECT
# ─────────────────────────────────────────────

def apply_ken_burns(
    clip: ImageClip,
    preset: KenBurnsPreset,
    target_w: int,
    target_h: int,
) -> ImageClip:
    """
    Apply a cinematic Ken Burns motion effect to a static ImageClip.

    The image is slightly oversized (by KEN_BURNS_ZOOM_FACTOR) so motion
    never reveals black borders.

    Args:
        clip: MoviePy ImageClip to animate.
        preset: One of zoom_in, zoom_out, pan_left, pan_right.
        target_w: Final output frame width.
        target_h: Final output frame height.

    Returns:
        Animated ImageClip with Ken Burns applied.
    """
    zoom = config.KEN_BURNS_ZOOM_FACTOR
    duration = clip.duration

    # Oversized canvas for motion headroom
    oversized_w = int(target_w * zoom)
    oversized_h = int(target_h * zoom)
    extra_x = oversized_w - target_w
    extra_y = oversized_h - target_h

    if preset == KenBurnsPreset.ZOOM_IN:
        def make_frame(t: float) -> np.ndarray:
            progress = t / duration
            scale = 1.0 + (zoom - 1.0) * progress
            current_w = int(target_w * scale)
            current_h = int(target_h * scale)
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((current_w, current_h), Image.LANCZOS)
            # Center crop back to target
            left = (current_w - target_w) // 2
            top = (current_h - target_h) // 2
            return np.array(img.crop((left, top, left + target_w, top + target_h)))

    elif preset == KenBurnsPreset.ZOOM_OUT:
        def make_frame(t: float) -> np.ndarray:
            progress = t / duration
            scale = zoom - (zoom - 1.0) * progress
            current_w = int(target_w * scale)
            current_h = int(target_h * scale)
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((current_w, current_h), Image.LANCZOS)
            left = (current_w - target_w) // 2
            top = (current_h - target_h) // 2
            return np.array(img.crop((left, top, left + target_w, top + target_h)))

    elif preset == KenBurnsPreset.PAN_LEFT:
        def make_frame(t: float) -> np.ndarray:
            progress = t / duration
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((oversized_w, oversized_h), Image.LANCZOS)
            left = int(extra_x * progress)
            return np.array(img.crop((left, 0, left + target_w, target_h)))

    else:  # PAN_RIGHT
        def make_frame(t: float) -> np.ndarray:
            progress = t / duration
            frame = clip.get_frame(t)
            img = Image.fromarray(frame).resize((oversized_w, oversized_h), Image.LANCZOS)
            left = int(extra_x * (1.0 - progress))
            return np.array(img.crop((left, 0, left + target_w, target_h)))

    return clip.fl(lambda gf, t: make_frame(t), apply_to=["mask"])


# ─────────────────────────────────────────────
# SCENE CLIP BUILDER
# ─────────────────────────────────────────────

def build_scene_clip(
    scene: EnrichedScene,
    target_w: int,
    target_h: int,
    image_key: str,
    subtitle_enabled: bool = True,
) -> Optional[ImageClip]:
    """
    Build a single MoviePy clip for one scene (image + audio + subtitles + Ken Burns).

    Args:
        scene: EnrichedScene with audio_path and image_path populated.
        target_w / target_h: Output resolution.
        image_key: "mobile" or "laptop" — selects which pre-rendered image to use.
        subtitle_enabled: Whether to burn Khmer subtitles into the frame.

    Returns:
        Composed ImageClip, or None if assets are missing.
    """
    # Determine correct image path
    sid = scene.scene_id
    if image_key == "mobile":
        img_path = config.IMAGES_DIR / f"scene_{sid}_mobile.png"
    else:
        img_path = config.IMAGES_DIR / f"scene_{sid}_laptop.png"

    audio_path = Path(scene.audio_path) if scene.audio_path else None

    if not img_path.exists():
        logger.warning(f"[warning]Scene {sid}: Image not found at {img_path}, skipping.[/warning]")
        return None
    if not audio_path or not audio_path.exists():
        logger.warning(f"[warning]Scene {sid}: Audio not found, skipping.[/warning]")
        return None

    duration = scene.audio_duration_s

    # Load and resize image to target resolution
    pil_img = Image.open(img_path).convert("RGB")
    from visual_engine import resize_and_crop
    pil_img = resize_and_crop(pil_img, target_w, target_h)

    # Create base ImageClip
    base_clip = ImageClip(np.array(pil_img), duration=duration)

    # Apply Ken Burns effect
    preset = scene.ken_burns_preset or random.choice(list(KenBurnsPreset))
    try:
        animated_clip = apply_ken_burns(base_clip, preset, target_w, target_h)
    except Exception as exc:
        logger.warning(f"[warning]Ken Burns failed for scene {sid}: {exc}. Using static image.[/warning]")
        animated_clip = base_clip

    # Burn subtitles into frames
    if subtitle_enabled and config.SUBTITLE_ENABLED:
        narration = scene.khmer_narration
        def frame_with_subtitle(gf, t):
            frame = gf(t)
            return add_subtitle_to_frame(frame, narration, target_w, target_h)
        animated_clip = animated_clip.fl(frame_with_subtitle)

    # Attach audio
    audio_clip = AudioFileClip(str(audio_path))
    final_clip = animated_clip.set_audio(audio_clip).set_fps(config.VIDEO_FPS)

    logger.info(
        f"[scene]Scene {sid}: clip built "
        f"({duration:.1f}s, {target_w}×{target_h}, preset={preset.value})[/scene]"
    )
    return final_clip


# ─────────────────────────────────────────────
# BACKGROUND MUSIC MIXER
# ─────────────────────────────────────────────

def mix_background_music(video_clip, total_duration: float):
    """
    Overlay looped ambient background music at reduced volume beneath narration.

    Args:
        video_clip: The assembled video clip (has narration audio already).
        total_duration: Total video duration in seconds.

    Returns:
        Video clip with mixed audio, or original clip if music is unavailable.
    """
    music_path = Path(config.BACKGROUND_MUSIC_PATH)
    if not config.BACKGROUND_MUSIC_ENABLED or not music_path.exists():
        logger.info("[info]Background music skipped (disabled or file not found).[/info]")
        return video_clip

    try:
        music_clip = AudioFileClip(str(music_path))
        # Loop music to cover full video duration
        loops_needed = int(total_duration / music_clip.duration) + 2
        from moviepy.editor import concatenate_audioclips
        looped_music = concatenate_audioclips([music_clip] * loops_needed).subclip(0, total_duration)
        # Convert dB to linear volume factor
        vol_factor = 10 ** (config.BACKGROUND_MUSIC_VOLUME_DB / 20)
        quiet_music = looped_music.fx(volumex, vol_factor)
        # Composite narration + music
        narration = video_clip.audio
        mixed = CompositeAudioClip([narration, quiet_music])
        logger.info(
            f"[success]✓ Background music mixed at {config.BACKGROUND_MUSIC_VOLUME_DB} dB[/success]"
        )
        return video_clip.set_audio(mixed)
    except Exception as exc:
        logger.warning(f"[warning]Background music mixing failed: {exc}[/warning]")
        return video_clip


# ─────────────────────────────────────────────
# VIDEO RENDERER
# ─────────────────────────────────────────────

class VideoRenderer:
    """
    Assembles all scene clips into final MP4 videos.
    Exports both mobile (9:16) and laptop (16:9) versions.
    """

    def _assemble(
        self,
        scenes: List[EnrichedScene],
        target_w: int,
        target_h: int,
        image_key: str,
        subtitle_enabled: bool,
    ):
        """Build and concatenate all scene clips."""
        clips = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
        ) as progress:
            task = progress.add_task(
                f"🎬 Building {image_key} clips ({target_w}×{target_h})…",
                total=len(scenes),
            )
            for scene in scenes:
                clip = build_scene_clip(scene, target_w, target_h, image_key, subtitle_enabled)
                if clip:
                    # Apply crossfade
                    if clips:
                        clip = clip.crossfadein(config.CROSSFADE_DURATION)
                    clips.append(clip)
                progress.advance(task)

        if not clips:
            raise RuntimeError("No valid scene clips were built. Check your assets.")

        final = concatenate_videoclips(clips, method="compose", padding=-config.CROSSFADE_DURATION)
        return final

    def _export(
        self,
        video,
        output_path: Path,
        story_title: str,
    ) -> Path:
        """Write the final video to disk."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"[info]Exporting video → {output_path.name}[/info]")
        video.write_videofile(
            str(output_path),
            codec=config.VIDEO_CODEC,
            audio_codec=config.AUDIO_CODEC,
            bitrate=config.VIDEO_BITRATE,
            audio_bitrate=config.AUDIO_BITRATE,
            fps=config.VIDEO_FPS,
            logger=None,    # Suppress moviepy's default verbose output
        )
        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(
            f"[success]✓ Exported: {output_path.name} ({size_mb:.1f} MB)[/success]"
        )
        return output_path

    def render(
        self,
        scenes: List[EnrichedScene],
        story_title: str,
        profile: ExportProfile = ExportProfile.BOTH,
    ) -> dict[str, str]:
        """
        Render the final video(s) from enriched scenes.

        Args:
            scenes: List of EnrichedScene with all assets populated.
            story_title: Used in the output filename.
            profile: ExportProfile.MOBILE, LAPTOP, or BOTH.

        Returns:
            Dict with 'mobile' and/or 'laptop' keys pointing to output MP4 paths.
        """
        # Sanitize title for filename
        safe_title = re.sub(r"[^\w\u1780-\u17FF\-_ ]", "", story_title).strip()[:50]
        if not safe_title:
            safe_title = "khmer_story"

        results: dict[str, str] = {}

        # ── MOBILE 9:16 ──────────────────────────────────────
        if profile in (ExportProfile.MOBILE, ExportProfile.BOTH):
            logger.info("[step]─── Rendering MOBILE (9:16) 1080×1920 ───[/step]")
            mobile_video = self._assemble(
                scenes, config.MOBILE_WIDTH, config.MOBILE_HEIGHT,
                image_key="mobile", subtitle_enabled=True,
            )
            total_dur = mobile_video.duration
            mobile_video = mix_background_music(mobile_video, total_dur)
            mobile_path = config.VIDEO_DIR / f"{safe_title}{config.MOBILE_SUFFIX}.mp4"
            self._export(mobile_video, mobile_path, safe_title)
            mobile_video.close()
            results["mobile"] = str(mobile_path)

        # ── LAPTOP 16:9 ───────────────────────────────────────
        if profile in (ExportProfile.LAPTOP, ExportProfile.BOTH):
            logger.info("[step]─── Rendering LAPTOP (16:9) 1920×1080 ───[/step]")
            laptop_video = self._assemble(
                scenes, config.LAPTOP_WIDTH, config.LAPTOP_HEIGHT,
                image_key="laptop", subtitle_enabled=True,
            )
            total_dur = laptop_video.duration
            laptop_video = mix_background_music(laptop_video, total_dur)
            laptop_path = config.VIDEO_DIR / f"{safe_title}{config.LAPTOP_SUFFIX}.mp4"
            self._export(laptop_video, laptop_path, safe_title)
            laptop_video.close()
            results["laptop"] = str(laptop_path)

        return results


# ─────────────────────────────────────────────
# CLI ENTRY POINT
# ─────────────────────────────────────────────

@click.command()
@click.option(
    "--state", "-s",
    default=str(config.STATE_FILE),
    show_default=True,
    help="Path to pipeline state.json",
)
@click.option(
    "--profile", "-p",
    type=click.Choice(["mobile", "laptop", "both"], case_sensitive=False),
    default="both",
    show_default=True,
    help="Export profile",
)
def main(state: str, profile: str) -> None:
    """MODULE 4: Render final video(s) from pipeline state."""
    import json
    from utils import ensure_output_dirs, console
    from models import PipelineState

    ensure_output_dirs()
    state_path = Path(state)
    if not state_path.exists():
        logger.error(f"[error]State file not found: {state_path}[/error]")
        raise SystemExit(1)

    with open(state_path, "r", encoding="utf-8") as f:
        pipeline_state = PipelineState.model_validate(json.load(f))

    export_profile = ExportProfile(profile)
    renderer = VideoRenderer()
    results = renderer.render(
        scenes=pipeline_state.enriched_scenes,
        story_title=pipeline_state.story_title or "khmer_story",
        profile=export_profile,
    )

    console.print("\n[success]✓ Rendering complete![/success]")
    for k, v in results.items():
        console.print(f"  [{k.upper()}] → {v}")


if __name__ == "__main__":
    main()
