"use client";

import { useState } from "react";
import { Server, Search, Filter, Plus, TrendingUp, X } from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
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
  const { data, loading, handleServerAction } = useDashboard();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("All");
  const [selectedServerId, setSelectedServerId] = useState<string | null>(null);

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
    </>
  );
}
