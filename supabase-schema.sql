-- ================================================================
-- CloudPulse AI — Supabase Schema (Auth-enabled)
-- Paste this into the Supabase SQL Editor to set up all tables.
-- Idempotent: safe to re-run on an existing project (adds columns,
-- replaces policies). Requires the Email auth provider (password +
-- magic link) to be enabled under Authentication → Providers.
-- ================================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 1. Servers table
CREATE TABLE IF NOT EXISTS servers (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  server_name    TEXT NOT NULL,
  ip_address     TEXT,
  status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'warning', 'critical', 'idle')),
  specifications JSONB DEFAULT '{}'::jsonb,
  owner_id       UUID REFERENCES auth.users(id),           -- who owns this node
  ingestion_token TEXT NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex')
                   UNIQUE,                                 -- 256-bit bearer token for the agent
  created_at     TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Server metrics (time-series logs)
CREATE TABLE IF NOT EXISTS server_metrics (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  server_id               UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  cpu_usage               FLOAT NOT NULL,
  ram_usage               FLOAT NOT NULL,
  network_traffic         FLOAT NOT NULL,
  estimated_cost_per_hour FLOAT NOT NULL,
  recorded_at             TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_metrics_server_time
  ON server_metrics (server_id, recorded_at DESC);

-- 3. System alerts
CREATE TABLE IF NOT EXISTS system_alerts (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  server_id  UUID NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  alert_type TEXT NOT NULL CHECK (alert_type IN ('HIGH_CPU', 'IDLE_RESOURCE', 'BUDGET_SPIKE', 'NETWORK_ANOMALY')),
  message    TEXT NOT NULL,
  resolved   BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_alerts_unresolved
  ON system_alerts (resolved, created_at DESC);

-- ================================================================
-- Upgrade path for projects that already ran the old schema
-- ================================================================
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES auth.users(id);
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS ingestion_token TEXT
  NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex') UNIQUE;

-- ================================================================
-- Row Level Security — users only access their own infrastructure.
-- (The backend writes through the service-role key, which bypasses
-- RLS; these policies protect direct anon-key access from the app.)
-- ================================================================
ALTER TABLE public.servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.server_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.system_alerts ENABLE ROW LEVEL SECURITY;

-- Drop the old "allow all" policies if present
DROP POLICY IF EXISTS "Enable all access for all users" ON public.servers;
DROP POLICY IF EXISTS "Enable all access for all users" ON public.server_metrics;
DROP POLICY IF EXISTS "Enable all access for all users" ON public.system_alerts;

-- Servers: full control over your own nodes
CREATE POLICY "users_manage_own_servers" ON public.servers
  FOR ALL USING (auth.uid() = owner_id) WITH CHECK (auth.uid() = owner_id);

-- Server metrics: read/write only for metrics attached to your servers
CREATE POLICY "users_read_own_server_metrics" ON public.server_metrics
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = server_metrics.server_id AND s.owner_id = auth.uid())
  );
CREATE POLICY "users_insert_own_server_metrics" ON public.server_metrics
  FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = server_metrics.server_id AND s.owner_id = auth.uid())
  );

-- System alerts: read/write only for alerts on your servers
CREATE POLICY "users_read_own_system_alerts" ON public.system_alerts
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = system_alerts.server_id AND s.owner_id = auth.uid())
  );
CREATE POLICY "users_insert_own_system_alerts" ON public.system_alerts
  FOR INSERT WITH CHECK (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = system_alerts.server_id AND s.owner_id = auth.uid())
  );
