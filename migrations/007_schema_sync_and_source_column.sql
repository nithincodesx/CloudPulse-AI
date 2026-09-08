-- ==============================================================================
-- CloudPulse AI — Migration 007: Safe Schema Synchronization & Source Column
-- ==============================================================================

-- 1. Ensure source column exists on servers with default 'agent'
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'agent'
  CHECK (source IN ('agent', 'aws_discovery'));

-- 2. Ensure AWS discovery & inventory columns exist
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_instance_id TEXT,
  ADD COLUMN IF NOT EXISTS aws_resource_id TEXT,
  ADD COLUMN IF NOT EXISTS aws_region TEXT,
  ADD COLUMN IF NOT EXISTS aws_availability_zone TEXT,
  ADD COLUMN IF NOT EXISTS aws_state TEXT,
  ADD COLUMN IF NOT EXISTS aws_launch_time TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS aws_tags JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS aws_account_id TEXT,
  ADD COLUMN IF NOT EXISTS private_ip TEXT,
  ADD COLUMN IF NOT EXISTS public_ip TEXT,
  ADD COLUMN IF NOT EXISTS resource_type TEXT DEFAULT 'ec2',
  ADD COLUMN IF NOT EXISTS last_discovered_at TIMESTAMPTZ;

-- 3. Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_servers_source ON public.servers(source);
CREATE INDEX IF NOT EXISTS idx_servers_aws_instance_id ON public.servers(aws_instance_id);

-- 4. Reload PostgREST schema cache
NOTIFY pgrst, 'reload schema';
