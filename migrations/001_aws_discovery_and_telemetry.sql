-- ================================================================
-- Migration 001: AWS Resource Discovery & Expanded Telemetry
-- Idempotent non-destructive migration script for Supabase
-- ================================================================

-- 1. Extend servers table with AWS metadata and source tracking
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'agent'
    CHECK (source IN ('agent', 'aws_discovery')),
  ADD COLUMN IF NOT EXISTS aws_instance_id TEXT UNIQUE,
  ADD COLUMN IF NOT EXISTS aws_region TEXT,
  ADD COLUMN IF NOT EXISTS aws_availability_zone TEXT,
  ADD COLUMN IF NOT EXISTS aws_state TEXT,
  ADD COLUMN IF NOT EXISTS aws_launch_time TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS aws_tags JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS last_discovered_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_servers_aws_instance_id
  ON public.servers (aws_instance_id) WHERE aws_instance_id IS NOT NULL;

-- 2. Extend server_metrics table with expanded psutil metrics
ALTER TABLE public.server_metrics
  ADD COLUMN IF NOT EXISTS disk_usage FLOAT,
  ADD COLUMN IF NOT EXISTS disk_io JSONB,
  ADD COLUMN IF NOT EXISTS system_uptime FLOAT,
  ADD COLUMN IF NOT EXISTS load_average JSONB,
  ADD COLUMN IF NOT EXISTS process_count INTEGER,
  ADD COLUMN IF NOT EXISTS network_stats JSONB;
