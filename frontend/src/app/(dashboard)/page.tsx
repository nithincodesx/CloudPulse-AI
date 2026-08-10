"use client";

import { useState } from "react";
import Link from "next/link";
import { Server, Cpu, DollarSign, Bell, Cloud, AlertTriangle, TrendingUp } from "lucide-react";
import KpiCard from "@/components/KpiCard";
import CpuRamChart from "@/components/CpuRamChart";
import AlertFeed from "@/components/AlertFeed";
import ServerTable from "@/components/ServerTable";
import CostModeBadge from "@/components/CostModeBadge";
import { useDashboard } from "@/lib/DashboardContext";
import type { MetricRow } from "@/lib/types";

/** Transform server metrics into chart-friendly shape. */
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

export default function Dashboard() {
  const { data, loading, isLive, alertFeedOpen, handleDismissAlert, handleServerAction } = useDashboard();
  const [selectedServer, setSelectedServer] = useState<string | null>(null);

  // --- Loading skeleton ------------------------------------------------
  if (loading && !data) {
    return (
      <div className="flex min-h-[calc(100vh-80px)] items-center justify-center">
        <div className="flex flex-col items-center gap-5">
          <div
            className="h-16 w-16 rounded-2xl flex items-center justify-center shimmer"
            style={{
              background: "linear-gradient(180deg, #16161a 0%, #0b0b0d 100%)",
              boxShadow:
                "inset 0 3px 6px rgba(0,0,0,0.65), inset 0 -2px 4px rgba(255,255,255,0.06), 0 2px 4px rgba(255,255,255,0.08)",
            }}
          >
            <Cloud size={28} className="text-accent-yellow" />
          </div>
          <div className="flex items-center gap-2">
            <div className="live-dot h-2 w-2 rounded-full bg-accent-yellow" />
            <p
              className="text-[11px] font-mono font-medium tracking-[0.3em] uppercase"
              style={{ color: "rgba(244,240,230,0.4)" }}
            >
              Initializing CloudPulse
            </p>
          </div>
        </div>
      </div>
    );
  }

  const s = data?.summary;

  // --- Derived values --------------------------------------------------
  const chartData = (() => {
    if (!data) return [];
    if (selectedServer && data.metrics[selectedServer]) {
      return toChartPoints(data.metrics[selectedServer]);
    }
    const allPoints = Object.values(data.metrics).flat();
    const byTime = new Map<string, { cpu: number; ram: number; net: number; count: number }>();
    for (const m of allPoints) {
      const key = new Date(m.recorded_at).toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
      });
      const existing = byTime.get(key) ?? { cpu: 0, ram: 0, net: 0, count: 0 };
      existing.cpu += m.cpu_usage;
      existing.ram += m.ram_usage;
      existing.net += m.network_traffic;
      existing.count += 1;
      byTime.set(key, existing);
    }
    return Array.from(byTime.entries())
      .map(([time, v]) => ({
        time,
        cpu: Math.round((v.cpu / v.count) * 10) / 10,
        ram: Math.round((v.ram / v.count) * 10) / 10,
        network: Math.round((v.net / v.count) * 10) / 10,
      }))
      .slice(-15);
  })();

  const serverRows = data
    ? data.servers.map((srv) => {
        const metrics = data.metrics[srv.id];
        return {
          ...srv,
          latest_metric: metrics?.[metrics.length - 1],
        };
      })
    : [];

  return (
    <>
      <main className="flex-1 space-y-6 p-6 overflow-y-auto">
        {/* ============================================================== */}
        {/* Simulated cost mode banner (only when no cloud account)         */}
        {/* ============================================================== */}
        {!s?.cloud_connected && (
          <div
            className="flex items-center gap-3 rounded-2xl px-4 py-3"
            style={{
              background: "rgba(255,230,0,0.06)",
              border: "1px solid rgba(255,230,0,0.18)",
            }}
          >
            <AlertTriangle size={16} style={{ color: "#ffe600", flexShrink: 0 }} />
            <p className="text-[12px]" style={{ color: "rgba(244,240,230,0.8)" }}>
              <span className="font-bold" style={{ color: "#ffe600" }}>Simulated cost mode</span>
              {" — connect an AWS account to see real spend. "}
              <Link
                href="/cost-analytics"
                className="font-semibold underline underline-offset-2"
                style={{ color: "#ffe600" }}
              >
                Connect now
              </Link>
            </p>
          </div>
        )}

        {/* ============================================================== */}
        {/* KPI Row                                                        */}
        {/* ============================================================== */}
        <section className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Active Nodes"
            value={s?.active_nodes ?? 0}
            subtitle={`${s?.total_nodes ?? 0} total registered`}
            icon={<Server size={20} />}
            trend={s && s.active_nodes > s.total_nodes * 0.7 ? "up" : "down"}
            trendLabel={s ? `${Math.round((s.active_nodes / Math.max(s.total_nodes, 1)) * 100)}% utilization` : ""}
            highlight
          />
          <KpiCard
            label="Avg CPU Load"
            value={`${s?.avg_cpu_load_pct ?? 0}%`}
            subtitle="Cluster-wide average"
            icon={<Cpu size={20} />}
            trend={s && s.avg_cpu_load_pct > 70 ? "up" : "neutral"}
            trendLabel={
              s && s.warning_nodes + s.critical_nodes > 0
                ? `${s.warning_nodes + s.critical_nodes} nodes at risk`
                : "Healthy"
            }
          />
          <KpiCard
            label="Monthly Spend"
            value={s?.cloud_connected ? `$${(s.monthly_cost_estimate ?? 0).toLocaleString()}` : "$0"}
            subtitle={s?.cloud_connected ? "Month-to-date · AWS Cost Explorer" : "Connect a cloud account"}
            icon={<DollarSign size={20} />}
            badge={<CostModeBadge connected={!!s?.cloud_connected} />}
            trend={s && s.cloud_connected && (s.hourly_cost_estimate ?? 0) > 0 ? "up" : "down"}
            trendLabel={
              s?.cloud_connected
                ? `$${(s.hourly_cost_estimate ?? 0).toFixed(2)} / hr (derived from daily)`
                : "No real spend data"
            }
          />
          <KpiCard
            label="Active Alerts"
            value={s?.active_alerts_count ?? 0}
            subtitle="Requires attention"
            icon={<Bell size={20} />}
            highlight={s ? s.active_alerts_count > 0 : false}
            trend={s && s.active_alerts_count > 0 ? "up" : "down"}
            trendLabel={
              s && s.active_alerts_count > 0
                ? `${s.active_alerts_count} unresolved`
                : "All clear"
            }
          />
        </section>

        {/* ============================================================== */}
        {/* Marquee ticker                                                  */}
        {/* ============================================================== */}
        <div
          className="overflow-hidden whitespace-nowrap py-3 rounded-2xl"
          style={{
            background: "var(--color-accent-yellow)",
            color: "var(--color-ink)",
            borderTop: "1px solid var(--color-ink)",
            borderBottom: "1px solid var(--color-ink)",
          }}
        >
          <div className="marquee-track font-heading font-extrabold text-xl">
            {Array.from({ length: 6 }).map((_, i) => (
              <span key={i}>
                <span className="mx-3">Monitoring</span>
                <span className="inline-block w-2 h-2 rounded-full bg-ink mx-3 align-middle" style={{ transform: "translateY(-1px)" }} />
                <span className="mx-3">Optimizing</span>
                <span className="inline-block w-2 h-2 rounded-full bg-ink mx-3 align-middle" style={{ transform: "translateY(-1px)" }} />
                <span className="mx-3">Scaling</span>
                <span className="inline-block w-2 h-2 rounded-full bg-ink mx-3 align-middle" style={{ transform: "translateY(-1px)" }} />
              </span>
            ))}
          </div>
        </div>

        {/* ============================================================== */}
        {/* Chart + Alert Feed                                              */}
        {/* ============================================================== */}
        <section className="grid grid-cols-1 gap-6 xl:grid-cols-3">
          {/* Chart panel */}
          <div className="xl:col-span-2">
            <div className="glass-panel p-6 h-full flex flex-col">
              <div className="mb-6 flex items-center justify-between">
                <div>
                  <div className="eyebrow mb-3">Resource Utilization</div>
                  <h3 className="text-base font-bold text-paper font-heading">
                    {selectedServer
                      ? `Server: ${
                          data?.servers.find((srv) => srv.id === selectedServer)?.server_name ?? selectedServer
                        }`
                      : "Cluster-wide average CPU, RAM & Network"}
                  </h3>
                </div>

                {/* Server picker */}
                <select
                  value={selectedServer ?? ""}
                  onChange={(e) => setSelectedServer(e.target.value || null)}
                  className="rounded-xl px-4 py-2 text-[11px] font-mono font-medium transition-all focus:outline-none"
                  style={{
                    background: "rgba(244,240,230,0.04)",
                    color: "rgba(244,240,230,0.5)",
                    border: "1px solid rgba(244,240,230,0.08)",
                  }}
                >
                  <option value="">All servers (avg)</option>
                  {data?.servers.map((srv) => (
                    <option key={srv.id} value={srv.id}>
                      {srv.server_name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex-1 min-h-[300px]">
                <CpuRamChart data={chartData} isLive={isLive} />
              </div>
            </div>
          </div>

          {/* Alert feed panel */}
          <div
            className={`transition-all duration-500 ease-in-out ${
              alertFeedOpen ? "opacity-100 scale-100" : "hidden opacity-0 scale-95"
            }`}
          >
            <div className="glass-panel p-6 h-full flex flex-col">
              <div className="mb-5 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className="flex h-9 w-9 items-center justify-center rounded-xl"
                    style={{
                      background: "rgba(232,70,44,0.1)",
                      border: "1px solid rgba(232,70,44,0.15)",
                      boxShadow: "0 0 12px rgba(232,70,44,0.1)",
                    }}
                  >
                    <AlertTriangle size={16} className="text-accent-red" />
                  </div>
                  <div>
                    <h3 className="text-base font-bold text-paper font-heading">
                      Live Alerts
                    </h3>
                    <p
                      className="text-[10px] font-mono font-medium mt-0.5"
                      style={{ color: "rgba(244,240,230,0.3)" }}
                    >
                      {data?.active_alerts.length ?? 0} active
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex-1">
                <AlertFeed alerts={data?.active_alerts ?? []} onDismiss={handleDismissAlert} />
              </div>
            </div>
          </div>
        </section>

        {/* ============================================================== */}
        {/* Server Table                                                   */}
        {/* ============================================================== */}
        <section>
          <div className="glass-panel p-6">
            <div className="mb-6 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div
                  className="flex h-9 w-9 items-center justify-center rounded-xl"
                  style={{
                    background: "rgba(255,230,0,0.08)",
                    border: "1px solid rgba(255,230,0,0.12)",
                    boxShadow: "0 0 12px rgba(255,230,0,0.08)",
                  }}
                >
                  <TrendingUp size={16} className="text-accent-yellow" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-paper font-heading">
                    Resource Optimization & Cost
                  </h3>
                  <p
                    className="text-[10px] font-mono font-medium mt-0.5"
                    style={{ color: "rgba(244,240,230,0.3)" }}
                  >
                    Itemized node breakdown with savings projections
                  </p>
                </div>
              </div>
            </div>
            <ServerTable servers={serverRows} onAction={handleServerAction} />
          </div>
        </section>

        {/* ============================================================== */}
        {/* Footer                                                         */}
        {/* ============================================================== */}
        <footer
          className="flex items-center justify-between pt-6 pb-4 text-[10px] font-mono font-medium uppercase tracking-[0.3em]"
          style={{ color: "rgba(244,240,230,0.15)" }}
        >
          <span>CloudPulse AI v2.4.0</span>
          <span>Enterprise Infrastructure Monitor</span>
        </footer>
      </main>
    </>
  );
}
