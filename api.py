"""
api.py — FastAPI Backend for the Khmer Story Pipeline Web UI
=============================================================
Exposes the 5-module pipeline as REST endpoints with real-time
Server-Sent Events (SSE) for live progress streaming.

Deploy to: Railway / Render / Google Cloud Run
Frontend:  Deploy web/ to Vercel (static site)

CORS is fully open so the Vercel frontend can call this API from any origin.

Start locally (dev):
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Environment variables needed (set in Railway/Render dashboard):
    GEMINI_API_KEY
    TTS_PROVIDER              (default: gtts)
    IMAGE_PROVIDER            (default: gemini_imagen)
    SUPABASE_URL              (optional — enables persistent job history)
    SUPABASE_ANON_KEY         (optional — enables persistent job history)
    GOOGLE_APPLICATION_CREDENTIALS  (optional)
    ELEVENLABS_API_KEY        (optional)
    STABILITY_API_KEY         (optional)

With Supabase configured:
  - Jobs are stored in postgres (survive server restarts)
  - Progress events stream via Supabase Realtime to the browser
  - Videos/images are stored in Supabase Storage (CDN-served)
  Without Supabase: falls back to in-memory dict (jobs lost on restart)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Supabase integration (optional — graceful fallback to in-memory) ──
SUPABASE_ENABLED = bool(os.getenv("SUPABASE_URL"))
if SUPABASE_ENABLED:
    try:
        import supabase_client as sb
        print("[API] Supabase integration ENABLED — jobs will persist to postgres")
    except ImportError:
        SUPABASE_ENABLED = False
        print("[API] supabase package not installed — using in-memory job store")
else:
    print("[API] SUPABASE_URL not set — using in-memory job store (jobs lost on restart)")

# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────

app = FastAPI(
    title="Khmer Story Pipeline API",
    description="AI-powered Khmer story video generation backend",
    version="1.0.0",
)

# Full CORS — required for Vercel frontend calling Railway/Render backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve the frontend static files at root (for local dev convenience)
WEB_DIR = Path(__file__).parent / "web"
if WEB_DIR.exists():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR)), name="web")

# ─────────────────────────────────────────────
# IN-MEMORY JOB STORE
# ─────────────────────────────────────────────
# Production: replace with Redis or a lightweight SQLite store

class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


jobs: Dict[str, Dict[str, Any]] = {}   # in-memory fallback
job_queues: Dict[str, asyncio.Queue] = {}


def new_job(prompt: str, config: dict) -> str:
    job_id = str(uuid.uuid4())[:8]
    record = {
        "id": job_id,
        "prompt": prompt,
        "config": config,
        "status": JobStatus.QUEUED,
        "created_at": datetime.now().isoformat(),
        "step": 0,
        "progress_pct": 0,
        "message": "Queued…",
        "outputs": {},
        "scene_previews": [],
        "error": None,
    }
    jobs[job_id] = record
    if SUPABASE_ENABLED:
        try:
            sb.create_job(job_id, prompt, config)
        except Exception as exc:
            print(f"[Supabase] create_job failed: {exc}")
    return job_id


def _sync_job_from_supabase(job_id: str) -> None:
    """Pull latest job state from Supabase into in-memory cache."""
    if not SUPABASE_ENABLED:
        return
    try:
        data = sb.get_job(job_id)
        if data:
            jobs[job_id] = data
    except Exception:
        pass


# ─────────────────────────────────────────────
# REQUEST / RESPONSE MODELS
# ─────────────────────────────────────────────

class RunRequest(BaseModel):
    prompt: str
    mode: str = "ai_generate"          # "ai_generate" | "paste_story"
    num_scenes: int = 6
    export_profile: str = "both"       # "mobile" | "laptop" | "both"
    tts_provider: str = "gtts"
    image_provider: str = "gemini_imagen"
    story_style: str = "dramatic"      # mood hint


class GenerateStoryRequest(BaseModel):
    prompt: str
    num_scenes: int = 6
    style: str = "dramatic"


# ─────────────────────────────────────────────
# SSE PROGRESS EMITTER
# ─────────────────────────────────────────────


main_loop: Optional[asyncio.AbstractEventLoop] = None

@app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()
    print("[API] Event loop captured for worker threads")

def emit(job_id: str, step: int, module: str, status: str, message: str, pct: int) -> None:
    event = {
        "step": step,
        "module": module,
        "status": status,
        "message": message,
        "progress_pct": pct,
        "timestamp": datetime.now().isoformat(),
    }
    if job_id in jobs:
        jobs[job_id].update({"step": step, "progress_pct": pct, "message": message, "status": status})

    if SUPABASE_ENABLED:
        try:
            sb.insert_event(job_id, step, module, status, message, pct)
        except Exception:
            pass

    q = job_queues.get(job_id)
    if q and main_loop and main_loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(q.put(event), main_loop)
        except Exception:
            pass

def run_pipeline_thread(job_id: str, req: RunRequest) -> None:
    """
    Executes the full 5-module pipeline in a separate thread.
    Emits SSE progress events at each step.
    """
    job = jobs[job_id]
    job["status"] = JobStatus.RUNNING

    try:
        # ── Apply provider overrides from request ──
        import config as cfg
        cfg.TTS_PROVIDER = req.tts_provider
        cfg.IMAGE_PROVIDER = req.image_provider
        cfg.RESUME_ON_RESTART = False   # Fresh run per web request

        from utils import ensure_output_dirs, save_state, load_state
        from models import PipelineState, ExportProfile, EnrichedScene

        # Use job_id as sub-directory so jobs don't overwrite each other
        job_output_dir = Path("output") / job_id
        cfg.OUTPUT_DIR = job_output_dir
        cfg.AUDIO_DIR = job_output_dir / "audio"
        cfg.IMAGES_DIR = job_output_dir / "images"
        cfg.VIDEO_DIR = job_output_dir / "video"
        cfg.METADATA_DIR = job_output_dir / "metadata"
        cfg.STATE_FILE = job_output_dir / "state.json"
        ensure_output_dirs()

        state = PipelineState(story_prompt=req.prompt)

        # ── STEP 1: Write scenes ─────────────────
        emit(job_id, 1, "writer", "running", "Writing story with Gemini…", 5)
        from writer import SceneWriter
        writer = SceneWriter()

        if req.mode == "paste_story":
            # Paste mode: send text to Gemini to structure into scenes
            structured_prompt = (
                f"Structure this story into {req.num_scenes} scenes:\n\n{req.prompt}"
            )
            scene_list = writer.generate(structured_prompt, req.num_scenes)
        else:
            scene_list = writer.generate(req.prompt, req.num_scenes)

        writer.save(scene_list, job_output_dir / "scenes.json")
        state.scenes_generated = True
        state.story_title = scene_list.story_title
        state.enriched_scenes = [EnrichedScene(**s.model_dump()) for s in scene_list.scenes]
        emit(job_id, 1, "writer", "done", f"Story written: '{scene_list.story_title}'", 18)

        # ── STEP 2 & 3: Audio and Image Generation (Parallel) ────────
        emit(job_id, 2, "generation", "running", "Generating Audio and AI Images concurrently…", 20)
        from audio_engine import AudioEngine
        from visual_engine import VisualEngine
        import concurrent.futures

        audio_engine = AudioEngine()
        vis_engine = VisualEngine()

        def generate_audio():
            return audio_engine.process_all(scene_list)

        def generate_visuals():
            # visual_engine processes EnrichedScene objects
            return vis_engine.process_all(state.enriched_scenes)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_audio = executor.submit(generate_audio)
            future_visual = executor.submit(generate_visuals)
            
            audio_results = future_audio.result()
            visual_results = future_visual.result()

        # Merge results since they were processed independently
        # visual_engine mutated the existing state.enriched_scenes with image_paths
        # audio_engine returned a new list with audio_paths and durations
        visual_map = {s.scene_id: s for s in state.enriched_scenes}
        merged_scenes = []
        for audio_scene in audio_results:
            merged = audio_scene
            if merged.scene_id in visual_map:
                merged.image_path = visual_map[merged.scene_id].image_path
            state.mark_audio_done(merged.scene_id)
            state.mark_image_done(merged.scene_id)
            merged_scenes.append(merged)
            
        state.enriched_scenes = merged_scenes
        emit(job_id, 3, "generation", "done", "All audio and images generated", 60)

        # Collect image thumbnails for UI gallery
        scene_previews = []
        for e in state.enriched_scenes:
            mobile_img = cfg.IMAGES_DIR / f"scene_{e.scene_id}_mobile.png"
            scene_previews.append({
                "scene_id": e.scene_id,
                "narration_preview": e.khmer_narration[:80],
                "mood": e.mood if isinstance(e.mood, str) else e.mood.value,
                "duration_s": round(e.audio_duration_s, 1),
                "image_url": f"/api/image/{job_id}/{e.scene_id}/mobile"
                             if mobile_img.exists() else None,
            })
        job["scene_previews"] = scene_previews

        # ── STEP 4: Video Rendering ───────────────
        emit(job_id, 4, "renderer", "running", "Rendering video (this takes a minute)…", 62)
        from renderer import VideoRenderer
        from models import ExportProfile as EP
        renderer = VideoRenderer()
        profile = EP(req.export_profile)
        results = renderer.render(
            scenes=state.enriched_scenes,
            story_title=state.story_title or "khmer_story",
            profile=profile,
        )
        state.video_mobile_path = results.get("mobile")
        state.video_laptop_path = results.get("laptop")
        emit(job_id, 4, "renderer", "done", "Videos rendered", 84)

        # ── STEP 5: Metadata ─────────────────────
        emit(job_id, 5, "publisher", "running", "Generating social media metadata…", 86)
        total_dur = sum(e.audio_duration_s for e in state.enriched_scenes)
        from publisher import MetadataPublisher
        publisher = MetadataPublisher()
        metadata = publisher.generate(
            story_title=state.story_title,
            num_scenes=len(state.enriched_scenes),
            duration_seconds=total_dur,
        )
        publisher.save(metadata, state.story_title)
        state.metadata_done = True
        emit(job_id, 5, "publisher", "done", "Metadata generated", 100)

        outputs = {}

        # ── Upload videos to Supabase Storage ────
        if SUPABASE_ENABLED:
            try:
                emit(job_id, 5, "storage", "running", "Uploading videos to cloud storage…", 90)
                if results.get("mobile") and Path(results["mobile"]).exists():
                    mobile_url = sb.upload_video(job_id, "mobile", Path(results["mobile"]))
                    outputs["video_mobile"] = mobile_url   # override with CDN URL
                if results.get("laptop") and Path(results["laptop"]).exists():
                    laptop_url = sb.upload_video(job_id, "laptop", Path(results["laptop"]))
                    outputs["video_laptop"] = laptop_url
            except Exception as exc:
                print(f"[Supabase] upload failed (videos still available via local API): {exc}")

        job["outputs"] = outputs
        job["status"] = JobStatus.DONE

        # Persist final state to Supabase
        if SUPABASE_ENABLED:
            try:
                sb.update_job(
                    job_id,
                    status="done",
                    progress_pct=100,
                    story_title=state.story_title,
                    outputs=outputs,
                    scene_previews=job.get("scene_previews", []),
                )
            except Exception as exc:
                print(f"[Supabase] update_job(done) failed: {exc}")

        # Send final DONE event
        emit(job_id, 5, "done", "done", "Pipeline complete!", 100)

    except Exception as exc:
        tb = traceback.format_exc()
        job["status"] = JobStatus.FAILED
        job["error"] = str(exc)
        if SUPABASE_ENABLED:
            try:
                sb.update_job(job_id, status="failed", error=str(exc))
            except Exception:
                pass
        emit(job_id, job.get("step", 0), "error", "failed", f"❌ Error: {exc}", job.get("progress_pct", 0))
        print(f"[JOB {job_id}] FAILED:\n{tb}", file=sys.stderr)
    finally:
        # Signal SSE stream to close
        q = job_queues.get(job_id)
        if q:
            if main_loop and main_loop.is_running():
                asyncio.run_coroutine_threadsafe(q.put(None), main_loop)


# ─────────────────────────────────────────────
# API ROUTES
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    index = WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"status": "Khmer Story Pipeline API", "version": "1.0.0"})


@app.get("/style.css")
async def get_style():
    style = WEB_DIR / "style.css"
    if style.exists():
        return FileResponse(str(style), media_type="text/css")
    raise HTTPException(status_code=404, detail="style.css not found")


@app.get("/app.js")
async def get_app_js():
    js = WEB_DIR / "app.js"
    if js.exists():
        return FileResponse(str(js), media_type="application/javascript")
    raise HTTPException(status_code=404, detail="app.js not found")

@app.get("/api/status")
async def health():
    """Health check for uptime monitors (Render/Railway ping)."""
    return {
        "status": "ok",
        "supabase": SUPABASE_ENABLED,
        "active_jobs": len([j for j in jobs.values() if j["status"] == "running"]),
    }


@app.get("/api/jobs")
async def list_jobs(limit: int = 20):
    """
    Return recent job history.
    Uses Supabase postgres when enabled, otherwise in-memory list.
    """
    if SUPABASE_ENABLED:
        try:
            return sb.list_recent_jobs(limit)
        except Exception as exc:
            print(f"[Supabase] list_jobs failed: {exc}")
    # Fallback: return in-memory jobs sorted by created_at
    sorted_jobs = sorted(
        jobs.values(),
        key=lambda j: j.get("created_at", ""),
        reverse=True,
    )
    return [
        {"id": j["id"], "prompt": j["prompt"], "status": j["status"],
         "progress_pct": j["progress_pct"], "story_title": j.get("outputs", {}).get("story_title"),
         "created_at": j["created_at"]}
        for j in sorted_jobs[:limit]
    ]


@app.post("/api/run")
async def run_pipeline(req: RunRequest, background_tasks: BackgroundTasks):
    """
    Start a new pipeline job.
    Returns a job_id immediately — use /api/progress/{job_id} for live updates.
    """
    job_id = new_job(req.prompt, req.model_dump())
    job_queues[job_id] = asyncio.Queue()

    # Run the pipeline in a thread (it uses sync libraries: moviepy, mutagen, etc.)
    thread = threading.Thread(
        target=run_pipeline_thread,
        args=(job_id, req),
        daemon=True,
    )
    thread.start()

    return {"job_id": job_id, "status": "queued", "progress_url": f"/api/progress/{job_id}"}


@app.get("/api/progress/{job_id}")
async def progress_stream(job_id: str):
    """
    Server-Sent Events (SSE) stream of live pipeline progress.
    Connect with: new EventSource('/api/progress/JOB_ID')
    """
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send current state immediately
        job = jobs[job_id]
        yield f"data: {json.dumps({'step': job['step'], 'progress_pct': job['progress_pct'], 'message': job['message'], 'status': job['status']})}\n\n"

        q = job_queues.get(job_id)
        if not q:
            return

        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                if event is None:   # Pipeline finished or crashed
                    if jobs[job_id].get("status") == JobStatus.FAILED:
                        # Frontend will handle the 'failed' event that was sent right before None
                        break
                    yield f"data: {json.dumps({'done': True, 'outputs': jobs[job_id].get('outputs', {})})}\n\n"
                    break
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("status") in ("done", "failed") and event.get("step") == 5:
                    if event.get("status") == "failed":
                        break
                    yield f"data: {json.dumps({'done': True, 'outputs': jobs[job_id].get('outputs', {})})}\n\n"
                    break
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"   # Prevent proxy timeout
            except Exception:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable Nginx buffering for SSE
        },
    )


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    """Get full job state including outputs and scene previews."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/video/{job_id}/{profile}")
async def stream_video(job_id: str, profile: str):
    """Stream an MP4 video file for the given job and profile (mobile/laptop)."""
    job_video_dir = Path("output") / job_id / "video"
    if not job_video_dir.exists():
        job_video_dir = Path("output") / "video"

    suffix = "mobile" if profile == "mobile" else "laptop"
    mp4_files = list(job_video_dir.glob(f"*{suffix}*.mp4"))
    if not mp4_files:
        mp4_files = list(job_video_dir.glob("*.mp4"))

    if not mp4_files:
        raise HTTPException(status_code=404, detail=f"Video ({profile}) not found on server")

    video_file = mp4_files[0]
    from urllib.parse import quote
    encoded_name = quote(video_file.name)
    return FileResponse(
        path=str(video_file),
        media_type="video/mp4",
        filename=f"video_{profile}.mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Disposition": f"inline; filename=\"video_{profile}.mp4\"; filename*=UTF-8''{encoded_name}",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Expose-Headers": "Content-Range, Accept-Ranges, Content-Length",
        },
    )


@app.get("/api/image/{job_id}/{scene_id}/{variant}")
async def get_scene_image(job_id: str, scene_id: int, variant: str):
    """Return a scene image thumbnail (mobile or laptop variant)."""
    img_dir = Path("output") / job_id / "images"
    if not img_dir.exists():
        img_dir = Path("output") / "images"

    img_path = img_dir / f"scene_{scene_id}_{variant}.png"
    if not img_path.exists():
        img_path = img_dir / f"scene_{scene_id}.png"
    if not img_path.exists():
        all_imgs = list(img_dir.glob("*.png"))
        if all_imgs:
            img_path = all_imgs[0]
        else:
            raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(
        str(img_path),
        media_type="image/png",
        headers={"Access-Control-Allow-Origin": "*"},
    )


@app.get("/api/metadata/{job_id}")
async def get_metadata(job_id: str):
    """Return the structured metadata JSON for a completed job."""
    meta_path = Path("output") / job_id / "metadata" / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="Metadata not ready")
    with open(meta_path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/caption/{job_id}")
async def get_caption(job_id: str):
    """Return the caption.txt content as plain text."""
    caption_path = Path("output") / job_id / "metadata" / "caption.txt"
    if not caption_path.exists():
        raise HTTPException(status_code=404, detail="Caption not ready")
    return FileResponse(str(caption_path), media_type="text/plain; charset=utf-8")


@app.post("/api/generate-story")
async def generate_story_only(req: GenerateStoryRequest):
    """
    Generate ONLY the story scenes (no audio/video).
    Used by the 'AI Generate' tab to preview scenes before running the full pipeline.
    """
    try:
        import config as cfg
        from writer import SceneWriter
        writer = SceneWriter()
        scene_list = writer.generate(req.prompt, req.num_scenes)
        return {
            "story_title": scene_list.story_title,
            "story_title_en": scene_list.story_title_en,
            "total_scenes": scene_list.total_scenes,
            "scenes": [
                {
                    "scene_id": s.scene_id,
                    "khmer_narration": s.khmer_narration,
                    "visual_prompt": s.visual_prompt,
                    "mood": s.mood.value if hasattr(s.mood, "value") else s.mood,
                    "duration_hint_seconds": s.duration_hint_seconds,
                }
                for s in scene_list.scenes
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
