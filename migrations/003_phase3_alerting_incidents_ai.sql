-- ================================================================
-- CloudPulse AI — Phase 3 Migration: Grounded AI Investigation,
-- Smart Alerting Pipeline, Alert Rules & Incident Lifecycle
-- ================================================================

-- 1. Notification Channels
CREATE TABLE IF NOT EXISTS public.notification_channels (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id     UUID REFERENCES auth.users(id),
  name         TEXT NOT NULL,
  channel_type TEXT NOT NULL CHECK (channel_type IN ('webhook', 'discord', 'slack', 'email')),
  config       JSONB NOT NULL DEFAULT '{}'::jsonb,
  enabled      BOOLEAN NOT NULL DEFAULT true,
  created_at   TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 2. Alert Rules
CREATE TABLE IF NOT EXISTS public.alert_rules (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id          UUID REFERENCES auth.users(id),
  name              TEXT NOT NULL,
  rule_type         TEXT NOT NULL CHECK (rule_type IN ('CPU_ANOMALY', 'RAM_ANOMALY', 'NETWORK_ANOMALY', 'IDLE_RESOURCE', 'BUDGET_SPIKE', 'SAVINGS_THRESHOLD', 'CUSTOM')),
  condition_config  JSONB NOT NULL DEFAULT '{}'::jsonb,
  severity          TEXT NOT NULL DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'critical')),
  cooldown_minutes  INT NOT NULL DEFAULT 15,
  channels          JSONB NOT NULL DEFAULT '["webhook"]'::jsonb,
  enabled           BOOLEAN NOT NULL DEFAULT true,
  created_at        TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at        TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 3. Incidents
CREATE TABLE IF NOT EXISTS public.incidents (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  server_id           UUID NOT NULL REFERENCES public.servers(id) ON DELETE CASCADE,
  title               TEXT NOT NULL,
  description         TEXT NOT NULL,
  incident_type       TEXT NOT NULL,
  severity            TEXT NOT NULL DEFAULT 'warning' CHECK (severity IN ('info', 'warning', 'critical')),
  status              TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'acknowledged', 'resolved')),
  root_cause_summary  TEXT,
  ai_investigation    JSONB NOT NULL DEFAULT '{}'::jsonb,
  acknowledged_at     TIMESTAMPTZ,
  acknowledged_by     TEXT,
  resolved_at         TIMESTAMPTZ,
  resolved_by         TEXT,
  created_at          TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL,
  updated_at          TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_server_status
  ON public.incidents (server_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_incidents_status_severity
  ON public.incidents (status, severity, created_at DESC);

-- 4. Incident Timeline
CREATE TABLE IF NOT EXISTS public.incident_timeline (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id  UUID NOT NULL REFERENCES public.incidents(id) ON DELETE CASCADE,
  event_type   TEXT NOT NULL,
  actor        TEXT NOT NULL DEFAULT 'system',
  message      TEXT NOT NULL,
  meta         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incident_timeline_inc
  ON public.incident_timeline (incident_id, created_at ASC);

-- 5. Incident Notes
CREATE TABLE IF NOT EXISTS public.incident_notes (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  incident_id  UUID NOT NULL REFERENCES public.incidents(id) ON DELETE CASCADE,
  user_id      UUID REFERENCES auth.users(id),
  author_name  TEXT NOT NULL DEFAULT 'Operator',
  note_text    TEXT NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- 6. Notification Logs
CREATE TABLE IF NOT EXISTS public.notification_logs (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id           UUID REFERENCES public.alert_rules(id) ON DELETE SET NULL,
  incident_id       UUID REFERENCES public.incidents(id) ON DELETE SET NULL,
  server_id         UUID REFERENCES public.servers(id) ON DELETE CASCADE,
  channel_type      TEXT NOT NULL,
  severity          TEXT NOT NULL,
  recipient_target  TEXT,
  status            TEXT NOT NULL CHECK (status IN ('sent', 'failed', 'cooldown_skipped')),
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  error_message     TEXT,
  created_at        TIMESTAMPTZ DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notif_logs_incident
  ON public.notification_logs (incident_id, created_at DESC);

-- Enable RLS
ALTER TABLE public.notification_channels ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alert_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_timeline ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.incident_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notification_logs ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "users_manage_own_channels" ON public.notification_channels
  FOR ALL USING (auth.uid() = owner_id OR owner_id IS NULL);

CREATE POLICY "users_manage_own_rules" ON public.alert_rules
  FOR ALL USING (auth.uid() = owner_id OR owner_id IS NULL);

CREATE POLICY "users_manage_own_incidents" ON public.incidents
  FOR ALL USING (
    EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = incidents.server_id AND (s.owner_id = auth.uid() OR s.owner_id IS NULL))
  );

CREATE POLICY "users_manage_own_incident_timeline" ON public.incident_timeline
  FOR ALL USING (
    EXISTS (SELECT 1 FROM public.incidents i
            JOIN public.servers s ON s.id = i.server_id
            WHERE i.id = incident_timeline.incident_id AND (s.owner_id = auth.uid() OR s.owner_id IS NULL))
  );

CREATE POLICY "users_manage_own_incident_notes" ON public.incident_notes
  FOR ALL USING (
    EXISTS (SELECT 1 FROM public.incidents i
            JOIN public.servers s ON s.id = i.server_id
            WHERE i.id = incident_notes.incident_id AND (s.owner_id = auth.uid() OR s.owner_id IS NULL))
  );

CREATE POLICY "users_read_own_notif_logs" ON public.notification_logs
  FOR SELECT USING (
    server_id IS NULL OR EXISTS (SELECT 1 FROM public.servers s
            WHERE s.id = notification_logs.server_id AND (s.owner_id = auth.uid() OR s.owner_id IS NULL))
  );
