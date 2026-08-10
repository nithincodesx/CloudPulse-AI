-- ================================================================
-- CloudPulse AI — Supabase Schema (Enterprise Edition)
-- Paste this into the Supabase SQL Editor to set up all tables.
-- ================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Servers table
CREATE TABLE IF NOT EXISTS servers (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  server_name    TEXT NOT NULL,
  ip_address     TEXT,
  status         TEXT NOT NULL DEFAULT 'active'
                   CHECK (status IN ('active', 'warning', 'critical', 'idle')),
  specifications JSONB DEFAULT '{}'::jsonb,
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
-- Row Level Security (development convenience — open access)
-- ================================================================
ALTER TABLE public.servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.server_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.system_alerts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Enable all access for all users" ON public.servers
  FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all access for all users" ON public.server_metrics
  FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Enable all access for all users" ON public.system_alerts
  FOR ALL USING (true) WITH CHECK (true);

-- ================================================================
-- Seed demo servers
-- ================================================================
INSERT INTO servers (server_name, ip_address, status, specifications) VALUES
  ('web-prod-01',    '10.0.1.11', 'active',   '{"vcpus": 4, "ram_gb": 16, "type": "c5.xlarge"}'::jsonb),
  ('web-prod-02',    '10.0.1.12', 'active',   '{"vcpus": 4, "ram_gb": 16, "type": "c5.xlarge"}'::jsonb),
  ('api-master-01',  '10.0.2.21', 'active',   '{"vcpus": 8, "ram_gb": 32, "type": "m5.2xlarge"}'::jsonb),
  ('api-worker-02',  '10.0.2.22', 'warning',  '{"vcpus": 4, "ram_gb": 16, "type": "c5.xlarge"}'::jsonb),
  ('db-primary-01',  '10.0.3.31', 'active',   '{"vcpus": 16, "ram_gb": 64, "type": "r5.4xlarge"}'::jsonb),
  ('cache-redis-01', '10.0.4.41', 'active',   '{"vcpus": 2, "ram_gb": 8, "type": "r5.large"}'::jsonb),
  ('worker-queue-01','10.0.5.51', 'idle',     '{"vcpus": 2, "ram_gb": 8, "type": "t3.large"}'::jsonb),
  ('staging-web-01', '10.0.6.61', 'active',   '{"vcpus": 2, "ram_gb": 8, "type": "t3.large"}'::jsonb),
  ('analytics-01',   '10.0.7.71', 'critical', '{"vcpus": 8, "ram_gb": 32, "type": "c5.2xlarge"}'::jsonb),
  ('cdn-edge-01',    '10.0.8.81', 'idle',     '{"vcpus": 2, "ram_gb": 4, "type": "t3.medium"}'::jsonb)
ON CONFLICT DO NOTHING;
