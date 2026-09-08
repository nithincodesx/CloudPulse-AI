-- ==============================================================================
-- CloudPulse AI — Migration 006: Enhanced AWS Resource Inventory & Discovery Metadata
-- ==============================================================================

-- 1. Extend servers table with granular AWS inventory fields
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_resource_id TEXT,
  ADD COLUMN IF NOT EXISTS aws_account_id TEXT,
  ADD COLUMN IF NOT EXISTS private_ip TEXT,
  ADD COLUMN IF NOT EXISTS public_ip TEXT,
  ADD COLUMN IF NOT EXISTS resource_type TEXT DEFAULT 'ec2';

-- 2. Performance indexes for multi-tenant resource resolution
CREATE INDEX IF NOT EXISTS idx_servers_aws_resource_id ON public.servers(aws_resource_id);
CREATE INDEX IF NOT EXISTS idx_servers_aws_account_id ON public.servers(aws_account_id);
CREATE INDEX IF NOT EXISTS idx_servers_resource_type ON public.servers(resource_type);
