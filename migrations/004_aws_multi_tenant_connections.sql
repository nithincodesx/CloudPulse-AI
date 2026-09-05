-- ================================================================
-- Migration 004: Multi-Tenant SaaS AWS Connection System
-- Enables cross-account IAM role assumption via STS AssumeRole with ExternalId
-- ================================================================

CREATE TABLE IF NOT EXISTS public.aws_connections (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  aws_account_id   TEXT,
  role_arn         TEXT,
  external_id      TEXT NOT NULL UNIQUE,
  region           TEXT NOT NULL DEFAULT 'us-east-1',
  display_name     TEXT NOT NULL DEFAULT 'AWS Account',
  status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'connected', 'error', 'disconnected')),
  error_message    TEXT,
  last_verified_at TIMESTAMPTZ,
  last_sync_at     TIMESTAMPTZ,
  created_at       TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at       TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Indexes for fast lookup by user and external_id
CREATE INDEX IF NOT EXISTS idx_aws_connections_user_status
  ON public.aws_connections (user_id, status);

CREATE INDEX IF NOT EXISTS idx_aws_connections_external_id
  ON public.aws_connections (external_id);

-- Optional association: link servers to an aws_connection
ALTER TABLE public.servers
  ADD COLUMN IF NOT EXISTS aws_connection_id UUID REFERENCES public.aws_connections(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_servers_aws_connection
  ON public.servers (aws_connection_id);

-- Enable Row Level Security (RLS)
ALTER TABLE public.aws_connections ENABLE ROW LEVEL SECURITY;

-- RLS Policies: Users only access their own connections; Service Role has full access
DROP POLICY IF EXISTS "Users can view own AWS connections" ON public.aws_connections;
CREATE POLICY "Users can view own AWS connections"
  ON public.aws_connections FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own AWS connections" ON public.aws_connections;
CREATE POLICY "Users can insert own AWS connections"
  ON public.aws_connections FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own AWS connections" ON public.aws_connections;
CREATE POLICY "Users can update own AWS connections"
  ON public.aws_connections FOR UPDATE
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own AWS connections" ON public.aws_connections;
CREATE POLICY "Users can delete own AWS connections"
  ON public.aws_connections FOR DELETE
  TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role full access on aws_connections" ON public.aws_connections;
CREATE POLICY "Service role full access on aws_connections"
  ON public.aws_connections FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
