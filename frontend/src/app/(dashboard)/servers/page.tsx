"use client";

import { useState, useEffect } from "react";
import { Server, Search, Plus, X, Copy, Check, Loader2 } from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
import { supabase } from "@/lib/supabase";
import { useAuth } from "@/lib/AuthContext";
import ServerTable from "@/components/ServerTable";
import CpuRamChart from "@/components/CpuRamChart";
import type { MetricRow } from "@/lib/types";

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
  const { data, loading, loadData, handleServerAction } = useDashboard();
  const { user } = useAuth();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("All");
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);

  // Provisioning modal state
  const [provisionOpen, setProvisionOpen] = useState(false);
  const [serverName, setServerName] = useState("");
  const [serverIp, setServerIp] = useState("");
  const [provisioning, setProvisioning] = useState(false);
  const [provisionError, setProvisionError] = useState<string | null>(null);

  // This user's own servers (RLS-scoped) → ingestion token lookup by server id.
  const [ownedTokens, setOwnedTokens] = useState<Record<string, string>>({});
  const [copiedToken, setCopiedToken] = useState(false);

  const loadOwnedTokens = async () => {
    if (!user) return;
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
  };

  useEffect(() => {
    loadOwnedTokens();
  }, [user]);

  const handleProvision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!user || !serverName.trim()) return;
    setProvisioning(true);
    setProvisionError(null);
    try {
      const { data, error } = await supabase
        .from("servers")
        .insert({
          server_name: serverName.trim(),
          ip_address: serverIp.trim() || null,
          owner_id: user.id,
        })
        .select("id, server_name, ip_address, ingestion_token")
        .single();
      if (error) throw error;
      setServerName("");
      setServerIp("");
      setProvisionOpen(false);
      await loadOwnedTokens();
      loadData();
    } catch (err) {
      setProvisionError(err instanceof Error ? err.message : "Failed to provision server");
    } finally {
      setProvisioning(false);
    }
  };

  const copyToken = async (token: string) => {
    try {
      await navigator.clipboard.writeText(token);
      setCopiedToken(true);
      setTimeout(() => setCopiedToken(false), 1500);
    } catch {
      // clipboard unavailable — ignore
    }
  };

  if (loading && !data) {
    return <div className="p-6 text-paper/50">Loading servers...</div>;
  }

  const serverRows = data
    ? data.servers.map((srv) => {
        const metrics = data.metrics[srv.id];
        return {
          ...srv,
          latest_metric: metrics?.[metrics.length - 1],
        };
      })
    : [];

  const filteredServers = serverRows.filter((s) => {
    const matchesSearch = s.server_name.toLowerCase().includes(search.toLowerCase()) || 
                          (s.ip_address?.toLowerCase().includes(search.toLowerCase()) ?? false);
    const matchesStatus = statusFilter === "All" || s.status.toLowerCase() === statusFilter.toLowerCase();
    return matchesSearch && matchesStatus;
  });

  const selectedServer = data?.servers.find((s) => s.id === selectedServerId);
  const selectedServerMetrics = selectedServer ? data?.metrics[selectedServer.id] : undefined;

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
            onClick={() => {
              setProvisionError(null);
              setProvisionOpen(true);
            }}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-[12px] font-semibold transition-all hover:brightness-110"
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
                  Click a row to view node details
                </p>
              </div>
            </div>
          </div>
          
          <ServerTable servers={filteredServers} onAction={handleServerAction} onRowClick={(id) => setSelectedServerId(id)} />
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
          <div className="flex flex-col h-full">
            <div className="p-6" style={{ borderBottom: "1px solid rgba(244,240,230,0.06)" }}>
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <Server size={20} className="text-paper" />
                  <h2 className="text-xl font-bold font-heading text-paper tracking-tight">{selectedServer.server_name}</h2>
                </div>
                <button
                  onClick={() => setSelectedServerId(null)}
                  className="p-2 rounded-lg hover:bg-white/5 transition-colors"
                >
                  <X size={18} className="text-paper/40" />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[12px] font-mono bg-white/5 px-2 py-1 rounded text-paper/60 border border-white/5">
                  ID: {selectedServer.id}
                </span>
                <span className={`px-2 py-1 rounded text-[10px] font-mono font-bold uppercase tracking-wider ${
                  selectedServer.status === "active" ? "bg-accent-green/10 text-accent-green border border-accent-green/20" :
                  selectedServer.status === "warning" ? "bg-accent-yellow/10 text-accent-yellow border border-accent-yellow/20" :
                  selectedServer.status === "critical" ? "bg-accent-red/10 text-accent-red border border-accent-red/20" :
                  "bg-white/5 text-paper/40 border border-white/10"
                }`}>
                  {selectedServer.status}
                </span>
              </div>

              {ownedTokens[selectedServer.id] && (
                <div className="mt-4 rounded-xl border border-white/10 bg-black/30 p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-mono uppercase tracking-widest text-paper/40">
                      Ingestion Token
                    </span>
                    <button
                      onClick={() => copyToken(ownedTokens[selectedServer.id])}
                      className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2 py-1 text-[10px] font-mono text-paper/70 hover:bg-white/5 transition-colors cursor-pointer"
                      title="Copy token"
                    >
                      {copiedToken ? <Check size={11} className="text-accent-green" /> : <Copy size={11} />}
                      {copiedToken ? "Copied" : "Copy"}
                    </button>
                  </div>
                  <code
                    className="block break-all text-[11px] font-mono leading-relaxed select-all"
                    style={{ color: "#ffe600" }}
                  >
                    {ownedTokens[selectedServer.id]}
                  </code>
                  <p className="mt-2 text-[10px] leading-relaxed text-paper/35">
                    Pass to the telemetry agent with{" "}
                    <code className="text-paper/60">--token</code> to stream metrics for this node.
                  </p>
                </div>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-8">
              {/* Specs */}
              <div>
                <h4 className="eyebrow mb-4">Hardware Specifications</h4>
                <div className="grid grid-cols-2 gap-3">
                  <div className="glass-panel p-4 flex flex-col justify-center">
                    <span className="text-[10px] font-mono text-paper/40 mb-1">vCPUs</span>
                    <span className="text-lg font-bold text-paper font-heading">{selectedServer.specifications?.vcpus ?? 4} Cores</span>
                  </div>
                  <div className="glass-panel p-4 flex flex-col justify-center">
                    <span className="text-[10px] font-mono text-paper/40 mb-1">Memory</span>
                    <span className="text-lg font-bold text-paper font-heading">{selectedServer.specifications?.ram_gb ?? 16} GB</span>
                  </div>
                </div>
              </div>

              {/* Chart */}
              <div>
                <h4 className="eyebrow mb-4">Historical Spikes</h4>
                <div className="glass-panel p-4 h-[200px]">
                  {selectedServerMetrics ? (
                    <CpuRamChart data={toChartPoints(selectedServerMetrics)} isLive={false} />
                  ) : (
                    <div className="h-full flex items-center justify-center text-[11px] font-mono text-paper/30">No metric history available</div>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div>
                <h4 className="eyebrow mb-4">Control Actions</h4>
                <div className="grid grid-cols-2 gap-3">
                  <button
                    className="p-3 rounded-xl text-[12px] font-semibold transition-all border border-white/10 text-paper/80 hover:bg-white/5"
                    onClick={() => handleServerAction(selectedServer.id, "optimize")}
                  >
                    Restart Node
                  </button>
                  <button
                    className="p-3 rounded-xl text-[12px] font-semibold transition-all border border-white/10 text-paper/80 hover:bg-white/5"
                  >
                    Scale Up Specs
                  </button>
                  <button
                    className="p-3 rounded-xl text-[12px] font-semibold transition-all border border-white/10 text-paper/80 hover:bg-white/5"
                  >
                    Isolate Instance
                  </button>
                  <button
                    className="p-3 rounded-xl text-[12px] font-semibold transition-all hover:brightness-110"
                    style={{
                      background: "rgba(232,70,44,0.1)",
                      color: "#e8462c",
                      border: "1px solid rgba(232,70,44,0.2)",
                    }}
                    onClick={() => {
                      handleServerAction(selectedServer.id, "terminate");
                      setSelectedServerId(null);
                    }}
                  >
                    Terminate Node
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
            onClick={() => setProvisionOpen(false)}
          />
          <div className="fixed inset-0 z-[120] flex items-center justify-center p-4">
            <div
              className="w-full max-w-md rounded-2xl border p-6"
              style={{
                background: "linear-gradient(180deg, rgba(18,18,18,0.98) 0%, rgba(11,11,13,0.99) 100%)",
                borderColor: "rgba(244,240,230,0.08)",
                boxShadow: "0 24px 64px rgba(0,0,0,0.6)",
              }}
            >
              <div className="mb-5 flex items-center justify-between">
                <div>
                  <h3 className="text-base font-bold font-heading text-paper">Provision New Node</h3>
                  <p className="text-[10px] font-mono text-paper/40 mt-0.5">
                    Registered to your account · ingestion token generated automatically
                  </p>
                </div>
                <button
                  onClick={() => setProvisionOpen(false)}
                  className="p-2 rounded-lg hover:bg-white/5 transition-colors"
                >
                  <X size={18} className="text-paper/40" />
                </button>
              </div>

              <form onSubmit={handleProvision} className="flex flex-col gap-4">
                <label className="flex flex-col gap-1.5">
                  <span className="font-mono text-[11px] uppercase tracking-widest" style={{ color: "#8a8780" }}>
                    Node Name
                  </span>
                  <input
                    type="text"
                    required
                    autoFocus
                    value={serverName}
                    onChange={(e) => setServerName(e.target.value)}
                    placeholder="e.g. prod-db-01"
                    className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                    style={{
                      background: "#0b0b0d",
                      borderColor: "rgba(244,240,230,0.10)",
                      color: "#f4f0e6",
                    }}
                  />
                </label>

                <label className="flex flex-col gap-1.5">
                  <span className="font-mono text-[11px] uppercase tracking-widest" style={{ color: "#8a8780" }}>
                    IP Address <span style={{ color: "#5f5d58" }}>(optional)</span>
                  </span>
                  <input
                    type="text"
                    value={serverIp}
                    onChange={(e) => setServerIp(e.target.value)}
                    placeholder="10.0.0.12"
                    className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                    style={{
                      background: "#0b0b0d",
                      borderColor: "rgba(244,240,230,0.10)",
                      color: "#f4f0e6",
                    }}
                  />
                </label>

                {provisionError && (
                  <p className="rounded-md px-3 py-2 text-xs" style={{ background: "rgba(232,70,44,0.12)", color: "#ff8a75" }}>
                    {provisionError}
                  </p>
                )}

                <button
                  type="submit"
                  disabled={provisioning || !serverName.trim()}
                  className="mt-1 flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-opacity disabled:opacity-50"
                  style={{ background: "#ffe600", color: "#0b0b0d" }}
                >
                  {provisioning ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                  {provisioning ? "Provisioning..." : "Provision Node"}
                </button>
              </form>
            </div>
          </div>
        </>
      )}
    </>
  );
}
