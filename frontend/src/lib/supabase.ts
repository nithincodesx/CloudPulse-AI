import type { SupabaseClient } from "@supabase/supabase-js";
import type { DashboardData, Alert } from "./types";

/** Lazily-created Supabase client — avoids crashing on build when env vars missing. */
let _supabase: SupabaseClient | null = null;

export function getSupabase(): SupabaseClient | null {
  if (_supabase) return _supabase;
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return null;
  // Dynamic import to avoid build failure when env vars are missing
  const { createClient } = require("@supabase/supabase-js");
  _supabase = createClient(url, key);
  return _supabase;
}

// ---------------------------------------------------------------------------
// API Calls (Real Backend Integration)
// ---------------------------------------------------------------------------
const API_URL = "http://localhost:8000";

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

// Subscriptions are no longer used since we rely on SQLite and polling
export function subscribeToAlerts(callback: (payload: any) => void) {
  return null;
}

