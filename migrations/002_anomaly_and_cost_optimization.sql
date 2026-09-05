-- ================================================================
-- CloudPulse AI — Phase 2 Migration: Advanced Anomaly Detection
-- and Cost Optimization Engine Tables
-- ================================================================

-- 1. Anomaly Events Table
CREATE TABLE IF NOT EXISTS public.anomaly_events (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  server_id           UUID NOT NULL REFERENCES public.servers(id) ON DELETE CASCADE,
  metric_name         TEXT NOT NULL,
  current_value       FLOAT NOT NULL,
  baseline_value      FLOAT NOT NULL,
  deviation_sigma     FLOAT,
  severity            TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
  consecutive_count   INT NOT NULL DEFAULT 1,
  duration_seconds    INT NOT NULL DEFAULT 0,
  detection_method    TEXT NOT NULL,
  explanation         TEXT NOT NULL,
  meta                JSONB NOT NULL DEFAULT '{}'::jsonb,
  resolved            BOOLEAN NOT NULL DEFAULT false,
  created_at          TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_server
  ON public.anomaly_events (server_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_anomaly_events_unresolved
  ON public.anomaly_events (resolved, severity, created_at DESC);

-- 2. Cost Optimization Recommendations Table
CREATE TABLE IF NOT EXISTS public.optimization_recommendations (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  server_id                   UUID NOT NULL REFERENCES public.servers(id) ON DELETE CASCADE,
  service_name                TEXT NOT NULL DEFAULT 'ec2',
  resource_id                 TEXT,
  resource_name               TEXT NOT NULL,
  region                      TEXT,
  recommendation_type         TEXT NOT NULL CHECK (recommendation_type IN ('IDLE_RESOURCE', 'LOW_UTILIZATION', 'RIGHT_SIZING', 'COST_SPIKE', 'UNATTACHED_WASTE')),
  severity                    TEXT NOT NULL DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'critical')),
  current_cost_monthly        NUMERIC(10,2) NOT NULL DEFAULT 0.00,
  estimated_savings_monthly   NUMERIC(10,2) NOT NULL DEFAULT 0.00,
  estimated_avoidable_cost    NUMERIC(10,2) NOT NULL DEFAULT 0.00,
  confidence                  TEXT NOT NULL CHECK (confidence IN ('HIGH', 'MEDIUM', 'LOW')),
  pricing_source              TEXT NOT NULL DEFAULT 'aws_catalog',
  problem_summary             TEXT NOT NULL,
  action_recommendation       TEXT NOT NULL,
  target_resource_type        TEXT,
  evidence                    JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'applied', 'dismissed')),
  created_at                  TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at                  TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_opt_recs_server
  ON public.optimization_recommendations (server_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_opt_recs_status_type
  ON public.optimization_recommendations (status, recommendation_type, severity);

-- Enable RLS
ALTER TABLE public.anomaly_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.optimization_recommendations ENABLE ROW LEVEL SECURITY;

-- RLS Policies for anomaly_events
DROP POLICY IF EXISTS "users_read_own_anomaly_events" ON public.anomaly_events;
CREATE POLICY "users_read_own_anomaly_events" ON public.anomaly_events
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = anomaly_events.server_id AND s.owner_id = auth.uid())
  );

DROP POLICY IF EXISTS "users_manage_own_anomaly_events" ON public.anomaly_events;
CREATE POLICY "users_manage_own_anomaly_events" ON public.anomaly_events
  FOR ALL USING (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = anomaly_events.server_id AND s.owner_id = auth.uid())
  );

-- RLS Policies for optimization_recommendations
DROP POLICY IF EXISTS "users_read_own_opt_recommendations" ON public.optimization_recommendations;
CREATE POLICY "users_read_own_opt_recommendations" ON public.optimization_recommendations
  FOR SELECT USING (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = optimization_recommendations.server_id AND s.owner_id = auth.uid())
  );

DROP POLICY IF EXISTS "users_manage_own_opt_recommendations" ON public.optimization_recommendations;
CREATE POLICY "users_manage_own_opt_recommendations" ON public.optimization_recommendations
  FOR ALL USING (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = optimization_recommendations.server_id AND s.owner_id = auth.uid())
  );
