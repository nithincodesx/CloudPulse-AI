import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import type {
  DashboardData,
  Alert,
  CloudStatus,
  SyncResult,
  DiscoveryResult,
  WeeklyInsight,
  InsightGenerateResult,
  AnomalyEvent,
  OptimizationRecommendation,
  OptimizationSummary,
  ServerBaselineInfo,
  Incident,
  IncidentNote,
  IncidentTimeline,
  AlertRule,
  NotificationChannel,
  NotificationLog,
  AIInvestigation,
  AWSConnection,
  AWSConnectionInitiateResult,
  AWSConnectionVerifyResult,
  Organization,
  OrganizationMember,
  AuditLog,
  AWSHealthDiagnosticResult,
  OrganizationUsage,
  OrgRole,
} from "./types";

// Browser Supabase client — powers auth (login/magic link) and owns-server
// provisioning. Env vars are injected at build time via NEXT_PUBLIC_*.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error(
    "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set in " +
      "frontend/.env.local (copy frontend/.env.local.example)."
  );
}

export const supabase: SupabaseClient = createBrowserClient(supabaseUrl, supabaseAnonKey);

// ---------------------------------------------------------------------------
// Backend API calls (real backend integration). The dashboard reads through
// the FastAPI backend; the Supabase client is used for auth + provisioning.
// ---------------------------------------------------------------------------
// Backend API base URL. No silent localhost fallback — if it's missing we fail
// fast so a misconfigured deploy can't quietly point the browser at localhost.
// Set NEXT_PUBLIC_API_URL in frontend/.env.local (dev) or the Vercel dashboard
// (production = the deployed Render URL).
const API_URL = process.env.NEXT_PUBLIC_API_URL;

if (!API_URL) {
  throw new Error(
    "NEXT_PUBLIC_API_URL must be set in frontend/.env.local (copy " +
      "frontend/.env.local.example) or as a Vercel environment variable."
  );
}

export async function fetchDashboardData(): Promise<DashboardData> {
  const res = await fetch(`${API_URL}/api/servers/status`);
  if (!res.ok) throw new Error("Failed to fetch from backend");
  return await res.json();
}

export async function fetchAllAlerts(): Promise<Alert[]> {
  const res = await fetch(`${API_URL}/api/alerts`);
  if (!res.ok) throw new Error("Failed to fetch alerts");
  return await res.json();
}

export async function resolveAlert(alertId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/${alertId}/resolve`, {
      method: "PATCH",
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to resolve alert", error);
    return false;
  }
}

export async function fetchCloudStatus(): Promise<CloudStatus> {
  const res = await fetch(`${API_URL}/api/cloud/status`);
  if (!res.ok) throw new Error("Failed to fetch cloud status");
  return await res.json();
}

export async function triggerCostSync(): Promise<SyncResult> {
  const res = await fetch(`${API_URL}/api/cloud/sync`, { method: "POST" });
  if (!res.ok) {
    let detail = `Sync failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }
  return await res.json();
}

export async function triggerResourceDiscovery(region?: string): Promise<DiscoveryResult> {
  const url = region
    ? `${API_URL}/api/cloud/discover?region=${encodeURIComponent(region)}`
    : `${API_URL}/api/cloud/discover`;
  const res = await fetch(url, { method: "POST" });
  if (!res.ok) {
    let detail = `Discovery failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }
  return await res.json();
}

export async function fetchLatestInsight(): Promise<WeeklyInsight | null> {
  const res = await fetch(`${API_URL}/api/insights/latest`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Failed to fetch weekly insight");
  return await res.json();
}

export async function generateInsight(): Promise<InsightGenerateResult> {
  const res = await fetch(`${API_URL}/api/insights/generate`, { method: "POST" });
  if (!res.ok) {
    let detail = `Generation failed (${res.status})`;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // non-JSON error body
    }
    throw new Error(detail);
  }
  return await res.json();
}

export async function updateServerStatus(serverId: string, status: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/servers/${serverId}/status`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to update server status", error);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Phase 2: Anomaly Events & Baseline Envelopes
// ---------------------------------------------------------------------------

export async function fetchAnomalyEvents(params?: {
  server_id?: string;
  severity?: string;
  resolved?: boolean;
}): Promise<AnomalyEvent[]> {
  const query = new URLSearchParams();
  if (params?.server_id) query.set("server_id", params.server_id);
  if (params?.severity) query.set("severity", params.severity);
  if (params?.resolved !== undefined) query.set("resolved", String(params.resolved));

  const qs = query.toString();
  const url = qs ? `${API_URL}/api/anomalies?${qs}` : `${API_URL}/api/anomalies`;
  const res = await fetch(url);
  if (!res.ok) return [];
  return await res.json();
}

export async function resolveAnomalyEvent(eventId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/anomalies/${eventId}/resolve`, {
      method: "PATCH",
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to resolve anomaly event", error);
    return false;
  }
}

export async function fetchServerBaseline(serverId: string): Promise<ServerBaselineInfo | null> {
  try {
    const res = await fetch(`${API_URL}/api/anomalies/baseline/${serverId}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch server baseline", error);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Phase 2: Cost Optimization Engine
// ---------------------------------------------------------------------------

export async function fetchOptimizationSummary(): Promise<OptimizationSummary | null> {
  try {
    const res = await fetch(`${API_URL}/api/optimization/summary`);
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch optimization summary", error);
    return null;
  }
}

export async function fetchOptimizationRecommendations(filters?: {
  server_id?: string;
  service_name?: string;
  region?: string;
  severity?: string;
  recommendation_type?: string;
  status?: string;
}): Promise<OptimizationRecommendation[]> {
  try {
    const query = new URLSearchParams();
    if (filters?.server_id) query.set("server_id", filters.server_id);
    if (filters?.service_name) query.set("service_name", filters.service_name);
    if (filters?.region) query.set("region", filters.region);
    if (filters?.severity) query.set("severity", filters.severity);
    if (filters?.recommendation_type) query.set("recommendation_type", filters.recommendation_type);
    if (filters?.status) query.set("status", filters.status);

    const qs = query.toString();
    const url = qs ? `${API_URL}/api/optimization/recommendations?${qs}` : `${API_URL}/api/optimization/recommendations`;
    const res = await fetch(url);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch optimization recommendations", error);
    return [];
  }
}

export async function triggerOptimizationAnalysis(): Promise<{
  analyzed_servers_count: number;
  recommendations_generated_count: number;
  summary: OptimizationSummary;
  recommendations: OptimizationRecommendation[];
} | null> {
  try {
    const res = await fetch(`${API_URL}/api/optimization/analyze`, { method: "POST" });
    if (!res.ok) throw new Error("Failed to trigger optimization analysis");
    return await res.json();
  } catch (error) {
    console.error("Failed to trigger optimization analysis", error);
    return null;
  }
}

export async function updateRecommendationStatus(
  recommendationId: string,
  status: "active" | "applied" | "dismissed"
): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/optimization/recommendations/${recommendationId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to update recommendation status", error);
    return false;
  }
}

// ---------------------------------------------------------------------------
// Phase 3: Incidents & Investigations API
// ---------------------------------------------------------------------------

export async function fetchIncidents(statusFilter?: string): Promise<Incident[]> {
  try {
    const url = statusFilter && statusFilter !== "all"
      ? `${API_URL}/api/incidents?status=${statusFilter}`
      : `${API_URL}/api/incidents`;
    const res = await fetch(url);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch incidents", error);
    return [];
  }
}

export async function fetchIncidentDetail(incidentId: string): Promise<Incident | null> {
  try {
    const res = await fetch(`${API_URL}/api/incidents/${incidentId}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch incident detail", error);
    return null;
  }
}

export async function updateIncidentStatus(
  incidentId: string,
  status: "open" | "acknowledged" | "resolved",
  actor: string = "Operator",
  resolutionNotes?: string
): Promise<Incident | null> {
  try {
    const res = await fetch(`${API_URL}/api/incidents/${incidentId}/status`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, actor, resolution_notes: resolutionNotes }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to update incident status", error);
    return null;
  }
}

export async function addIncidentNote(
  incidentId: string,
  authorName: string,
  noteText: string
): Promise<IncidentNote | null> {
  try {
    const res = await fetch(`${API_URL}/api/incidents/${incidentId}/notes`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ author_name: authorName, note_text: noteText }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to add incident note", error);
    return null;
  }
}

export async function triggerIncidentInvestigation(incidentId: string): Promise<AIInvestigation | null> {
  try {
    const res = await fetch(`${API_URL}/api/incidents/${incidentId}/investigate`, {
      method: "POST",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to trigger incident AI investigation", error);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Phase 3: Alert Rules & Notification Channels API
// ---------------------------------------------------------------------------

export async function fetchAlertRules(): Promise<AlertRule[]> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/rules`);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch alert rules", error);
    return [];
  }
}

export async function saveAlertRule(rule: Partial<AlertRule>): Promise<AlertRule | null> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/rules`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rule),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to save alert rule", error);
    return null;
  }
}

export async function deleteAlertRule(ruleId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/rules/${ruleId}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to delete alert rule", error);
    return false;
  }
}

export async function fetchNotificationChannels(): Promise<NotificationChannel[]> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/channels`);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch notification channels", error);
    return [];
  }
}

export async function saveNotificationChannel(channel: Partial<NotificationChannel>): Promise<NotificationChannel | null> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/channels`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(channel),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to save notification channel", error);
    return null;
  }
}

export async function deleteNotificationChannel(channelId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/channels/${channelId}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to delete notification channel", error);
    return false;
  }
}

export async function testNotificationChannel(channelId: string): Promise<{
  status: string;
  recipient_target: string;
  error_message?: string | null;
} | null> {
  try {
    const res = await fetch(`${API_URL}/api/alerts/channels/${channelId}/test`, {
      method: "POST",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to test notification channel", error);
    return null;
  }
}

export async function fetchNotificationLogs(incidentId?: string): Promise<NotificationLog[]> {
  try {
    const url = incidentId
      ? `${API_URL}/api/alerts/logs?incident_id=${incidentId}`
      : `${API_URL}/api/alerts/logs`;
    const res = await fetch(url);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch notification logs", error);
    return [];
  }
}

// ---------------------------------------------------------------------------
// Phase 4: Multi-Tenant SaaS AWS Connections API
// ---------------------------------------------------------------------------

export async function initiateAWSConnection(region: string = "us-east-1"): Promise<AWSConnectionInitiateResult | null> {
  try {
    const res = await fetch(`${API_URL}/api/aws/connections/initiate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ region }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to initiate AWS connection", error);
    return null;
  }
}

export async function fetchAWSConnections(): Promise<AWSConnection[]> {
  try {
    const res = await fetch(`${API_URL}/api/aws/connections`);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch AWS connections", error);
    return [];
  }
}

export async function saveAWSConnection(data: {
  role_arn: string;
  external_id: string;
  display_name: string;
  region: string;
  aws_account_id?: string;
}): Promise<AWSConnection | null> {
  try {
    const res = await fetch(`${API_URL}/api/aws/connections`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const errJson = await res.json().catch(() => ({}));
      throw new Error(errJson.detail || "Failed to save AWS connection");
    }
    return await res.json();
  } catch (error) {
    console.error("Failed to save AWS connection", error);
    throw error;
  }
}

export async function verifyAWSConnection(connectionId: string): Promise<AWSConnectionVerifyResult | null> {
  try {
    const res = await fetch(`${API_URL}/api/aws/connections/${connectionId}/verify`, {
      method: "POST",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to verify AWS connection", error);
    return null;
  }
}

export async function syncAWSConnection(connectionId: string): Promise<{
  status: string;
  cost_sync: SyncResult;
  discovery: DiscoveryResult;
} | null> {
  try {
    const res = await fetch(`${API_URL}/api/aws/connections/${connectionId}/sync`, {
      method: "POST",
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to sync AWS connection", error);
    return null;
  }
}

export async function deleteAWSConnection(connectionId: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/api/aws/connections/${connectionId}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to delete AWS connection", error);
    return false;
  }
}

export async function fetchAWSConnectionHealth(connectionId: string): Promise<AWSHealthDiagnosticResult | null> {
  try {
    const res = await fetch(`${API_URL}/api/aws/connections/${connectionId}/health`);
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch AWS connection health", error);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Phase 5: Organizations, RBAC, Audit Logs & Usage
// ---------------------------------------------------------------------------

export async function fetchOrganizations(userId?: string, userEmail?: string): Promise<Organization[]> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    if (userEmail) params.append("user_email", userEmail);
    const res = await fetch(`${API_URL}/api/organizations?${params.toString()}`);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch organizations", error);
    return [];
  }
}

export async function createOrganization(
  name: string,
  planTier: string = "free",
  userId?: string,
  userEmail?: string
): Promise<Organization | null> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    if (userEmail) params.append("user_email", userEmail);
    const res = await fetch(`${API_URL}/api/organizations?${params.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, plan_tier: planTier }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to create organization");
    }
    return await res.json();
  } catch (error) {
    console.error("Failed to create organization", error);
    throw error;
  }
}

export async function fetchOrganization(orgId: string, userId?: string): Promise<Organization | null> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    const res = await fetch(`${API_URL}/api/organizations/${orgId}?${params.toString()}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch organization", error);
    return null;
  }
}

export async function updateOrganization(
  orgId: string,
  updates: Partial<Organization>,
  userId?: string
): Promise<Organization | null> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    const res = await fetch(`${API_URL}/api/organizations/${orgId}?${params.toString()}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to update organization", error);
    return null;
  }
}

export async function deleteOrganization(orgId: string, userId?: string): Promise<boolean> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    const res = await fetch(`${API_URL}/api/organizations/${orgId}?${params.toString()}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to delete organization", error);
    return false;
  }
}

export async function fetchOrgMembers(orgId: string): Promise<OrganizationMember[]> {
  try {
    const res = await fetch(`${API_URL}/api/organizations/${orgId}/members`);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch organization members", error);
    return [];
  }
}

export async function inviteOrgMember(
  orgId: string,
  email: string,
  role: OrgRole = "MEMBER",
  userId?: string,
  userEmail?: string
): Promise<OrganizationMember | null> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    if (userEmail) params.append("user_email", userEmail);
    const res = await fetch(`${API_URL}/api/organizations/${orgId}/members?${params.toString()}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to invite member");
    }
    return await res.json();
  } catch (error) {
    console.error("Failed to invite organization member", error);
    throw error;
  }
}

export async function updateOrgMemberRole(
  orgId: string,
  memberId: string,
  role: OrgRole,
  userId?: string,
  userEmail?: string
): Promise<OrganizationMember | null> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    if (userEmail) params.append("user_email", userEmail);
    const res = await fetch(`${API_URL}/api/organizations/${orgId}/members/${memberId}?${params.toString()}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to update organization member role", error);
    return null;
  }
}

export async function removeOrgMember(
  orgId: string,
  memberId: string,
  userId?: string,
  userEmail?: string
): Promise<boolean> {
  try {
    const params = new URLSearchParams();
    if (userId) params.append("user_id", userId);
    if (userEmail) params.append("user_email", userEmail);
    const res = await fetch(`${API_URL}/api/organizations/${orgId}/members/${memberId}?${params.toString()}`, {
      method: "DELETE",
    });
    return res.ok;
  } catch (error) {
    console.error("Failed to remove organization member", error);
    return false;
  }
}

export async function fetchAuditLogs(
  orgId: string,
  limit: number = 50,
  offset: number = 0,
  action?: string
): Promise<AuditLog[]> {
  try {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString(),
    });
    if (action) params.append("action", action);
    const res = await fetch(`${API_URL}/api/organizations/${orgId}/audit-logs?${params.toString()}`);
    if (!res.ok) return [];
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch audit logs", error);
    return [];
  }
}

export async function fetchOrgUsage(orgId: string): Promise<OrganizationUsage | null> {
  try {
    const res = await fetch(`${API_URL}/api/organizations/${orgId}/usage`);
    if (!res.ok) return null;
    return await res.json();
  } catch (error) {
    console.error("Failed to fetch organization usage", error);
    return null;
  }
}

// Subscriptions are no longer used since we rely on the backend and polling.
export function subscribeToAlerts(callback: (payload: any) => void) {
  return null;
}


