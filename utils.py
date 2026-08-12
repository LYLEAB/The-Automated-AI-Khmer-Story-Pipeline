"""
utils.py — Shared utilities for the Khmer Story Pipeline.

Provides:
  - Colored rich logger
  - Exponential-backoff retry decorator
  - JSON response cleaner (strips LLM markdown fences)
  - Output directory initializer
  - Pipeline state persistence (load / save)
  - Cost/run-log tracker
"""

from __future__ import annotations

import json
import logging
import re
import time
import traceback
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.theme import Theme

import config
from models import PipelineState

# ─────────────────────────────────────────────
# CONSOLE & LOGGER SETUP
# ─────────────────────────────────────────────

_THEME = Theme(
    {
        "info": "bold cyan",
        "success": "bold green",
        "warning": "bold yellow",
        "error": "bold red",
        "scene": "bold magenta",
        "step": "bold blue",
    }
)
console = Console(theme=_THEME)

def setup_logger(name: str) -> logging.Logger:
    """Return a rich-formatted logger with the given name."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        handler = RichHandler(
            console=console,
            rich_tracebacks=True,
            markup=True,
            show_path=False,
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


log = setup_logger("pipeline")


# ─────────────────────────────────────────────
# RETRY DECORATOR
# ─────────────────────────────────────────────

F = TypeVar("F", bound=Callable[..., Any])


def retry(
    max_attempts: int = config.MAX_RETRY_ATTEMPTS,
    base_delay: float = config.RETRY_BASE_DELAY_SECONDS,
    exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that retries a function up to `max_attempts` times
    with exponential backoff on the specified exception types.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    delay = base_delay * (2 ** (attempt - 1))
                    log.warning(
                        f"[warning]Attempt {attempt}/{max_attempts} failed for "
                        f"[bold]{func.__name__}[/bold]: {exc}. "
                        f"Retrying in {delay:.1f}s…[/warning]"
                    )
                    time.sleep(delay)
            log.error(
                f"[error]All {max_attempts} attempts failed for "
                f"[bold]{func.__name__}[/bold].[/error]"
            )
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator


# ─────────────────────────────────────────────
# JSON CLEANER (strips LLM markdown fences)
# ─────────────────────────────────────────────

def clean_json_response(text: str) -> str:
    """
    Strip markdown code fences and leading/trailing whitespace from an LLM response
    so it can be parsed as raw JSON.

    Examples handled:
        ```json\n{...}\n```  →  {...}
        ```\n{...}\n```      →  {...}
        {  ...  }            →  {  ...  }  (no-op)
    """
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ``` blocks
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ─────────────────────────────────────────────
# OUTPUT DIRECTORY INITIALIZATION
# ─────────────────────────────────────────────

def ensure_output_dirs() -> None:
    """Create all required output subdirectories if they don't already exist."""
    dirs = [
        config.OUTPUT_DIR,
        config.AUDIO_DIR,
        config.IMAGES_DIR,
        config.VIDEO_DIR,
        config.METADATA_DIR,
        config.ASSETS_DIR,
        config.ASSETS_DIR / "fonts",
    ]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
    log.info("[success]✓ Output directories ready[/success]")


# ─────────────────────────────────────────────
# PIPELINE STATE PERSISTENCE
# ─────────────────────────────────────────────

def save_state(state: PipelineState) -> None:
    """Persist pipeline state to output/state.json for resumability."""
    config.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_FILE, "w", encoding="utf-8") as f:
        f.write(state.model_dump_json(indent=2))
    log.debug(f"State saved → {config.STATE_FILE}")


def load_state(story_prompt: str) -> Optional[PipelineState]:
    """
    Load existing pipeline state from disk.
    Returns None if no state file exists or story prompt doesn't match.
    """
    if not config.RESUME_ON_RESTART:
        return None
    if not config.STATE_FILE.exists():
        return None
    try:
        with open(config.STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        state = PipelineState.model_validate(data)
        if state.story_prompt != story_prompt:
            log.info("[info]State file is for a different story prompt — starting fresh.[/info]")
            return None
        log.info(
            f"[success]✓ Resuming from saved state "
            f"(audio done: {len(state.audio_done_scenes)}, "
            f"images done: {len(state.images_done_scenes)})[/success]"
        )
        return state
    except Exception as exc:
        log.warning(f"[warning]Could not load state file: {exc} — starting fresh.[/warning]")
        return None


# ─────────────────────────────────────────────
# RUN LOG / COST TRACKER
# ─────────────────────────────────────────────

class RunLogger:
    """
    Tracks per-run metrics: API call counts, estimated costs, timings.
    Writes to output/run_log.json at the end of each pipeline run.
    """

    def __init__(self) -> None:
        self.start_time = datetime.now()
        self.events: list[dict] = []
        self.totals: dict[str, Any] = {
            "gemini_calls": 0,
            "tts_calls": 0,
            "image_gen_calls": 0,
            "total_audio_seconds": 0.0,
            "total_scene_count": 0,
        }

    def log_event(self, module: str, event: str, **kwargs: Any) -> None:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "module": module,
            "event": event,
            **kwargs,
        }
        self.events.append(entry)
        log.debug(f"[step][{module}][/step] {event}")

    def increment(self, key: str, amount: float = 1.0) -> None:
        self.totals[key] = self.totals.get(key, 0) + amount

    def finalize(self) -> None:
        elapsed = (datetime.now() - self.start_time).total_seconds()
        report = {
            "run_date": self.start_time.isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "totals": self.totals,
            "events": self.events,
        }
        config.RUN_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(config.RUN_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        console.print(
            Panel(
                f"[success]Pipeline complete in {elapsed:.1f}s[/success]\n"
                f"Scenes: {self.totals['total_scene_count']} | "
                f"Gemini calls: {self.totals['gemini_calls']} | "
                f"TTS calls: {self.totals['tts_calls']} | "
                f"Image gen calls: {self.totals['image_gen_calls']}",
                title="[bold cyan]📊 Run Summary[/bold cyan]",
                border_style="cyan",
            )
        )

    def print_section(self, title: str) -> None:
        console.print(f"\n[step]{'─'*60}[/step]")
        console.print(f"[step]  🎬 {title}[/step]")
        console.print(f"[step]{'─'*60}[/step]")


# Global run logger instance (created fresh per main.py invocation)
run_logger = RunLogger()
