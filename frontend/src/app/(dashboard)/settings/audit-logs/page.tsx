"use client";

import React, { useState, useEffect } from "react";
import {
  ShieldAlert,
  Search,
  Filter,
  RefreshCw,
  Clock,
  User,
  Activity,
  FileText,
} from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import { fetchOrganizations, fetchAuditLogs } from "@/lib/supabase";
import type { AuditLog, Organization } from "@/lib/types";

export default function AuditLogsPage() {
  const { user } = useAuth();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [activeOrg, setActiveOrg] = useState<Organization | null>(null);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [actionFilter, setActionFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadData = async () => {
    if (!user) return;
    try {
      const orgList = await fetchOrganizations(user.id, user.email);
      setOrgs(orgList);
      const cur = orgList[0] || null;
      setActiveOrg(cur);
      if (cur) {
        const auditData = await fetchAuditLogs(cur.id, 50, 0, actionFilter || undefined);
        setLogs(auditData);
      }
    } catch (err) {
      console.error("Failed to load audit logs", err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [user, actionFilter]);

  const handleRefresh = () => {
    setRefreshing(true);
    loadData();
  };

  const getActionBadge = (action: string) => {
    if (action.includes("CONNECTED") || action.includes("COMPLETED")) {
      return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
    }
    if (action.includes("FAILED") || action.includes("DISCONNECTED") || action.includes("REMOVED")) {
      return "bg-red-500/10 text-red-400 border-red-500/20";
    }
    if (action.includes("TRIGGERED")) {
      return "bg-amber-500/10 text-amber-400 border-amber-500/20";
    }
    return "bg-indigo-500/10 text-indigo-400 border-indigo-500/20";
  };

  if (loading) {
    return <div className="p-6 text-paper/50">Loading audit trail...</div>;
  }

  return (
    <main className="flex-1 p-6 overflow-y-auto space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="eyebrow mb-1">Security & Compliance</div>
          <h1 className="text-2xl font-bold text-white font-heading">Tenant Audit Trail</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Immutable log of sensitive operations, AWS connection events, and administrative changes.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Action Filter */}
          <select
            value={actionFilter}
            onChange={(e) => setActionFilter(e.target.value)}
            className="rounded-xl border border-white/10 bg-[#121218] px-3 py-2 text-xs font-mono text-zinc-300 focus:outline-none"
          >
            <option value="">All Actions</option>
            <option value="AWS_CONNECTED">AWS_CONNECTED</option>
            <option value="AWS_DISCONNECTED">AWS_DISCONNECTED</option>
            <option value="SYNC_COMPLETED">SYNC_COMPLETED</option>
            <option value="SYNC_FAILED">SYNC_FAILED</option>
            <option value="MEMBER_INVITED">MEMBER_INVITED</option>
            <option value="MEMBER_ROLE_UPDATED">MEMBER_ROLE_UPDATED</option>
            <option value="SETTINGS_UPDATED">SETTINGS_UPDATED</option>
          </select>

          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 rounded-xl border border-white/10 bg-[#121218] px-3 py-2 text-xs font-mono text-zinc-300 hover:bg-white/5 disabled:opacity-50"
          >
            <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {/* Audit Log Table */}
      <section className="rounded-2xl border border-white/10 bg-[#121218] overflow-hidden">
        {logs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-white/10 bg-white/[0.02] text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                <tr>
                  <th className="p-4">Timestamp</th>
                  <th className="p-4">Actor</th>
                  <th className="p-4">Action</th>
                  <th className="p-4">Resource</th>
                  <th className="p-4">Metadata</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5 text-zinc-300 font-mono text-[11px]">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-white/[0.02] transition-colors">
                    <td className="p-4 whitespace-nowrap text-zinc-400">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="p-4 whitespace-nowrap">
                      <span className="font-semibold text-white">
                        {log.actor_email || log.actor_id || "system"}
                      </span>
                    </td>
                    <td className="p-4 whitespace-nowrap">
                      <span
                        className={`rounded px-2 py-0.5 text-[9px] font-bold uppercase border ${getActionBadge(
                          log.action
                        )}`}
                      >
                        {log.action}
                      </span>
                    </td>
                    <td className="p-4 whitespace-nowrap text-zinc-400">
                      {log.resource_type} {log.resource_id ? `(${log.resource_id.slice(0, 8)}...)` : ""}
                    </td>
                    <td className="p-4 max-w-xs truncate text-[10px] text-zinc-500">
                      {JSON.stringify(log.metadata)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center text-zinc-500">
            <FileText size={28} className="mb-2 opacity-50" />
            <p className="text-sm font-semibold">No audit records found</p>
            <p className="text-xs mt-1">Actions performed in this workspace will automatically appear here.</p>
          </div>
        )}
      </section>
    </main>
  );
}
