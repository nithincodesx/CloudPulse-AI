-- ================================================================
-- CloudPulse AI — Migration 005: Multi-Tenant SaaS Organizations & RBAC
-- Adds Organizations, Organization Members (OWNER/ADMIN/MEMBER/VIEWER),
-- Audit Logs, and links all cloud resources, AWS connections, and alerts
-- to tenant organizations with Supabase RLS.
-- ================================================================

-- 1. Organizations table
CREATE TABLE IF NOT EXISTS public.organizations (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                 TEXT NOT NULL,
    slug                 TEXT NOT NULL UNIQUE,
    plan_tier            TEXT NOT NULL DEFAULT 'free' CHECK (plan_tier IN ('free', 'starter', 'pro', 'enterprise')),
    max_aws_connections INT NOT NULL DEFAULT 5,
    retention_days       INT NOT NULL DEFAULT 30,
    created_at           TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at           TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_organizations_slug ON public.organizations(slug);

-- 2. Organization Members table
CREATE TABLE IF NOT EXISTS public.organization_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL DEFAULT 'MEMBER' CHECK (role IN ('OWNER', 'ADMIN', 'MEMBER', 'VIEWER')),
    invited_email   TEXT,
    created_at      TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    updated_at      TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE (organization_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_org_members_user ON public.organization_members(user_id);
CREATE INDEX IF NOT EXISTS idx_org_members_org ON public.organization_members(organization_id);

-- 3. Audit Logs table
CREATE TABLE IF NOT EXISTS public.audit_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
    actor_id        UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    actor_email     TEXT,
    action          TEXT NOT NULL,
    resource_type   TEXT NOT NULL,
    resource_id     TEXT,
    metadata        JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_org_time ON public.audit_logs(organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON public.audit_logs(action);

-- 4. Add organization_id to existing tables
ALTER TABLE public.servers
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_servers_org ON public.servers(organization_id);

ALTER TABLE public.aws_connections
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS health_status TEXT DEFAULT 'UNVERIFIED' CHECK (health_status IN ('HEALTHY', 'DEGRADED', 'ERROR', 'UNVERIFIED')),
ADD COLUMN IF NOT EXISTS health_checks JSONB DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS last_sync_started TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS last_sync_completed TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS sync_status TEXT DEFAULT 'IDLE' CHECK (sync_status IN ('IDLE', 'SYNCING', 'SUCCESS', 'FAILED')),
ADD COLUMN IF NOT EXISTS sync_error TEXT;

CREATE INDEX IF NOT EXISTS idx_aws_connections_org ON public.aws_connections(organization_id);

ALTER TABLE public.incidents
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_incidents_org ON public.incidents(organization_id);

ALTER TABLE public.alert_rules
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_alert_rules_org ON public.alert_rules(organization_id);

ALTER TABLE public.notification_channels
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_notif_channels_org ON public.notification_channels(organization_id);

ALTER TABLE public.cost_anomalies
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_cost_anomalies_org ON public.cost_anomalies(organization_id);

ALTER TABLE public.optimization_recommendations
ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES public.organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_opt_recs_org ON public.optimization_recommendations(organization_id);

-- 5. Backfill existing users with default Personal Workspace
DO $$
DECLARE
    r RECORD;
    new_org_id UUID;
BEGIN
    FOR r IN SELECT id, email FROM auth.users LOOP
        -- Check if user already belongs to an organization
        IF NOT EXISTS (SELECT 1 FROM public.organization_members WHERE user_id = r.id) THEN
            -- Create organization
            INSERT INTO public.organizations (name, slug, plan_tier)
            VALUES (
                COALESCE(split_part(r.email, '@', 1) || '''s Workspace', 'My Workspace'),
                'org-' || encode(gen_random_bytes(6), 'hex'),
                'free'
            )
            RETURNING id INTO new_org_id;

            -- Make user OWNER
            INSERT INTO public.organization_members (organization_id, user_id, role)
            VALUES (new_org_id, r.id, 'OWNER');

            -- Associate existing servers
            UPDATE public.servers
            SET organization_id = new_org_id
            WHERE owner_id = r.id AND organization_id IS NULL;

            -- Associate existing aws_connections
            UPDATE public.aws_connections
            SET organization_id = new_org_id
            WHERE user_id = r.id AND organization_id IS NULL;

            -- Associate alert_rules
            UPDATE public.alert_rules
            SET organization_id = new_org_id
            WHERE user_id = r.id AND organization_id IS NULL;

            -- Associate notification_channels
            UPDATE public.notification_channels
            SET organization_id = new_org_id
            WHERE user_id = r.id AND organization_id IS NULL;
        END IF;
    END LOOP;
END $$;

-- 6. Helper functions for RLS & RBAC
CREATE OR REPLACE FUNCTION public.is_org_member(p_org_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.organization_members
        WHERE organization_id = p_org_id AND user_id = auth.uid()
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION public.get_org_role(p_org_id UUID)
RETURNS TEXT AS $$
DECLARE
    v_role TEXT;
BEGIN
    SELECT role INTO v_role FROM public.organization_members
    WHERE organization_id = p_org_id AND user_id = auth.uid();
    RETURN v_role;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION public.is_org_admin(p_org_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.organization_members
        WHERE organization_id = p_org_id AND user_id = auth.uid() AND role IN ('OWNER', 'ADMIN')
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION public.is_org_owner(p_org_id UUID)
RETURNS BOOLEAN AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM public.organization_members
        WHERE organization_id = p_org_id AND user_id = auth.uid() AND role = 'OWNER'
    );
END;
$$ LANGUAGE plpgsql SECURITY DEFINER STABLE;

-- 7. Enable RLS on newly created tables
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs ENABLE ROW LEVEL SECURITY;

-- Organizations RLS
DROP POLICY IF EXISTS "Members can view their organizations" ON public.organizations;
CREATE POLICY "Members can view their organizations"
    ON public.organizations FOR SELECT
    TO authenticated
    USING (public.is_org_member(id));

DROP POLICY IF EXISTS "Authenticated users can create organizations" ON public.organizations;
CREATE POLICY "Authenticated users can create organizations"
    ON public.organizations FOR INSERT
    TO authenticated
    WITH CHECK (true);

DROP POLICY IF EXISTS "Owners can update organization settings" ON public.organizations;
CREATE POLICY "Owners can update organization settings"
    ON public.organizations FOR UPDATE
    TO authenticated
    USING (public.is_org_owner(id))
    WITH CHECK (public.is_org_owner(id));

DROP POLICY IF EXISTS "Owners can delete organization" ON public.organizations;
CREATE POLICY "Owners can delete organization"
    ON public.organizations FOR DELETE
    TO authenticated
    USING (public.is_org_owner(id));

DROP POLICY IF EXISTS "Service role full access on organizations" ON public.organizations;
CREATE POLICY "Service role full access on organizations"
    ON public.organizations FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Organization Members RLS
DROP POLICY IF EXISTS "Members can view members in their orgs" ON public.organization_members;
CREATE POLICY "Members can view members in their orgs"
    ON public.organization_members FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS "Admins and Owners can insert org members" ON public.organization_members;
CREATE POLICY "Admins and Owners can insert org members"
    ON public.organization_members FOR INSERT
    TO authenticated
    WITH CHECK (public.is_org_admin(organization_id) OR auth.uid() = user_id);

DROP POLICY IF EXISTS "Admins and Owners can update org members" ON public.organization_members;
CREATE POLICY "Admins and Owners can update org members"
    ON public.organization_members FOR UPDATE
    TO authenticated
    USING (public.is_org_admin(organization_id))
    WITH CHECK (public.is_org_admin(organization_id));

DROP POLICY IF EXISTS "Admins and Owners can delete org members" ON public.organization_members;
CREATE POLICY "Admins and Owners can delete org members"
    ON public.organization_members FOR DELETE
    TO authenticated
    USING (public.is_org_admin(organization_id) OR auth.uid() = user_id);

DROP POLICY IF EXISTS "Service role full access on organization_members" ON public.organization_members;
CREATE POLICY "Service role full access on organization_members"
    ON public.organization_members FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Audit Logs RLS
DROP POLICY IF EXISTS "Members can view audit logs for their org" ON public.audit_logs;
CREATE POLICY "Members can view audit logs for their org"
    ON public.audit_logs FOR SELECT
    TO authenticated
    USING (public.is_org_member(organization_id));

DROP POLICY IF EXISTS "Members can insert audit logs for their org" ON public.audit_logs;
CREATE POLICY "Members can insert audit logs for their org"
    ON public.audit_logs FOR INSERT
    TO authenticated
    WITH CHECK (public.is_org_member(organization_id));

DROP POLICY IF EXISTS "Service role full access on audit_logs" ON public.audit_logs;
CREATE POLICY "Service role full access on audit_logs"
    ON public.audit_logs FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Update AWS Connections RLS to check organization membership & admin role
DROP POLICY IF EXISTS "Users can view own AWS connections" ON public.aws_connections;
CREATE POLICY "Users can view own AWS connections"
    ON public.aws_connections FOR SELECT
    TO authenticated
    USING (
        (organization_id IS NOT NULL AND public.is_org_member(organization_id))
        OR auth.uid() = user_id
    );

DROP POLICY IF EXISTS "Admins can insert AWS connections" ON public.aws_connections;
CREATE POLICY "Admins can insert AWS connections"
    ON public.aws_connections FOR INSERT
    TO authenticated
    WITH CHECK (
        (organization_id IS NOT NULL AND public.is_org_admin(organization_id))
        OR auth.uid() = user_id
    );

DROP POLICY IF EXISTS "Admins can update AWS connections" ON public.aws_connections;
CREATE POLICY "Admins can update AWS connections"
    ON public.aws_connections FOR UPDATE
    TO authenticated
    USING (
        (organization_id IS NOT NULL AND public.is_org_admin(organization_id))
        OR auth.uid() = user_id
    )
    WITH CHECK (
        (organization_id IS NOT NULL AND public.is_org_admin(organization_id))
        OR auth.uid() = user_id
    );

DROP POLICY IF EXISTS "Admins can delete AWS connections" ON public.aws_connections;
CREATE POLICY "Admins can delete AWS connections"
    ON public.aws_connections FOR DELETE
    TO authenticated
    USING (
        (organization_id IS NOT NULL AND public.is_org_admin(organization_id))
        OR auth.uid() = user_id
    );
