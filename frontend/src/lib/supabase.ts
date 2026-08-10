import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";
import type {
  DashboardData,
  Alert,
  CloudStatus,
  SyncResult,
  WeeklyInsight,
  InsightGenerateResult,
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

// Subscriptions are no longer used since we rely on the backend and polling.
export function subscribeToAlerts(callback: (payload: any) => void) {
  return null;
}
