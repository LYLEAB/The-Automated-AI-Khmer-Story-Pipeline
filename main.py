"""
main.py — Pipeline Orchestrator & CLI Entry Point
==================================================
Ties all 5 modules together into a single end-to-end pipeline run.

Features:
  • Resumable state (crash-safe — skips already-generated assets)
  • Real-time Rich progress display
  • Dual-profile video export (mobile 9:16 + laptop 16:9)
  • Run cost/analytics log
  • Batch mode (--batch stories.txt)

Usage:
    # Single story
    python main.py --prompt "រឿងកុលាបប៉ៃលិន" --scenes 6

    # Short test run
    python main.py --prompt "A brave Khmer princess" --scenes 3 --test

    # Choose export profile
    python main.py --prompt "..." --scenes 6 --profile mobile

    # Batch mode (one prompt per line in stories.txt)
    python main.py --batch stories.txt
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import List, Optional

import click
from rich.panel import Panel
from rich.rule import Rule

import config
from models import EnrichedScene, ExportProfile, PipelineState, SceneList
from utils import (
    console,
    ensure_output_dirs,
    load_state,
    run_logger,
    save_state,
    setup_logger,
)

logger = setup_logger("main")


# ─────────────────────────────────────────────
# PIPELINE RUNNER
# ─────────────────────────────────────────────

class KhmerStoryPipeline:
    """
    End-to-end orchestrator for the Automated AI Khmer Story Pipeline.
    Each step is state-tracked for resumability.
    """

    def __init__(
        self,
        story_prompt: str,
        num_scenes: int = 6,
        export_profile: ExportProfile = ExportProfile.BOTH,
        test_mode: bool = False,
    ) -> None:
        self.story_prompt = story_prompt
        self.num_scenes = min(num_scenes, 3 if test_mode else config.MAX_SCENES)
        self.export_profile = export_profile
        self.test_mode = test_mode
        ensure_output_dirs()

    def _print_header(self) -> None:
        console.print(
            Panel(
                f"[bold cyan]🎬 Automated AI Khmer Story Pipeline[/bold cyan]\n\n"
                f"[white]Prompt :[/white]  [yellow]{self.story_prompt}[/yellow]\n"
                f"[white]Scenes  :[/white]  {self.num_scenes}\n"
                f"[white]Export  :[/white]  {self.export_profile.value.upper()}\n"
                f"[white]Test mode:[/white] {'✓ ON (3 scenes max)' if self.test_mode else 'OFF'}",
                title="[bold magenta]✨ Khmer Story Pipeline[/bold magenta]",
                border_style="magenta",
                padding=(1, 4),
            )
        )

    # ── STEP 1: SCENE GENERATION ──────────────────────────

    def step_write(self, state: PipelineState) -> SceneList:
        run_logger.print_section("STEP 1 / 5 — Script & Scene Generation")

        if state.scenes_generated and (config.OUTPUT_DIR / "scenes.json").exists():
            logger.info("[info]Scenes already generated — loading from disk.[/info]")
            from writer import SceneWriter
            return SceneWriter().load()

        from writer import SceneWriter
        writer = SceneWriter()
        scene_list = writer.generate(self.story_prompt, self.num_scenes)
        writer.save(scene_list)

        state.scenes_generated = True
        state.story_title = scene_list.story_title
        state.enriched_scenes = [
            EnrichedScene(**s.model_dump()) for s in scene_list.scenes
        ]
        save_state(state)
        return scene_list

    # ── STEP 2: TTS AUDIO ─────────────────────────────────

    def step_audio(
        self, state: PipelineState, scene_list: SceneList
    ) -> List[EnrichedScene]:
        run_logger.print_section("STEP 2 / 5 — Text-to-Speech Audio Generation")

        from audio_engine import AudioEngine
        engine = AudioEngine()
        enriched = engine.process_all(scene_list, done_scene_ids=state.audio_done_scenes)

        # Merge results into state
        state_map = {e.scene_id: e for e in state.enriched_scenes}
        for e in enriched:
            state_map[e.scene_id] = e
            state.mark_audio_done(e.scene_id)
        state.enriched_scenes = sorted(state_map.values(), key=lambda x: x.scene_id)
        save_state(state)
        return state.enriched_scenes

    # ── STEP 3: IMAGE GENERATION ───────────────────────────

    def step_images(self, state: PipelineState) -> List[EnrichedScene]:
        run_logger.print_section("STEP 3 / 5 — Visual Asset Generation")

        from visual_engine import VisualEngine
        engine = VisualEngine()
        updated = engine.process_all(
            state.enriched_scenes,
            done_scene_ids=state.images_done_scenes,
        )

        state_map = {e.scene_id: e for e in state.enriched_scenes}
        for e in updated:
            state_map[e.scene_id] = e
            state.mark_image_done(e.scene_id)
        state.enriched_scenes = sorted(state_map.values(), key=lambda x: x.scene_id)
        save_state(state)
        return state.enriched_scenes

    # ── STEP 4: VIDEO RENDERING ────────────────────────────

    def step_render(self, state: PipelineState) -> dict[str, str]:
        run_logger.print_section("STEP 4 / 5 — Video Assembly & Rendering")

        # Skip rendering if we have already exported this profile
        if (
            self.export_profile == ExportProfile.MOBILE
            and state.video_mobile_path
            and Path(state.video_mobile_path).exists()
        ):
            logger.info("[info]Mobile video already rendered.[/info]")
            return {"mobile": state.video_mobile_path}

        if (
            self.export_profile == ExportProfile.LAPTOP
            and state.video_laptop_path
            and Path(state.video_laptop_path).exists()
        ):
            logger.info("[info]Laptop video already rendered.[/info]")
            return {"laptop": state.video_laptop_path}

        from renderer import VideoRenderer
        renderer = VideoRenderer()
        results = renderer.render(
            scenes=state.enriched_scenes,
            story_title=state.story_title or "khmer_story",
            profile=self.export_profile,
        )

        if "mobile" in results:
            state.video_mobile_path = results["mobile"]
        if "laptop" in results:
            state.video_laptop_path = results["laptop"]
        save_state(state)
        return results

    # ── STEP 5: METADATA / PUBLISHER ───────────────────────

    def step_publish(
        self, state: PipelineState, video_paths: dict[str, str]
    ) -> None:
        run_logger.print_section("STEP 5 / 5 — Social Media Metadata Generation")

        if state.metadata_done and (config.METADATA_DIR / "metadata.json").exists():
            logger.info("[info]Metadata already generated.[/info]")
            return

        total_duration = sum(
            e.audio_duration_s for e in state.enriched_scenes
        )

        from publisher import MetadataPublisher
        publisher = MetadataPublisher()
        metadata = publisher.generate(
            story_title=state.story_title,
            story_title_en="",
            num_scenes=len(state.enriched_scenes),
            duration_seconds=total_duration,
        )
        publisher.print_preview(metadata)
        publisher.save(metadata, story_title=state.story_title, video_paths=video_paths)

        state.metadata_done = True
        save_state(state)

    # ── FULL PIPELINE RUN ──────────────────────────────────

    def run(self) -> None:
        """Execute the complete pipeline end-to-end."""
        self._print_header()
        start = time.time()

        # Load or initialize pipeline state
        state = load_state(self.story_prompt) or PipelineState(story_prompt=self.story_prompt)

        # Execute each step
        scene_list = self.step_write(state)
        self.step_audio(state, scene_list)
        self.step_images(state)
        video_paths = self.step_render(state)
        self.step_publish(state, video_paths)

        # Finalize
        run_logger.finalize()
        elapsed = time.time() - start

        console.print(Rule(style="magenta"))
        console.print(
            Panel(
                "[bold green]🎉 PIPELINE COMPLETE![/bold green]\n\n"
                + "".join(
                    f"[white]{'📱 Mobile' if k == 'mobile' else '💻 Laptop'} :[/white] "
                    f"[cyan]{v}[/cyan]\n"
                    for k, v in video_paths.items()
                )
                + f"\n[white]Metadata :[/white] [cyan]{config.METADATA_DIR / 'caption.txt'}[/cyan]\n"
                + f"\n[dim]Total time: {elapsed:.1f}s[/dim]",
                title="[bold magenta]✅ Output Summary[/bold magenta]",
                border_style="green",
                padding=(1, 4),
            )
        )


# ─────────────────────────────────────────────
# BATCH MODE
# ─────────────────────────────────────────────

def run_batch(batch_file: str, num_scenes: int, profile: ExportProfile) -> None:
    """Process multiple story prompts from a text file (one per line)."""
    batch_path = Path(batch_file)
    if not batch_path.exists():
        logger.error(f"[error]Batch file not found: {batch_path}[/error]")
        raise SystemExit(1)

    prompts = [
        line.strip()
        for line in batch_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    console.print(
        Panel(
            f"[bold cyan]📦 Batch Mode: {len(prompts)} stories queued[/bold cyan]",
            border_style="cyan",
        )
    )

    for i, prompt in enumerate(prompts, 1):
        console.print(f"\n[step]══ Story {i}/{len(prompts)}: {prompt[:80]} ══[/step]")
        try:
            pipeline = KhmerStoryPipeline(prompt, num_scenes=num_scenes, export_profile=profile)
            pipeline.run()
        except Exception as exc:
            logger.error(f"[error]Story {i} failed: {exc}[/error]")
            console.print_exception()
            continue   # Continue to next story in batch

    console.print("\n[success]✓ Batch processing complete![/success]")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

@click.command()
@click.option(
    "--prompt", "-p",
    default=None,
    help="Story topic or prompt in Khmer or English",
)
@click.option(
    "--scenes", "-s",
    default=6, show_default=True,
    help="Number of scenes to generate",
)
@click.option(
    "--profile",
    type=click.Choice(["mobile", "laptop", "both"], case_sensitive=False),
    default="both", show_default=True,
    help="Video export profile: mobile (9:16), laptop (16:9), or both",
)
@click.option(
    "--test",
    is_flag=True, default=False,
    help="Test mode: limit to 3 scenes for a quick validation run",
)
@click.option(
    "--batch",
    default=None,
    help="Path to a text file with one story prompt per line (batch mode)",
)
def main(
    prompt: Optional[str],
    scenes: int,
    profile: str,
    test: bool,
    batch: Optional[str],
) -> None:
    """
    🎬 Automated AI Khmer Story Pipeline — Main Entry Point

    Generates a complete video story from a text prompt using AI.
    """
    export_profile = ExportProfile(profile)

    if batch:
        run_batch(batch, num_scenes=scenes, profile=export_profile)
        return

    if not prompt:
        console.print("[error]ERROR: Provide --prompt or --batch[/error]")
        raise SystemExit(1)

    pipeline = KhmerStoryPipeline(
        story_prompt=prompt,
        num_scenes=scenes,
        export_profile=export_profile,
        test_mode=test,
    )
    pipeline.run()


if __name__ == "__main__":
    main()
