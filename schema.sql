-- ============================================================
-- schema.sql — Supabase Database Schema
-- Khmer Story Pipeline
-- ============================================================
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ============================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── PIPELINE JOBS ─────────────────────────────────────────
-- Stores one record per video generation run
CREATE TABLE IF NOT EXISTS pipeline_jobs (
    id            TEXT        PRIMARY KEY,          -- Short UUID e.g. "a1b2c3d4"
    prompt        TEXT        NOT NULL,             -- Original story prompt
    config        JSONB       DEFAULT '{}',         -- Pipeline settings (scenes, TTS, etc.)
    status        TEXT        NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
    step          INTEGER     DEFAULT 0,            -- Current pipeline step (1–5)
    progress_pct  INTEGER     DEFAULT 0,            -- Overall progress 0–100
    message       TEXT        DEFAULT 'Queued…',   -- Latest status message
    story_title   TEXT,                             -- Khmer story title (set after step 1)
    outputs       JSONB       DEFAULT '{}',         -- Video URLs, metadata URLs
    scene_previews JSONB      DEFAULT '[]',         -- Scene thumbnails for UI gallery
    error         TEXT,                             -- Error message if failed
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Auto-update updated_at on every change
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON pipeline_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── PIPELINE EVENTS ───────────────────────────────────────
-- Granular per-step progress events — Supabase Realtime streams
-- INSERT events on this table to the browser in real time.
CREATE TABLE IF NOT EXISTS pipeline_events (
    id            BIGSERIAL   PRIMARY KEY,
    job_id        TEXT        NOT NULL REFERENCES pipeline_jobs(id) ON DELETE CASCADE,
    step          INTEGER     NOT NULL,
    module        TEXT        NOT NULL,     -- "writer" | "audio_engine" | etc.
    status        TEXT        NOT NULL,     -- "running" | "done" | "failed"
    message       TEXT        NOT NULL,
    progress_pct  INTEGER     NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast event polling per job
CREATE INDEX IF NOT EXISTS idx_events_job_id ON pipeline_events(job_id, created_at);

-- ── ROW-LEVEL SECURITY (RLS) ──────────────────────────────
-- Disable RLS for now (server-side API controls access).
-- Enable and add policies when you add user authentication.
ALTER TABLE pipeline_jobs   DISABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_events DISABLE ROW LEVEL SECURITY;

-- ── ENABLE REALTIME ───────────────────────────────────────
-- Allow Supabase Realtime to broadcast changes on these tables.
-- Run in Supabase: Table Editor → pipeline_events → Enable Realtime
ALTER PUBLICATION supabase_realtime ADD TABLE pipeline_events;
ALTER PUBLICATION supabase_realtime ADD TABLE pipeline_jobs;

-- ── STORAGE BUCKETS ───────────────────────────────────────
-- Create these in Supabase Dashboard → Storage → New Bucket
-- Or run via Supabase CLI:
--   supabase storage create videos --public
--   supabase storage create images --public
--   supabase storage create audio  --public
--
-- Bucket settings:
--   videos: public = true,  file size limit = 500 MB
--   images: public = true,  file size limit = 10 MB
--   audio:  public = true,  file size limit = 50 MB

-- ── SAMPLE QUERY: Recent jobs ─────────────────────────────
-- SELECT id, prompt, status, progress_pct, story_title, created_at
-- FROM pipeline_jobs
-- ORDER BY created_at DESC
-- LIMIT 10;
