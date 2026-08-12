"""
supabase_client.py — Supabase integration for the Khmer Story Pipeline
=======================================================================
Supabase replaces:
  - In-memory `jobs` dict in api.py       → `pipeline_jobs` postgres table
  - Local disk video/image storage         → Supabase Storage buckets
  - SSE-only progress                      → Supabase Realtime + SSE fallback

Tables created in Supabase (run schema.sql in Supabase SQL editor):
  - pipeline_jobs     : Job metadata + status
  - pipeline_events   : Per-step progress log (realtime subscription source)

Storage buckets:
  - videos            : Final MP4 exports (mobile + laptop)
  - images            : Scene images (mobile + laptop variants)
  - audio             : Scene TTS MP3 files

Setup:
  1. Create a free Supabase project at https://supabase.com
  2. Run schema.sql in the Supabase SQL Editor
  3. Create Storage buckets: videos, images, audio (set to public)
  4. Copy SUPABASE_URL and SUPABASE_KEY from Project Settings → API
  5. Add both to .env and to your Render/Railway environment variables
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_ANON_KEY", "")    # anon/public key is fine for server-side with RLS disabled

_client = None


def get_client():
    """Return a lazily-initialized Supabase client."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise EnvironmentError(
                "SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env "
                "or as environment variables on Render/Railway."
            )
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ─────────────────────────────────────────────
# JOB OPERATIONS
# ─────────────────────────────────────────────

def create_job(job_id: str, prompt: str, config: dict) -> dict:
    """Insert a new pipeline job record into the pipeline_jobs table."""
    client = get_client()
    record = {
        "id":          job_id,
        "prompt":      prompt,
        "config":      config,
        "status":      "queued",
        "step":        0,
        "progress_pct": 0,
        "message":     "Queued…",
        "outputs":     {},
        "error":       None,
    }
    client.table("pipeline_jobs").insert(record).execute()
    return record


def update_job(job_id: str, **fields) -> None:
    """Update job fields in the pipeline_jobs table."""
    client = get_client()
    client.table("pipeline_jobs").update(fields).eq("id", job_id).execute()


def get_job(job_id: str) -> Optional[dict]:
    """Fetch a single job record by ID."""
    client = get_client()
    res = client.table("pipeline_jobs").select("*").eq("id", job_id).single().execute()
    return res.data if res.data else None


def list_recent_jobs(limit: int = 20) -> list:
    """Fetch the most recent jobs, newest first."""
    client = get_client()
    res = (
        client.table("pipeline_jobs")
        .select("id, prompt, status, progress_pct, story_title, created_at")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


# ─────────────────────────────────────────────
# PROGRESS EVENTS (for Supabase Realtime)
# ─────────────────────────────────────────────

def insert_event(job_id: str, step: int, module: str, status: str, message: str, pct: int) -> None:
    """
    Insert a progress event row. Supabase Realtime streams these INSERT
    events to any subscribed frontend clients automatically.
    """
    client = get_client()
    client.table("pipeline_events").insert({
        "job_id":       job_id,
        "step":         step,
        "module":       module,
        "status":       status,
        "message":      message,
        "progress_pct": pct,
    }).execute()

    # Also update the parent job's current state
    update_job(job_id, step=step, progress_pct=pct, message=message, status="running" if status == "running" else None)


# ─────────────────────────────────────────────
# STORAGE OPERATIONS
# ─────────────────────────────────────────────

def upload_video(job_id: str, profile: str, local_path: Path) -> str:
    """
    Upload an MP4 file to Supabase Storage `videos` bucket.

    Args:
        job_id:     Job UUID (used as folder name).
        profile:    "mobile" or "laptop".
        local_path: Path to the local MP4 file.

    Returns:
        Public URL of the uploaded video.
    """
    client = get_client()
    storage_path = f"{job_id}/{profile}.mp4"
    with open(local_path, "rb") as f:
        client.storage.from_("videos").upload(
            path=storage_path,
            file=f,
            file_options={"content-type": "video/mp4", "upsert": "true"},
        )
    public_url = client.storage.from_("videos").get_public_url(storage_path)
    return public_url


def upload_image(job_id: str, scene_id: int, variant: str, local_path: Path) -> str:
    """
    Upload a scene image PNG to Supabase Storage `images` bucket.

    Args:
        job_id:    Job UUID.
        scene_id:  Scene number.
        variant:   "mobile" or "laptop".
        local_path: Path to the local PNG file.

    Returns:
        Public URL of the uploaded image.
    """
    client = get_client()
    storage_path = f"{job_id}/scene_{scene_id}_{variant}.png"
    with open(local_path, "rb") as f:
        client.storage.from_("images").upload(
            path=storage_path,
            file=f,
            file_options={"content-type": "image/png", "upsert": "true"},
        )
    return client.storage.from_("images").get_public_url(storage_path)


def upload_audio(job_id: str, scene_id: int, local_path: Path) -> str:
    """Upload a scene MP3 to Supabase Storage `audio` bucket."""
    client = get_client()
    storage_path = f"{job_id}/scene_{scene_id}.mp3"
    with open(local_path, "rb") as f:
        client.storage.from_("audio").upload(
            path=storage_path,
            file=f,
            file_options={"content-type": "audio/mpeg", "upsert": "true"},
        )
    return client.storage.from_("audio").get_public_url(storage_path)


def get_video_url(job_id: str, profile: str) -> Optional[str]:
    """Get the public URL for a stored video without re-uploading."""
    client = get_client()
    path = f"{job_id}/{profile}.mp4"
    try:
        return client.storage.from_("videos").get_public_url(path)
    except Exception:
        return None
