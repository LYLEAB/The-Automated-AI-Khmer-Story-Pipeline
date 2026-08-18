"""
main.py — Pipeline Orchestrator & CLI Entry Point
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


class KhmerStoryPipeline:
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
                f"[bold cyan]Automated AI Khmer Story Pipeline[/bold cyan]\n\n"
                f"[white]Prompt :[/white]  [yellow]{self.story_prompt}[/yellow]\n"
                f"[white]Scenes  :[/white]  {self.num_scenes}\n"
                f"[white]Export  :[/white]  {self.export_profile.value.upper()}\n"
                f"[white]Test mode:[/white] {'[ON] (3 scenes max)' if self.test_mode else '[OFF]'}",
                title="[bold blue]Khmer Story Pipeline[/bold blue]",
                border_style="blue",
                padding=(1, 4),
            )
        )

    def step_write(self, state: PipelineState) -> SceneList:
        run_logger.print_section("STEP 1 / 5 — Script & Scene Generation")
        if state.scenes_generated and (config.OUTPUT_DIR / "scenes.json").exists():
            logger.info("[INFO] Scenes already generated — loading from disk.")
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

    def step_audio(
        self, state: PipelineState, scene_list: SceneList
    ) -> List[EnrichedScene]:
        run_logger.print_section("STEP 2 / 5 — Text-to-Speech Audio Generation")
        from audio_engine import AudioEngine

        engine = AudioEngine()
        enriched = engine.process_scenes(
            scene_list,
            skip_existing=config.RESUME_ON_RESTART,
        )
        for s in enriched:
            state.mark_audio_done(s.scene_id)
        state.enriched_scenes = enriched
        save_state(state)
        return enriched

    def step_visuals(
        self, state: PipelineState, scenes: List[EnrichedScene]
    ) -> List[EnrichedScene]:
        run_logger.print_section("STEP 3 / 5 — Visual Asset Generation")
        from visual_engine import VisualEngine

        engine = VisualEngine()
        enriched = engine.process_scenes(
            scenes,
            skip_existing=config.RESUME_ON_RESTART,
        )
        for s in enriched:
            state.mark_image_done(s.scene_id)
        state.enriched_scenes = enriched
        save_state(state)
        return enriched

    def step_render(
        self, state: PipelineState, scenes: List[EnrichedScene]
    ) -> dict[str, str]:
        run_logger.print_section("STEP 4 / 5 — Video Assembly & Subtitle Burn-in")
        from renderer import VideoRenderer

        start = time.time()
        renderer = VideoRenderer()
        output_paths = renderer.render(
            scenes=scenes,
            story_title=state.story_title or "khmer_story",
            profile=self.export_profile,
        )
        run_logger.log_timing("render_seconds", time.time() - start)

        if "mobile" in output_paths:
            state.video_mobile_path = output_paths["mobile"]
        if "laptop" in output_paths:
            state.video_laptop_path = output_paths["laptop"]
        save_state(state)
        return output_paths

    def step_publish(
        self, state: PipelineState, scene_list: SceneList, scenes: List[EnrichedScene]
    ) -> None:
        run_logger.print_section("STEP 5 / 5 — Social Media Metadata Generation")
        from publisher import MetadataPublisher

        total_duration = sum(s.audio_duration_s for s in scenes)
        publisher = MetadataPublisher()
        metadata = publisher.generate(
            story_title=scene_list.story_title,
            story_title_en=scene_list.story_title_en,
            summary=" ".join(s.khmer_narration for s in scenes[:2]),
            num_scenes=len(scenes),
            duration_seconds=total_duration,
        )
        publisher.save(metadata)
        state.metadata_done = True
        save_state(state)

    def run(self) -> PipelineState:
        self._print_header()
        start_time = time.time()

        state = None
        if config.RESUME_ON_RESTART:
            state = load_state()
            if state and state.story_prompt == self.story_prompt:
                logger.info("[INFO] Resuming previous pipeline run...")

        if state is None:
            state = PipelineState(story_prompt=self.story_prompt)
            save_state(state)

        scene_list = self.step_write(state)
        enriched_scenes = self.step_audio(state, scene_list)
        enriched_scenes = self.step_visuals(state, enriched_scenes)
        video_paths = self.step_render(state, enriched_scenes)
        self.step_publish(state, scene_list, enriched_scenes)

        run_logger.save()
        total_time = time.time() - start_time
        console.print(f"\n[bold green][SUCCESS] Pipeline Complete! ({total_time:.1f}s total)[/bold green]")
        for profile_name, path in video_paths.items():
            console.print(f"  -> Video [{profile_name.upper()}]: [cyan]{path}[/cyan]")
        console.print(f"  -> Captions: [cyan]{config.METADATA_DIR / 'caption.txt'}[/cyan]")
        return state


@click.command()
@click.option("--prompt", "-p", default=None, help="Story topic/title in Khmer or English")
@click.option("--scenes", "-s", default=6, help="Number of scenes (default: 6, max: 12)")
@click.option(
    "--profile",
    type=click.Choice(["mobile", "laptop", "both"], case_sensitive=False),
    default="both",
    help="Export profile (default: both)",
)
@click.option("--test", is_flag=True, help="Quick test run (capped at 3 scenes)")
@click.option("--batch", "-b", default=None, help="Text file with one prompt per line")
def cli(
    prompt: Optional[str],
    scenes: int,
    profile: str,
    test: bool,
    batch: Optional[str],
) -> None:
    export_profile = ExportProfile(profile.lower())

    if batch:
        batch_path = Path(batch)
        if not batch_path.exists():
            console.print(f"[bold red]Batch file not found: {batch}[/bold red]")
            sys.exit(1)
        prompts = [
            line.strip()
            for line in batch_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        console.print(f"[bold cyan]Starting batch run: {len(prompts)} stories...[/bold cyan]")
        for i, p in enumerate(prompts, 1):
            console.print(Rule(f"Story {i}/{len(prompts)}: {p[:40]}..."))
            pipeline = KhmerStoryPipeline(
                story_prompt=p,
                num_scenes=scenes,
                export_profile=export_profile,
                test_mode=test,
            )
            pipeline.run()
        return

    if not prompt:
        prompt = click.prompt("Enter story topic / prompt (Khmer or English)")

    pipeline = KhmerStoryPipeline(
        story_prompt=prompt,
        num_scenes=scenes,
        export_profile=export_profile,
        test_mode=test,
    )
    pipeline.run()


if __name__ == "__main__":
    cli()
