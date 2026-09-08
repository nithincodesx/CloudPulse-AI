-- ==============================================================================
-- CloudPulse AI — Migration 008: Complete Telemetry & Fleet Schema
-- ==============================================================================
-- Brings the live project up to the schema declared in supabase-schema.sql so
-- the backend can actually persist telemetry (psutil expanded metrics) and
-- fleet metadata. Fully idempotent: re-running is a no-op.
--
-- RLS is NOT weakened: no policy is dropped or relaxed. The service-role
-- SELECT policy for the baseline RPC matches supabase-schema.sql exactly.
-- ==============================================================================

-- 1. Expanded psutil telemetry columns on server_metrics (schema.sql L169-180)
ALTER TABLE public.server_metrics
  ADD COLUMN IF NOT EXISTS disk_usage FLOAT;
ALTER TABLE public.server_metrics
  ADD COLUMN IF NOT EXISTS disk_io JSONB;
ALTER TABLE public.server_metrics
  ADD COLUMN IF NOT EXISTS system_uptime FLOAT;
ALTER TABLE public.server_metrics
  ADD COLUMN IF NOT EXISTS load_average JSONB;
ALTER TABLE public.server_metrics
  ADD COLUMN IF NOT EXISTS process_count INTEGER;
ALTER TABLE public.server_metrics
  ADD COLUMN IF NOT EXISTS network_stats JSONB;

-- Cost is no longer written per-metric (real spend lives in daily_costs);
-- relax the old NOT NULL so new rows may omit it (schema.sql L146-147).
ALTER TABLE public.server_metrics
  ALTER COLUMN estimated_cost_per_hour DROP NOT NULL;

-- 2. Fleet ownership / ingestion-token columns (schema.sql L136-142)
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS owner_id UUID REFERENCES auth.users(id);
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS ingestion_token TEXT
    NOT NULL DEFAULT encode(gen_random_bytes(32), 'hex') UNIQUE;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS cost_tag TEXT;

-- 3. Source + AWS discovery / inventory columns (schema.sql L149-166, Migration 006/007)
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'agent'
    CHECK (source IN ('agent', 'aws_discovery'));
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_instance_id TEXT UNIQUE;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_resource_id TEXT;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_region TEXT;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_availability_zone TEXT;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_state TEXT;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_launch_time TIMESTAMPTZ;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_tags JSONB DEFAULT '{}'::jsonb;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_account_id TEXT;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS private_ip TEXT;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS public_ip TEXT;
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS resource_type TEXT DEFAULT 'ec2';
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS last_discovered_at TIMESTAMPTZ;

-- 4. Lookup indexes (idempotent)
CREATE INDEX IF NOT EXISTS idx_servers_source ON public.servers(source);
CREATE INDEX IF NOT EXISTS idx_servers_aws_instance_id ON public.servers(aws_instance_id);
CREATE INDEX IF NOT EXISTS idx_servers_aws_resource_id ON public.servers(aws_resource_id);
CREATE INDEX IF NOT EXISTS idx_servers_aws_account_id ON public.servers(aws_account_id);
CREATE INDEX IF NOT EXISTS idx_servers_resource_type ON public.servers(resource_type);
CREATE INDEX IF NOT EXISTS idx_server_metrics_server_recorded
  ON public.server_metrics(server_id, recorded_at DESC);

-- 5. Statistical baseline RPCs used by anomaly detection (schema.sql L96-131)
CREATE OR REPLACE FUNCTION public.metrics_baseline(p_server_id UUID, p_days INT)
RETURNS TABLE(
  cpu_mean float8, cpu_std float8,
  ram_mean float8, ram_std float8,
  net_mean float8, net_std float8,
  sample_count bigint
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
  SELECT avg(cpu_usage)::float8,       stddev_pop(cpu_usage)::float8,
         avg(ram_usage)::float8,       stddev_pop(ram_usage)::float8,
         avg(network_traffic)::float8, stddev_pop(network_traffic)::float8,
         count(*)::bigint
  FROM public.server_metrics
  WHERE server_id = p_server_id
    AND recorded_at >= now() - make_interval(days => p_days);
$$;

CREATE OR REPLACE FUNCTION public.metrics_utilization(
  p_server_id UUID, p_days INT, p_cpu_floor float8, p_ram_floor float8
)
RETURNS TABLE(
  total_samples bigint, idle_samples bigint, avg_cpu float8, avg_ram float8
)
LANGUAGE sql STABLE SECURITY INVOKER
AS $$
  SELECT count(*)::bigint,
         count(*) FILTER (WHERE cpu_usage < p_cpu_floor AND ram_usage < p_ram_floor)::bigint,
         avg(cpu_usage)::float8,
         avg(ram_usage)::float8
  FROM public.server_metrics
  WHERE server_id = p_server_id
    AND recorded_at >= now() - make_interval(days => p_days);
$$;

-- Belt-and-suspenders grants (service-role bypasses RLS anyway; the functions
-- are SECURITY INVOKER so end users stay restricted by their own policies).
GRANT EXECUTE ON FUNCTION public.metrics_baseline(uuid, integer)
  TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.metrics_utilization(uuid, integer, float8, float8)
  TO authenticated, service_role;

-- 6. Reload PostgREST schema cache so new columns/RPCs are exposed immediately.
NOTIFY pgrst, 'reload schema';
