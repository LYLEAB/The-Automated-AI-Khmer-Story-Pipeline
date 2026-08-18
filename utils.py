"""
utils.py — Logging, retry decorators, and helper utilities.
"""
from __future__ import annotations

import functools
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel

import config

console = Console()
F = TypeVar("F", bound=Callable[..., Any])


class RunLogger:
    def __init__(self) -> None:
        self.stats: dict[str, Any] = {
            "gemini_calls": 0,
            "tts_calls": 0,
            "image_calls": 0,
            "render_seconds": 0.0,
            "start_time": time.time(),
        }

    def increment(self, metric: str, amount: int = 1) -> None:
        if metric in self.stats:
            self.stats[metric] += amount

    def log_timing(self, metric: str, duration_seconds: float) -> None:
        self.stats[metric] = round(duration_seconds, 2)

    def save(self, filepath: Path = config.RUN_LOG_FILE) -> None:
        self.stats["total_runtime_seconds"] = round(time.time() - self.stats["start_time"], 2)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=2)

    def print_section(self, title: str) -> None:
        console.print(f"\n[bold cyan]===[/bold cyan] [bold white]{title}[/bold white] [bold cyan]===[/bold cyan]")


run_logger = RunLogger()


def setup_logger(name: str = "pipeline") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = RichHandler(
            console=console,
            show_path=False,
            rich_tracebacks=True,
            markup=True,
        )
        formatter = logging.Formatter("[%(name)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger


logger = setup_logger("core")


def retry(
    max_attempts: int = 5,
    base_delay: float = config.RETRY_BASE_DELAY_SECONDS,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = base_delay
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    exc_str = str(exc).lower()
                    if "429" in exc_str or "quota exceeded" in exc_str or "rate limit" in exc_str:
                        logger.warning(f"[WARN] API Rate Limit hit! Sleeping for 65s to fully reset quota...")
                        time.sleep(65)
                        # Don't increment standard delay for 429, just loop again
                        continue

                    if attempt == max_attempts:
                        logger.error(f"[ERROR] {func.__name__} failed after {max_attempts} attempts: {exc}")
                        raise
                        
                    logger.warning(
                        f"[WARN] {func.__name__} attempt {attempt}/{max_attempts} failed: {exc}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay *= backoff
            if last_exc:
                logger.error(f"[ERROR] {func.__name__} failed after exhausting retries due to rate limits.")
                raise last_exc
        return wrapper  # type: ignore
    return decorator


def ensure_output_dirs() -> None:
    for path in [
        config.OUTPUT_DIR,
        config.AUDIO_DIR,
        config.IMAGES_DIR,
        config.VIDEO_DIR,
        config.METADATA_DIR,
        config.ASSETS_DIR / "fonts",
        config.ASSETS_DIR / "audio",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def clean_json_response(raw_text: str) -> str:
    text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def load_state(filepath: Path = config.STATE_FILE):
    from models import PipelineState
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PipelineState(**data)
        except Exception as exc:
            logger.warning(f"[WARN] Could not load state from {filepath}: {exc}")
    return None


def save_state(state, filepath: Path = config.STATE_FILE) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(state.model_dump_json(indent=2))


def log(msg: str, style: str = "info") -> None:
    prefix_map = {
        "info": "[INFO]",
        "success": "[SUCCESS]",
        "warning": "[WARN]",
        "error": "[ERROR]",
        "step": "[STEP]",
    }
    prefix = prefix_map.get(style, "[INFO]")
    console.print(f"[bold]{prefix}[/bold] {msg}")
