"use client";

import { useState, useEffect } from "react";
import {
  Server,
  Search,
  Plus,
  X,
  Copy,
  Check,
  Loader2,
  CheckCircle2,
  Eye,
  EyeOff,
  Terminal,
  Key,
  PowerOff,
  AlertTriangle,
  Activity,
  Cpu,
  HardDrive,
  Wifi,
  Clock,
  Radio,
} from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
import { supabase, apiFetch } from "@/lib/supabase";
import { useAuth } from "@/lib/AuthContext";
import ServerTable from "@/components/ServerTable";
import CpuRamChart from "@/components/CpuRamChart";
import type { MetricRow, Server as ServerType } from "@/lib/types";

function toChartPoints(metrics: MetricRow[]) {
  return metrics.map((m) => ({
    time: new Date(m.recorded_at).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
    }),
    cpu: m.cpu_usage,
    ram: m.ram_usage,
    network: m.network_traffic,
  }));
}

export default function ServersPage() {
  const { data, loading, loadData, addServerToState, handleServerAction } = useDashboard();
  const { user } = useAuth();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("All");
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);

  // Provisioning modal state
  const [provisionOpen, setProvisionOpen] = useState(false);
  const [provisionStep, setProvisionStep] = useState<"form" | "success">("form");
  const [serverName, setServerName] = useState("");
  const [serverIp, setServerIp] = useState("");
  const [serverCostTag, setServerCostTag] = useState("");
  const [provisioning, setProvisioning] = useState(false);
  const [provisionError, setProvisionError] = useState<string | null>(null);

  // Newly created node details for token display
  const [createdNode, setCreatedNode] = useState<{
    id: string;
    server_name: string;
    ingestion_token: string;
    ip_address?: string | null;
  } | null>(null);
  const [showToken, setShowToken] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedCommand, setCopiedCommand] = useState(false);

  // Direct Supabase query for this user's servers (bypasses backend; RLS ensures user isolation).
  // This is the primary source of truth for the fleet list when the backend returns empty data
  // (which happens when SUPABASE_SERVICE_KEY is misconfigured on the backend).
  const [ownedServers, setOwnedServers] = useState<ServerType[]>([]);
  const [serversLoading, setServersLoading] = useState(true);

  // Node Termination confirmation modal & toast state
  const [terminateModalNode, setTerminateModalNode] = useState<ServerType | null>(null);
  const [isTerminating, setIsTerminating] = useState(false);
  const [terminateError, setTerminateError] = useState<string | null>(null);
  const [terminatingId, setTerminatingId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    if (!toastMessage) return;
    const timer = setTimeout(() => setToastMessage(null), 4000);
    return () => clearTimeout(timer);
  }, [toastMessage]);

  // This user's own servers (RLS-scoped) → ingestion token lookup by server id.
  const [ownedTokens, setOwnedTokens] = useState<Record<string, string>>({});

  const loadOwnedServers = async () => {
    if (!user?.id) return;
    setServersLoading(true);
    try {
      const { data: rows, error } = await supabase
        .from("servers")
        .select("id, server_name, ip_address, ingestion_token, cost_tag, status, created_at, owner_id")
        .order("created_at", { ascending: false });
      if (error) {
        console.error("Fleet fetch error:", error);
        setServersLoading(false);
        return;
      }
      const servers: ServerType[] = (rows ?? []).map((r: any) => ({
        id: r.id,
        server_name: r.server_name,
        ip_address: r.ip_address ?? undefined,
        ingestion_token: r.ingestion_token ?? undefined,
        cost_tag: r.cost_tag ?? undefined,
        status: r.status ?? "active",
        source: "agent" as const,
        resource_type: "ec2",
        created_at: r.created_at ?? undefined,
      }));
      setOwnedServers(servers);

      // Also update token map and sync with backend memory cache
      const map: Record<string, string> = {};
      (rows ?? []).forEach((r: any) => {
        if (r.id && r.ingestion_token) {
          map[r.id] = r.ingestion_token;
          apiFetch("/api/servers/sync-node", {
            method: "POST",
            body: JSON.stringify(r),
          }).catch(() => {});
        }
      });
      setOwnedTokens(map);
    } catch (err) {
      console.error("Fleet query exception:", err);
    } finally {
      setServersLoading(false);
    }
  };

  const loadOwnedTokens = async () => {
    try {
      const { data: rows, error } = await supabase
        .from("servers")
        .select("id, ingestion_token")
        .order("created_at", { ascending: false });
      if (error) return;
      const map: Record<string, string> = {};
      rows?.forEach((r) => {
        if (r.id && r.ingestion_token) map[r.id] = r.ingestion_token;
      });
      setOwnedTokens(map);
    } catch {
      // Ignore token fetch errors
    }
  };

  useEffect(() => {
    loadOwnedServers();
    loadOwnedTokens();
  }, [user]);

  const handleOpenProvision = () => {
    setServerName("");
    setServerIp("");
    setServerCostTag("");
    setProvisionError(null);
    setCreatedNode(null);
    setProvisionStep("form");
    setShowToken(false);
    setProvisionOpen(true);
  };

  const handleCloseProvision = () => {
    setProvisionOpen(false);
    setProvisionStep("form");
    setProvisionError(null);
    setCreatedNode(null);
    setShowToken(false);
  };

  const handleProvision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!serverName.trim()) return;

    setProvisioning(true);
    setProvisionError(null);

    try {
      const nameClean = serverName.trim();
      const ipClean = serverIp.trim() || null;
      const tagClean = serverCostTag.trim() || nameClean;

      const insertPayload: Record<string, any> = {
        server_name: nameClean,
        ip_address: ipClean,
        cost_tag: tagClean,
        status: "active",
      };

      if (user?.id) {
        insertPayload.owner_id = user.id;
      }

      // Execute insert request - guaranteed core columns
      const { data: newRow, error } = await supabase
        .from("servers")
        .insert(insertPayload)
        .select("id, server_name, ip_address, ingestion_token, cost_tag, status, created_at")
        .single();

      if (error) {
        console.error("Supabase insert error:", error);
        let msg = error.message || "Failed to provision server";
        if (error.code === "42501") {
          msg = "Permission denied: Unable to create server row under current security policy.";
        } else if (error.code === "23505") {
          msg = `A node named "${nameClean}" already exists. Please choose a unique name.`;
        }
        throw new Error(msg);
      }

      if (!newRow) {
        throw new Error("No record was returned after server creation.");
      }

      // Store token in local map
      if (newRow.id && newRow.ingestion_token) {
        setOwnedTokens((prev) => ({ ...prev, [newRow.id]: newRow.ingestion_token }));
      }

      // Sync new node into backend registry
      try {
        apiFetch("/api/servers/sync-node", {
          method: "POST",
          body: JSON.stringify(newRow),
        }).catch(() => {});
      } catch {}

      // Immediately inject new node into local UI state so it's visible without waiting for poll
      const newServerObj: ServerType = {
        id: newRow.id,
        server_name: newRow.server_name,
        ip_address: newRow.ip_address || "auto-assigned",
        ingestion_token: newRow.ingestion_token,
        cost_tag: newRow.cost_tag,
        status: (newRow.status as any) || "active",
        source: "agent",
        resource_type: "ec2",
        created_at: newRow.created_at || new Date().toISOString(),
      };
      // Update both the global context state AND our local direct-query state
      addServerToState(newServerObj);
      setOwnedServers((prev) => {
        if (prev.some((s) => s.id === newServerObj.id)) return prev;
        return [newServerObj, ...prev];
      });

      // Force backend + token sync
      await loadOwnedTokens();
      loadData(true);
      // Re-fetch from Supabase directly to get DB-confirmed values
      setTimeout(() => loadOwnedServers(), 1500);

      // Save created node info and transition to success step
      setCreatedNode({
        id: newRow.id,
        server_name: newRow.server_name,
        ingestion_token: newRow.ingestion_token,
        ip_address: newRow.ip_address,
      });
      setProvisionStep("success");
    } catch (err: any) {
      setProvisionError(err?.message || "An unexpected error occurred during provisioning.");
    } finally {
      setProvisioning(false);
    }
  };

  const copyToken = async (token: string) => {
    try {
      await navigator.clipboard.writeText(token);
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 2000);
    } catch {
      // Ignore clipboard error
    }
  };

  const copyAgentCommand = async (token: string) => {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const cmd = `python telemetry_agent.py --token ${token} --url ${backendUrl} --interval 5`;
    try {
      await navigator.clipboard.writeText(cmd);
      setCopiedCommand(true);
      setTimeout(() => setCopiedCommand(false), 2000);
    } catch {
      // Ignore clipboard error
    }
  };

  const handleActionClick = (serverId: string, action: "optimize" | "terminate") => {
    if (action === "optimize") {
      handleServerAction(serverId, "optimize", user?.id);
    } else if (action === "terminate") {
      const target = serverRows.find((s) => s.id === serverId) || ownedServers.find((s) => s.id === serverId);
      if (target) {
        setTerminateModalNode(target);
        setTerminateError(null);
      }
    }
  };

  const handleConfirmTerminate = async () => {
    if (!terminateModalNode || isTerminating) return;
    setIsTerminating(true);
    setTerminatingId(terminateModalNode.id);
    setTerminateError(null);

    try {
      const success = await handleServerAction(terminateModalNode.id, "terminate", user?.id);
      if (success) {
        // Optimistically remove from ownedServers
        setOwnedServers((prev) => prev.filter((s) => s.id !== terminateModalNode.id));
        if (selectedServerId === terminateModalNode.id) {
          setSelectedServerId(null);
        }
        setToastMessage({
          type: "success",
          text: `Node "${terminateModalNode.server_name}" was successfully terminated and removed.`,
        });
        setTerminateModalNode(null);
        // Refresh confirmed data
        loadOwnedServers();
        loadData(true);
      } else {
        setTerminateError("Failed to terminate node. Please check permissions or network connection.");
      }
    } catch (err: any) {
      setTerminateError(err?.message || "An unexpected error occurred during termination.");
    } finally {
      setIsTerminating(false);
      setTerminatingId(null);
    }
  };

  if ((loading && !data) && serversLoading && ownedServers.length === 0) {
    return <div className="p-6 text-paper/50 font-mono text-sm">Loading servers...</div>;
  }

  // Helper to compute dynamic telemetry status based on metric freshness and utilization
  const computeTelemetryStatus = (baseStatus: string, latest?: MetricRow): string => {
    if (baseStatus === "terminated" || baseStatus === "error") return baseStatus;
    if (!latest) return "pending";
    const ageMs = Date.now() - new Date(latest.recorded_at).getTime();
    if (ageMs > 60000) return "stale";
    if (latest.cpu_usage > 90 || latest.ram_usage > 90) return "critical";
    if (latest.cpu_usage > 75 || latest.ram_usage > 75) return "warning";
    return "active";
  };

  // Build merged server list: use backend data as primary source (has metrics/cost),
  // fall back to direct Supabase query for any servers the backend missed.
  const backendServers: (ServerType & { latest_metric?: MetricRow; metrics?: MetricRow[] })[] = data
    ? data.servers.map((srv) => {
        const metrics = data.metrics?.[srv.id] || [];
        const latest_metric = metrics.length > 0 ? metrics[metrics.length - 1] : undefined;
        const dynamicStatus = computeTelemetryStatus(srv.status, latest_metric);
        return {
          ...srv,
          status: dynamicStatus as any,
          metrics,
          latest_metric,
        };
      })
    : [];

  const backendIds = new Set(backendServers.map((s) => s.id));

  // Servers visible only via Supabase direct query (fall back to data context metrics if present)
  const supabaseOnlyServers = ownedServers
    .filter((s) => !backendIds.has(s.id))
    .map((s) => {
      const metrics = data?.metrics?.[s.id] || [];
      const latest_metric = metrics.length > 0 ? metrics[metrics.length - 1] : undefined;
      const dynamicStatus = computeTelemetryStatus(s.status, latest_metric);
      return {
        ...s,
        status: dynamicStatus as any,
        metrics,
        latest_metric,
      };
    });

  const serverRows = [...backendServers, ...supabaseOnlyServers];

  const filteredServers = serverRows.filter((s) => {
    const matchesSearch =
      s.server_name.toLowerCase().includes(search.toLowerCase()) ||
      (s.ip_address?.toLowerCase().includes(search.toLowerCase()) ?? false);
    const matchesStatus =
      statusFilter === "All" || s.status.toLowerCase() === statusFilter.toLowerCase();
    return matchesSearch && matchesStatus;
  });

  // For the detail drawer: check serverRows, backend data, and owned servers
  const selectedServer =
    serverRows.find((s) => s.id === selectedServerId) ??
    data?.servers.find((s) => s.id === selectedServerId) ??
    ownedServers.find((s) => s.id === selectedServerId);

  const selectedServerMetrics: MetricRow[] = (selectedServer && data?.metrics?.[selectedServer.id])
    ? data.metrics[selectedServer.id]
    : [];
  const latestMetric: MetricRow | undefined = selectedServerMetrics.length > 0
    ? selectedServerMetrics[selectedServerMetrics.length - 1]
    : (selectedServer as any)?.latest_metric;

  const metricAgeSeconds = latestMetric
    ? Math.max(0, Math.round((Date.now() - new Date(latestMetric.recorded_at).getTime()) / 1000))
    : null;

  const isLiveTelemetry = metricAgeSeconds !== null && metricAgeSeconds <= 60;
  const isStaleTelemetry = metricAgeSeconds !== null && metricAgeSeconds > 60;

  return (
    <>
      <main className="flex-1 p-6 overflow-y-auto space-y-6 relative">
        {/* Header & Quick Filters */}
        <div className="flex flex-col sm:flex-row gap-4 items-center justify-between">
          <div className="flex items-center gap-3 w-full sm:w-auto">
            <div
              className="flex items-center gap-2 rounded-xl px-4 py-2 w-full sm:w-64"
              style={{
                background: "rgba(244,240,230,0.04)",
                border: "1px solid rgba(244,240,230,0.08)",
              }}
            >
              <Search size={16} className="text-paper/40" />
              <input
                type="text"
                placeholder="Search by name or IP..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="bg-transparent border-none text-[13px] text-paper font-medium focus:outline-none w-full"
              />
            </div>
            <div className="hidden sm:flex items-center gap-2">
              {["All", "Active", "Warning", "Critical", "Idle"].map((status) => (
                <button
                  key={status}
                  onClick={() => setStatusFilter(status)}
                  className="px-3 py-1.5 rounded-lg text-[11px] font-mono font-semibold uppercase tracking-wider transition-all"
                  style={
                    statusFilter === status
                      ? {
                          background: "rgba(255,230,0,0.1)",
                          color: "var(--color-accent-yellow)",
                          border: "1px solid rgba(255,230,0,0.2)",
                        }
                      : {
                          background: "transparent",
                          color: "rgba(244,240,230,0.4)",
                          border: "1px solid transparent",
                        }
                  }
                >
                  {status}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={handleOpenProvision}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-[12px] font-semibold transition-all hover:brightness-110 cursor-pointer"
            style={{
              background: "var(--color-accent-yellow)",
              color: "var(--color-ink)",
              boxShadow: "0 4px 12px -2px rgba(255,230,0,0.25)",
            }}
          >
            <Plus size={16} />
            Provision New Node
          </button>
        </div>

        {/* Server Grid/Table */}
        <div className="glass-panel p-6">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div
                className="flex h-9 w-9 items-center justify-center rounded-xl"
                style={{
                  background: "rgba(6,182,212,0.1)",
                  border: "1px solid rgba(6,182,212,0.15)",
                  boxShadow: "0 0 12px rgba(6,182,212,0.1)",
                }}
              >
                <Server size={16} className="text-accent-blue" />
              </div>
              <div>
                <h3 className="text-base font-bold text-paper font-heading">
                  Fleet Inventory
                </h3>
                <p
                  className="text-[10px] font-mono font-medium mt-0.5"
                  style={{ color: "rgba(244,240,230,0.3)" }}
                >
                  Click a row to view node details & telemetry token
                </p>
              </div>
            </div>
          </div>

          <ServerTable
            servers={filteredServers}
            onAction={handleActionClick}
            onRowClick={(id) => setSelectedServerId(id)}
            terminatingId={terminatingId}
          />
        </div>
      </main>

      {/* Node Detail Drawer */}
      <div
        className={`fixed inset-y-0 right-0 z-[100] w-[450px] transform transition-transform duration-500 ease-[cubic-bezier(0.2,0.8,0.2,1)] ${
          selectedServerId ? "translate-x-0" : "translate-x-full"
        }`}
        style={{
          background: "linear-gradient(180deg, rgba(11,11,13,0.98) 0%, rgba(7,7,10,0.99) 100%)",
          backdropFilter: "blur(40px) saturate(200%)",
          borderLeft: "1px solid rgba(244,240,230,0.08)",
          boxShadow: "-20px 0 40px rgba(0,0,0,0.5)",
        }}
      >
        {selectedServer && (
          <div className="flex flex-col h-full overflow-y-auto">
            <div className="p-6" style={{ borderBottom: "1px solid rgba(244,240,230,0.06)" }}>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <Server size={20} className="text-paper" />
                  <h2 className="text-xl font-bold font-heading text-paper tracking-tight">
                    {selectedServer.server_name}
                  </h2>
                </div>
                <button
                  onClick={() => setSelectedServerId(null)}
                  className="p-2 rounded-lg hover:bg-white/5 transition-colors"
                >
                  <X size={18} className="text-paper/40" />
                </button>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[12px] font-mono bg-white/5 px-2 py-1 rounded text-paper/60 border border-white/5">
                  ID: {selectedServer.id.slice(0, 8)}...
                </span>
                <span
                  className={`px-2 py-1 rounded text-[10px] font-mono font-bold uppercase tracking-wider ${
                    selectedServer.status === "active"
                      ? "bg-accent-green/10 text-accent-green border border-accent-green/20"
                      : selectedServer.status === "warning"
                      ? "bg-accent-yellow/10 text-accent-yellow border border-accent-yellow/20"
                      : selectedServer.status === "critical"
                      ? "bg-accent-red/10 text-accent-red border border-accent-red/20"
                      : "bg-white/5 text-paper/40 border border-white/10"
                  }`}
                >
                  {selectedServer.status}
                </span>
                {selectedServer.cost_tag && (
                  <span className="text-[10px] font-mono bg-indigo-500/10 text-indigo-300 px-2 py-1 rounded border border-indigo-500/20">
                    Tag: {selectedServer.cost_tag}
                  </span>
                )}
              </div>
            </div>

            {/* Ingestion Token & Agent Setup Panel */}
            <div className="p-6 space-y-6">
              {ownedTokens[selectedServer.id] && (
                <div className="glass-panel p-4 rounded-xl border border-indigo-500/20 bg-indigo-500/5 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-300 flex items-center gap-1.5">
                      <Key size={13} /> Ingestion Token
                    </span>
                    <button
                      onClick={() => copyToken(ownedTokens[selectedServer.id])}
                      className="flex items-center gap-1 text-[11px] font-mono text-indigo-400 hover:text-indigo-200"
                    >
                      {copiedToken ? <Check size={12} /> : <Copy size={12} />}
                      {copiedToken ? "Copied" : "Copy Token"}
                    </button>
                  </div>
                  <div className="bg-[#09090b] p-2.5 rounded-lg border border-white/10 font-mono text-xs text-zinc-300 break-all select-all">
                    {ownedTokens[selectedServer.id]}
                  </div>
                  <div className="pt-2 border-t border-white/5">
                    <span className="text-[10px] font-mono text-zinc-400 flex items-center gap-1 mb-1">
                      <Terminal size={11} /> Agent Telemetry Command:
                    </span>
                    <div className="bg-[#09090b] p-2.5 rounded-lg border border-white/10 font-mono text-[11px] text-amber-300 flex items-center justify-between">
                      <code className="truncate max-w-[280px]">
                        python telemetry_agent.py --token {ownedTokens[selectedServer.id].slice(0, 8)}... --url {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"} --interval 5
                      </code>
                      <button
                        onClick={() => copyAgentCommand(ownedTokens[selectedServer.id])}
                        className="text-zinc-400 hover:text-white p-1"
                        title="Copy full telemetry command"
                      >
                        {copiedCommand ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* Real-time Telemetry Health & Live Gauges */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h4 className="eyebrow">Live Telemetry Health</h4>
                  {isLiveTelemetry ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 shadow-[0_0_8px_rgba(16,185,129,0.2)]">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      LIVE FEED
                    </span>
                  ) : isStaleTelemetry ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                      <Radio size={10} />
                      STALE ({metricAgeSeconds}s ago)
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                      <Radio size={10} />
                      AWAITING AGENT
                    </span>
                  )}
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 mb-3">
                  {/* CPU Usage Card */}
                  <div className="glass-panel p-3 rounded-xl border border-white/5 bg-white/[0.02]">
                    <div className="flex items-center justify-between text-paper/40 text-[10px] font-mono mb-1.5">
                      <span className="flex items-center gap-1"><Cpu size={11} className="text-cyan-400" /> CPU</span>
                    </div>
                    <div className="text-lg font-bold font-mono text-paper">
                      {latestMetric ? `${latestMetric.cpu_usage.toFixed(1)}%` : "—"}
                    </div>
                    <div className="w-full bg-white/5 rounded-full h-1 mt-1.5 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          (latestMetric?.cpu_usage ?? 0) > 85
                            ? "bg-rose-500"
                            : (latestMetric?.cpu_usage ?? 0) > 70
                            ? "bg-amber-400"
                            : "bg-cyan-400"
                        }`}
                        style={{ width: `${Math.min(100, latestMetric?.cpu_usage ?? 0)}%` }}
                      />
                    </div>
                  </div>

                  {/* RAM Usage Card */}
                  <div className="glass-panel p-3 rounded-xl border border-white/5 bg-white/[0.02]">
                    <div className="flex items-center justify-between text-paper/40 text-[10px] font-mono mb-1.5">
                      <span className="flex items-center gap-1"><Activity size={11} className="text-emerald-400" /> RAM</span>
                    </div>
                    <div className="text-lg font-bold font-mono text-paper">
                      {latestMetric ? `${latestMetric.ram_usage.toFixed(1)}%` : "—"}
                    </div>
                    <div className="w-full bg-white/5 rounded-full h-1 mt-1.5 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-500 ${
                          (latestMetric?.ram_usage ?? 0) > 85
                            ? "bg-rose-500"
                            : (latestMetric?.ram_usage ?? 0) > 70
                            ? "bg-amber-400"
                            : "bg-emerald-400"
                        }`}
                        style={{ width: `${Math.min(100, latestMetric?.ram_usage ?? 0)}%` }}
                      />
                    </div>
                  </div>

                  {/* Disk Usage Card */}
                  <div className="glass-panel p-3 rounded-xl border border-white/5 bg-white/[0.02]">
                    <div className="flex items-center justify-between text-paper/40 text-[10px] font-mono mb-1.5">
                      <span className="flex items-center gap-1"><HardDrive size={11} className="text-violet-400" /> DISK</span>
                    </div>
                    <div className="text-lg font-bold font-mono text-paper">
                      {latestMetric?.disk_usage !== undefined ? `${latestMetric.disk_usage.toFixed(1)}%` : "—"}
                    </div>
                    <div className="w-full bg-white/5 rounded-full h-1 mt-1.5 overflow-hidden">
                      <div
                        className="h-full bg-violet-400 rounded-full transition-all duration-500"
                        style={{ width: `${Math.min(100, latestMetric?.disk_usage ?? 0)}%` }}
                      />
                    </div>
                  </div>

                  {/* Network Card */}
                  <div className="glass-panel p-3 rounded-xl border border-white/5 bg-white/[0.02]">
                    <div className="flex items-center justify-between text-paper/40 text-[10px] font-mono mb-1.5">
                      <span className="flex items-center gap-1"><Wifi size={11} className="text-amber-400" /> NET</span>
                    </div>
                    <div className="text-lg font-bold font-mono text-paper truncate">
                      {latestMetric?.network_traffic !== undefined ? `${latestMetric.network_traffic.toFixed(1)} MB` : "—"}
                    </div>
                    <div className="text-[9px] font-mono text-paper/30 mt-1.5 truncate">
                      Rate / pkt
                    </div>
                  </div>
                </div>

                {/* Telemetry metadata footer */}
                <div className="glass-panel px-3 py-2 rounded-lg border border-white/5 flex items-center justify-between text-[10px] font-mono text-paper/50">
                  <span className="flex items-center gap-1">
                    <Clock size={11} /> Last Reported: {latestMetric ? new Date(latestMetric.recorded_at).toLocaleTimeString() : "Never"}
                  </span>
                  <span>{selectedServerMetrics.length} Samples Cached</span>
                </div>
              </div>

              {/* Hardware Profile Specs */}
              <div>
                <h4 className="eyebrow mb-4">Hardware Profile</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="glass-panel p-4 flex flex-col justify-center">
                    <span className="text-[10px] font-mono text-paper/40 mb-1">vCPUs</span>
                    <span className="text-lg font-bold text-paper font-heading">
                      {selectedServer.specifications?.vcpus ?? 4} Cores
                    </span>
                  </div>
                  <div className="glass-panel p-4 flex flex-col justify-center">
                    <span className="text-[10px] font-mono text-paper/40 mb-1">Memory</span>
                    <span className="text-lg font-bold text-paper font-heading">
                      {selectedServer.specifications?.ram_gb ?? 16} GB
                    </span>
                  </div>
                </div>
              </div>

              {/* Chart */}
              <div>
                <div className="flex items-center justify-between mb-4">
                  <h4 className="eyebrow">Historical & Live Telemetry</h4>
                  {isLiveTelemetry && (
                    <span className="text-[10px] font-mono text-emerald-400 flex items-center gap-1">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" /> Live
                    </span>
                  )}
                </div>
                <div className="glass-panel p-4 h-[200px]">
                  {selectedServerMetrics && selectedServerMetrics.length > 0 ? (
                    <CpuRamChart data={toChartPoints(selectedServerMetrics)} isLive={isLiveTelemetry} />
                  ) : (
                    <div className="h-full flex items-center justify-center text-[11px] font-mono text-paper/30">
                      No telemetry metrics recorded yet
                    </div>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div>
                <h4 className="eyebrow mb-4">Control Actions</h4>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    className="p-3 rounded-xl text-[12px] font-semibold transition-all border border-white/10 text-paper/80 hover:bg-white/5 cursor-pointer"
                    onClick={() => handleServerAction(selectedServer.id, "optimize")}
                  >
                    Restart Node
                  </button>
                  <button
                    className="p-3 rounded-xl text-[12px] font-semibold transition-all hover:brightness-110 cursor-pointer flex items-center justify-center gap-1.5"
                    style={{
                      background: "rgba(232,70,44,0.1)",
                      color: "#e8462c",
                      border: "1px solid rgba(232,70,44,0.2)",
                    }}
                    onClick={() => {
                      setTerminateModalNode(selectedServer);
                      setTerminateError(null);
                    }}
                  >
                    <PowerOff size={14} /> Terminate Node
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Drawer Overlay */}
      {selectedServerId && (
        <div
          className="fixed inset-0 z-[90]"
          style={{ background: "rgba(7,7,10,0.5)", backdropFilter: "blur(2px)" }}
          onClick={() => setSelectedServerId(null)}
        />
      )}

      {/* Provision New Node Modal */}
      {provisionOpen && (
        <>
          <div
            className="fixed inset-0 z-[110]"
            style={{ background: "rgba(7,7,10,0.6)", backdropFilter: "blur(4px)" }}
            onClick={handleCloseProvision}
          />
          <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
            <div
              className="w-full max-w-md rounded-2xl border p-6 shadow-2xl transition-all"
              style={{
                background: "linear-gradient(180deg, rgba(18,18,18,0.98) 0%, rgba(11,11,13,0.99) 100%)",
                borderColor: "rgba(244,240,230,0.12)",
                boxShadow: "0 24px 64px rgba(0,0,0,0.8)",
              }}
            >
              {provisionStep === "form" ? (
                <>
                  <div className="mb-5 flex items-center justify-between">
                    <div>
                      <h3 className="text-base font-bold font-heading text-paper">Provision New Node</h3>
                      <p className="text-[10px] font-mono text-paper/40 mt-0.5">
                        Ingestion token will be generated automatically upon creation
                      </p>
                    </div>
                    <button
                      onClick={handleCloseProvision}
                      className="p-2 rounded-lg hover:bg-white/5 transition-colors"
                    >
                      <X size={18} className="text-paper/40" />
                    </button>
                  </div>

                  <form onSubmit={handleProvision} className="flex flex-col gap-4">
                    <label className="flex flex-col gap-1.5">
                      <span
                        className="font-mono text-[11px] uppercase tracking-widest"
                        style={{ color: "#8a8780" }}
                      >
                        Node Name <span className="text-amber-400">*</span>
                      </span>
                      <input
                        type="text"
                        required
                        autoFocus
                        value={serverName}
                        onChange={(e) => setServerName(e.target.value)}
                        placeholder="e.g. test-node-01"
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                        style={{
                          background: "#0b0b0d",
                          borderColor: "rgba(244,240,230,0.10)",
                          color: "#f4f0e6",
                        }}
                      />
                    </label>

                    <label className="flex flex-col gap-1.5">
                      <span
                        className="font-mono text-[11px] uppercase tracking-widest"
                        style={{ color: "#8a8780" }}
                      >
                        IP Address <span style={{ color: "#5f5d58" }}>(optional)</span>
                      </span>
                      <input
                        type="text"
                        value={serverIp}
                        onChange={(e) => setServerIp(e.target.value)}
                        placeholder="127.0.0.1"
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                        style={{
                          background: "#0b0b0d",
                          borderColor: "rgba(244,240,230,0.10)",
                          color: "#f4f0e6",
                        }}
                      />
                    </label>

                    <label className="flex flex-col gap-1.5">
                      <span
                        className="font-mono text-[11px] uppercase tracking-widest"
                        style={{ color: "#8a8780" }}
                      >
                        AWS Cost Tag <span style={{ color: "#5f5d58" }}>(optional)</span>
                      </span>
                      <input
                        type="text"
                        value={serverCostTag}
                        onChange={(e) => setServerCostTag(e.target.value)}
                        placeholder="Leave blank to use node name"
                        className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                        style={{
                          background: "#0b0b0d",
                          borderColor: "rgba(244,240,230,0.10)",
                          color: "#f4f0e6",
                        }}
                      />
                      <span className="text-[10px] leading-relaxed" style={{ color: "#5f5d58" }}>
                        Value of the <code className="text-paper/50">server</code> tag on this node&apos;s AWS resources.
                      </span>
                    </label>

                    {provisionError && (
                      <div
                        className="rounded-xl px-3 py-2.5 text-xs flex items-start gap-2 border"
                        style={{
                          background: "rgba(232,70,44,0.1)",
                          borderColor: "rgba(232,70,44,0.25)",
                          color: "#ff8a75",
                        }}
                      >
                        <X size={15} className="shrink-0 mt-0.5 text-red-400" />
                        <span>{provisionError}</span>
                      </div>
                    )}

                    <button
                      type="submit"
                      disabled={provisioning || !serverName.trim()}
                      className="mt-2 flex items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all disabled:opacity-50 cursor-pointer"
                      style={{ background: "#ffe600", color: "#0b0b0d" }}
                    >
                      {provisioning ? (
                        <Loader2 size={16} className="animate-spin text-black" />
                      ) : (
                        <Plus size={16} />
                      )}
                      {provisioning ? "Provisioning..." : "Provision Node"}
                    </button>
                  </form>
                </>
              ) : (
                /* Step 2: Provisioning Success View with Ingestion Token */
                <div className="space-y-5">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                      <CheckCircle2 size={20} />
                    </div>
                    <div>
                      <h3 className="text-base font-bold font-heading text-white">
                        Node Provisioned Successfully
                      </h3>
                      <p className="text-[11px] font-mono text-zinc-400">
                        {createdNode?.server_name} is now registered in fleet inventory
                      </p>
                    </div>
                  </div>

                  {/* Token Box */}
                  <div className="rounded-xl border border-white/10 bg-[#09090b] p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
                        <Key size={13} /> Ingestion Token
                      </span>
                      <button
                        onClick={() => setShowToken(!showToken)}
                        className="flex items-center gap-1 text-[11px] font-mono text-zinc-400 hover:text-white"
                      >
                        {showToken ? <EyeOff size={13} /> : <Eye size={13} />}
                        {showToken ? "Hide" : "Show"}
                      </button>
                    </div>

                    <div className="flex items-center justify-between gap-2 bg-[#121216] px-3 py-2 rounded-lg border border-white/5">
                      <code className="font-mono text-xs text-white select-all">
                        {showToken
                          ? createdNode?.ingestion_token
                          : `••••••••••••••••••••••••••••••••`}
                      </code>
                      <button
                        onClick={() => createdNode && copyToken(createdNode.ingestion_token)}
                        className="flex items-center gap-1 rounded bg-indigo-600/20 px-2.5 py-1 text-[11px] font-semibold text-indigo-300 hover:bg-indigo-600 hover:text-white transition-all shrink-0"
                      >
                        {copiedToken ? <Check size={12} /> : <Copy size={12} />}
                        {copiedToken ? "Copied" : "Copy Token"}
                      </button>
                    </div>
                  </div>

                  {/* Agent Command Box */}
                  <div className="rounded-xl border border-white/10 bg-[#09090b] p-4 space-y-2">
                    <span className="text-[11px] font-mono font-bold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                      <Terminal size={13} /> Telemetry Agent Command
                    </span>
                    <div className="flex items-center justify-between gap-2 bg-[#121216] px-3 py-2 rounded-lg border border-white/5">
                      <code className="font-mono text-[11px] text-amber-300 truncate max-w-[280px]">
                        python telemetry_agent.py --token {createdNode?.ingestion_token} --url {process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"} --interval 5
                      </code>
                      <button
                        onClick={() => createdNode && copyAgentCommand(createdNode.ingestion_token)}
                        className="flex items-center gap-1 rounded bg-white/5 px-2.5 py-1 text-[11px] font-semibold text-zinc-300 hover:bg-white/10 transition-all shrink-0"
                      >
                        {copiedCommand ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                        {copiedCommand ? "Copied" : "Copy Command"}
                      </button>
                    </div>
                  </div>

                  <button
                    onClick={() => {
                      if (createdNode?.id) {
                        setSelectedServerId(createdNode.id);
                      }
                      handleCloseProvision();
                    }}
                    className="w-full flex items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-bold uppercase tracking-wider text-black transition-all cursor-pointer"
                    style={{ background: "#ffe600" }}
                  >
                    Done — View Node in Fleet
                  </button>
                </div>
              )}
            </div>
          </div>
        </>
      )}
      {/* Termination Confirmation Modal */}
      {terminateModalNode && (
        <>
          <div
            className="fixed inset-0 z-[130]"
            style={{ background: "rgba(7,7,10,0.75)", backdropFilter: "blur(6px)" }}
            onClick={() => !isTerminating && setTerminateModalNode(null)}
          />
          <div className="fixed inset-0 z-[140] flex items-center justify-center p-4">
            <div
              className="relative w-full max-w-md rounded-2xl p-6 shadow-2xl border"
              style={{
                background: "linear-gradient(180deg, #141418 0%, #0c0c0f 100%)",
                borderColor: "rgba(232,70,44,0.3)",
                boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.7), 0 0 30px rgba(232,70,44,0.1)",
              }}
            >
              {/* Close button */}
              <button
                disabled={isTerminating}
                onClick={() => setTerminateModalNode(null)}
                className="absolute top-5 right-5 text-paper/40 hover:text-paper transition-colors disabled:opacity-30 cursor-pointer"
              >
                <X size={18} />
              </button>

              <div className="flex items-center gap-3 mb-4">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-red-500/10 border border-red-500/20 text-red-400">
                  <AlertTriangle size={22} />
                </div>
                <div>
                  <h3 className="text-base font-bold font-heading text-white">
                    Terminate Node
                  </h3>
                  <p className="text-[11px] font-mono text-zinc-400">
                    Confirm permanent node deactivation
                  </p>
                </div>
              </div>

              {/* Node Details Box */}
              <div className="rounded-xl border border-white/10 bg-[#09090b] p-4 space-y-2 mb-4">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-zinc-400 uppercase text-[10px] tracking-wider">Node Name</span>
                  <span className="font-semibold text-white font-mono">{terminateModalNode.server_name}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-zinc-400 uppercase text-[10px] tracking-wider">Node ID</span>
                  <span className="font-mono text-zinc-300 text-[11px]" title={terminateModalNode.id}>
                    {terminateModalNode.id.slice(0, 8)}...{terminateModalNode.id.slice(-4)}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-zinc-400 uppercase text-[10px] tracking-wider">IP Address</span>
                  <span className="font-mono text-zinc-300 text-[11px]">
                    {terminateModalNode.ip_address || "Auto-assigned"}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-zinc-400 uppercase text-[10px] tracking-wider">Current Status</span>
                  <span className="font-mono uppercase text-[10px] px-2 py-0.5 rounded bg-white/5 text-zinc-300 border border-white/10">
                    {terminateModalNode.status}
                  </span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-zinc-400 uppercase text-[10px] tracking-wider">Type</span>
                  <span className="font-mono text-[11px] text-zinc-400">
                    {terminateModalNode.source === "aws_discovery" ? "AWS EC2 Instance" : "Telemetry Node"}
                  </span>
                </div>
              </div>

              <div
                className="rounded-xl p-3 text-xs flex items-start gap-2.5 mb-5 border"
                style={{
                  background: "rgba(232,70,44,0.08)",
                  borderColor: "rgba(232,70,44,0.2)",
                  color: "#ff9985",
                }}
              >
                <PowerOff size={16} className="shrink-0 mt-0.5 text-red-400" />
                <span className="leading-relaxed">
                  This action will permanently remove <strong>{terminateModalNode.server_name}</strong> from your fleet inventory, revoke its ingestion token, and cascade delete associated metrics.
                </span>
              </div>

              {terminateError && (
                <div className="rounded-xl px-3 py-2 text-xs mb-4 text-red-400 bg-red-500/10 border border-red-500/20">
                  {terminateError}
                </div>
              )}

              <div className="flex items-center gap-3 justify-end">
                <button
                  type="button"
                  disabled={isTerminating}
                  onClick={() => setTerminateModalNode(null)}
                  className="px-4 py-2.5 rounded-xl text-xs font-semibold text-zinc-400 hover:text-white hover:bg-white/5 transition-all disabled:opacity-40 cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={isTerminating}
                  onClick={handleConfirmTerminate}
                  className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wider text-white transition-all disabled:opacity-50 cursor-pointer hover:brightness-110"
                  style={{
                    background: "linear-gradient(180deg, #e8462c 0%, #c42b13 100%)",
                    boxShadow: "0 4px 14px rgba(232,70,44,0.3)",
                  }}
                >
                  {isTerminating ? (
                    <>
                      <Loader2 size={14} className="animate-spin text-white" />
                      <span>Terminating...</span>
                    </>
                  ) : (
                    <>
                      <PowerOff size={14} />
                      <span>Confirm Termination</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Toast Notification */}
      {toastMessage && (
        <div
          className="fixed bottom-6 right-6 z-[150] flex items-center gap-3 px-4 py-3 rounded-xl border shadow-xl"
          style={{
            background: toastMessage.type === "success" ? "#0f1f17" : "#1f0f0f",
            borderColor: toastMessage.type === "success" ? "rgba(16,185,129,0.3)" : "rgba(239,68,68,0.3)",
            color: toastMessage.type === "success" ? "#34d399" : "#f87171",
          }}
        >
          {toastMessage.type === "success" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
          <span className="text-xs font-medium">{toastMessage.text}</span>
          <button
            onClick={() => setToastMessage(null)}
            className="ml-2 text-zinc-400 hover:text-white cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </>
  );
}
