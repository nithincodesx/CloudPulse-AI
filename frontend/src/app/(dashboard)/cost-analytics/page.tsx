"use client";

import { useState } from "react";
import {
  DollarSign,
  TrendingDown,
  TrendingUp,
  Cloud,
  AlertTriangle,
  RefreshCw,
  PlugZap,
} from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
import KpiCard from "@/components/KpiCard";
import CostModeBadge from "@/components/CostModeBadge";
import ServerTable from "@/components/ServerTable";
import { fetchCloudStatus, triggerCostSync } from "@/lib/supabase";
import type { DailyCost } from "@/lib/types";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

const fmtMoney = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtDate = (iso: string | null): string => {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime())
    ? iso
    : d.toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
};

const tooltipStyle = {
  backgroundColor: "rgba(11,11,13,0.9)",
  backdropFilter: "blur(12px)",
  border: "1px solid rgba(244,240,230,0.08)",
  borderRadius: "12px",
  color: "#f4f0e6",
  fontFamily: "var(--font-mono)",
  fontSize: "11px",
  boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
} as const;

export default function CostAnalyticsPage() {
  const { data, loading, loadData, handleServerAction } = useDashboard();
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [testMsg, setTestMsg] = useState<string | null>(null);

  if (loading && !data) {
    return <div className="p-6 text-paper/50">Loading analytics...</div>;
  }

  const connected = !!data?.summary?.cloud_connected;
  const cloud = data?.cloud;

  // --- Real daily totals from daily_costs (AWS Cost Explorer) ---------------
  const allCosts: DailyCost[] = Object.values(data?.costs ?? {}).flat();
  const byDate = new Map<string, number>();
  for (const c of allCosts) byDate.set(c.cost_date, (byDate.get(c.cost_date) ?? 0) + c.amount);
  const chartData = Array.from(byDate.entries())
    .map(([date, total]) => ({ date, total: Math.round(total * 100) / 100 }))
    .sort((a, b) => a.date.localeCompare(b.date))
    .slice(-30);

  const now = new Date();
  const monthStart = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-01`;
  const mtdTotal = chartData
    .filter((d) => d.date >= monthStart)
    .reduce((acc, d) => acc + d.total, 0);

  const elapsedDays = now.getDate();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const projectedRunRate = elapsedDays > 0 ? (mtdTotal / elapsedDays) * daysInMonth : 0;

  const latestDay = chartData[chartData.length - 1];
  const hourlyBurn = latestDay ? latestDay.total / 24 : 0;

  // Potential savings: 50% of real MTD spend on idle/warning nodes.
  const perServerMtd = new Map<string, number>();
  for (const c of allCosts) {
    if (c.cost_date < monthStart) continue;
    perServerMtd.set(c.server_id, (perServerMtd.get(c.server_id) ?? 0) + c.amount);
  }
  const potentialSavings = (data?.servers ?? [])
    .filter((s) => s.status === "idle" || s.status === "warning")
    .reduce((acc, s) => acc + (perServerMtd.get(s.id) ?? 0) * 0.5, 0);

  const serverRows = data
    ? data.servers.map((srv) => ({
        ...srv,
        latest_metric: data.metrics[srv.id]?.[data.metrics[srv.id].length - 1],
        monthly_cost: perServerMtd.get(srv.id),
      }))
    : [];

  // --- Actions ---------------------------------------------------------------
  const handleSync = async () => {
    setSyncing(true);
    setSyncMsg(null);
    try {
      const result = await triggerCostSync();
      setSyncMsg(
        `Synced ${result.days_synced} day(s) · ${result.matched} matched` +
          (result.unmatched.length ? ` · unmatched tags: ${result.unmatched.join(", ")}` : "")
      );
      await loadData();
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Sync failed");
    } finally {
      setSyncing(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestMsg(null);
    try {
      const status = await fetchCloudStatus();
      setTestMsg(
        status.connected
          ? `Connection OK — ${status.days_of_data} day(s) of cost data`
          : (status.error ?? "AWS not configured in backend/.env")
      );
    } catch (e) {
      setTestMsg(e instanceof Error ? e.message : "Connection test failed");
    } finally {
      setTesting(false);
    }
  };

  return (
    <main className="flex-1 p-6 overflow-y-auto space-y-6">
      {/* ============================================================== */}
      {/* Cloud Connection panel                                         */}
      {/* ============================================================== */}
      <section
        className="glass-panel p-6"
        style={{ border: `1px solid ${connected ? "rgba(16,185,129,0.15)" : "rgba(255,230,0,0.15)"}` }}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div
              className="flex h-11 w-11 items-center justify-center rounded-xl"
              style={{
                background: connected
                  ? "rgba(16,185,129,0.12)"
                  : "rgba(255,230,0,0.08)",
                border: connected
                  ? "1px solid rgba(16,185,129,0.25)"
                  : "1px solid rgba(255,230,0,0.2)",
                color: connected ? "#10b981" : "#ffe600",
              }}
            >
              {connected ? <Cloud size={20} /> : <AlertTriangle size={20} />}
            </div>
            <div>
              <div className="eyebrow mb-1.5">Cost Data Source</div>
              <h3 className="text-base font-bold text-paper font-heading">
                {connected ? "AWS Cost Explorer connected" : "Simulated cost mode"}
              </h3>
              <div className="mt-2">
                <CostModeBadge connected={connected} />
              </div>
            </div>
          </div>

          {/* Connected: sync action */}
          {connected && (
            <div className="flex flex-col items-end gap-1.5">
              <button
                onClick={handleSync}
                disabled={syncing}
                className="inline-flex items-center gap-2 rounded-xl px-4 py-2 text-[11px] font-mono font-semibold uppercase tracking-wider transition-all disabled:opacity-50"
                style={{
                  background: "rgba(16,185,129,0.12)",
                  color: "#10b981",
                  border: "1px solid rgba(16,185,129,0.25)",
                }}
              >
                <RefreshCw size={13} className={syncing ? "animate-spin" : ""} />
                {syncing ? "Syncing…" : "Sync now"}
              </button>
              {syncMsg && (
                <p className="text-[10px] font-mono max-w-[320px] text-right" style={{ color: "rgba(16,185,129,0.8)" }}>
                  {syncMsg}
                </p>
              )}
            </div>
          )}

          {/* Unconnected: test action */}
          {!connected && (
            <div className="flex flex-col items-end gap-1.5">
              <button
                onClick={handleTest}
                disabled={testing}
                className="inline-flex items-center gap-2 rounded-xl px-4 py-2 text-[11px] font-mono font-semibold uppercase tracking-wider transition-all disabled:opacity-50"
                style={{
                  background: "rgba(255,230,0,0.08)",
                  color: "#ffe600",
                  border: "1px solid rgba(255,230,0,0.2)",
                }}
              >
                <PlugZap size={13} />
                {testing ? "Testing…" : "Test connection"}
              </button>
              {testMsg && (
                <p className="text-[10px] font-mono max-w-[320px] text-right" style={{ color: "rgba(244,240,230,0.45)" }}>
                  {testMsg}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Detail row */}
        {connected && cloud && (
          <div
            className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3 text-[11px] font-mono"
            style={{ color: "rgba(244,240,230,0.5)" }}
          >
            <div className="rounded-xl px-3 py-2" style={{ background: "rgba(244,240,230,0.03)" }}>
              <span className="text-[9px] uppercase tracking-[0.2em] block mb-0.5" style={{ color: "rgba(244,240,230,0.3)" }}>
                Cost tag key
              </span>
              {cloud.cost_tag_key || "server"}
            </div>
            <div className="rounded-xl px-3 py-2" style={{ background: "rgba(244,240,230,0.03)" }}>
              <span className="text-[9px] uppercase tracking-[0.2em] block mb-0.5" style={{ color: "rgba(244,240,230,0.3)" }}>
                Last sync
              </span>
              {fmtDate(cloud.last_sync)} · {cloud.days_of_data} day(s)
            </div>
            <div className="rounded-xl px-3 py-2" style={{ background: "rgba(244,240,230,0.03)" }}>
              <span className="text-[9px] uppercase tracking-[0.2em] block mb-0.5" style={{ color: "rgba(244,240,230,0.3)" }}>
                Freshness
              </span>
              Cost Explorer lags 24–48h
            </div>
          </div>
        )}

        {!connected && (
          <div className="mt-5 rounded-xl px-4 py-3" style={{ background: "rgba(255,230,0,0.04)" }}>
            <p className="text-xs" style={{ color: "rgba(244,240,230,0.7)" }}>
              No cloud account connected — cost figures show <span className="font-mono font-bold">$0</span> rather
              than fabricated estimates. To enable real spend:
            </p>
            <ol className="mt-2 space-y-1 text-[11px] font-mono list-decimal list-inside" style={{ color: "rgba(244,240,230,0.5)" }}>
              <li>Create a read-only IAM role with <span className="font-bold">AWSBillingReadOnlyAccess</span> (or <span className="font-bold">ce:GetCostAndUsage</span>).</li>
              <li>Tag cost-bearing resources with <span className="font-bold">server</span> = node name.</li>
              <li>Set <span className="font-bold">AWS_ACCESS_KEY_ID</span> / <span className="font-bold">AWS_SECRET_ACCESS_KEY</span> in <span className="font-bold">backend/.env</span>.</li>
              <li>Restart the backend, then press <span className="font-bold">Sync now</span>.</li>
            </ol>
          </div>
        )}
      </section>

      {/* ============================================================== */}
      {/* KPI row                                                         */}
      {/* ============================================================== */}
      <section className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="MTD Total Spend"
          value={fmtMoney(mtdTotal)}
          subtitle={connected ? "Month-to-date · real spend" : "Connect a cloud account"}
          icon={<DollarSign size={20} />}
          badge={<CostModeBadge connected={connected} />}
          trend={connected ? "neutral" : "down"}
          trendLabel={connected ? `From ${chartData.length} day(s) of actuals` : "No real spend data"}
          highlight={connected && mtdTotal > 0}
        />
        <KpiCard
          label="Proj. Monthly Run Rate"
          value={fmtMoney(projectedRunRate)}
          subtitle="MTD ÷ elapsed days × days in month"
          icon={<TrendingUp size={20} />}
          badge={<CostModeBadge connected={connected} small />}
          trend={connected ? "neutral" : "down"}
          trendLabel={connected ? "Projected from daily actuals" : "No real spend data"}
        />
        <KpiCard
          label="Hourly Burn"
          value={fmtMoney(hourlyBurn)}
          subtitle="Latest day ÷ 24 · derived"
          icon={<DollarSign size={20} />}
          badge={<CostModeBadge connected={connected} small />}
          trend={connected ? "neutral" : "down"}
          trendLabel={connected ? "Derived, not real-time" : "No real spend data"}
        />
        <KpiCard
          label="Potential Savings"
          value={fmtMoney(potentialSavings)}
          subtitle="Idle/warning nodes × 50%"
          icon={<TrendingDown size={20} />}
          badge={<CostModeBadge connected={connected} small />}
          trend={connected ? "down" : "down"}
          trendLabel={connected ? "Downsize underutilized nodes" : "No real spend data"}
          highlight={connected && potentialSavings > 0}
        />
      </section>

      {/* ============================================================== */}
      {/* Real daily cost chart                                           */}
      {/* ============================================================== */}
      <section className="glass-panel p-6">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <div className="eyebrow mb-3">Daily Total Cost · Last {Math.max(chartData.length, 0)} days</div>
            <h3 className="text-base font-bold text-paper font-heading">
              {connected ? "Real daily spend from AWS Cost Explorer" : "No cost data available"}
            </h3>
          </div>
          <CostModeBadge connected={connected} small />
        </div>

        {connected && chartData.length > 0 ? (
          <div className="h-[300px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 10, right: 0, left: -10, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(244,240,230,0.04)" vertical={false} />
                <XAxis
                  dataKey="date"
                  stroke="rgba(244,240,230,0.2)"
                  tick={{ fill: "rgba(244,240,230,0.4)", fontSize: 10, fontFamily: "var(--font-mono)" }}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={30}
                  tickFormatter={(v: string) => v.slice(5)}
                />
                <YAxis
                  stroke="rgba(244,240,230,0.2)"
                  tick={{ fill: "rgba(244,240,230,0.4)", fontSize: 10, fontFamily: "var(--font-mono)" }}
                  tickLine={false}
                  axisLine={false}
                  tickFormatter={(val: number) => `$${val}`}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  itemStyle={{ color: "#f4f0e6" }}
                  formatter={(value) => [fmtMoney(Number(value)), "Daily cost"]}
                  labelFormatter={(label) => `Date: ${label}`}
                />
                <Area type="monotone" dataKey="total" stroke="#10b981" strokeWidth={2} fillOpacity={1} fill="url(#colorTotal)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="flex h-[300px] w-full flex-col items-center justify-center text-center">
            <div
              className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl"
              style={{
                background: "linear-gradient(180deg, #16161a 0%, #0b0b0d 100%)",
                boxShadow:
                  "inset 0 3px 6px rgba(0,0,0,0.65), inset 0 -2px 4px rgba(255,255,255,0.06), 0 2px 4px rgba(255,255,255,0.08)",
              }}
            >
              <Cloud size={24} style={{ color: "rgba(244,240,230,0.2)" }} />
            </div>
            <p className="text-sm font-medium" style={{ color: "rgba(244,240,230,0.4)" }}>
              {connected ? "No cost data synced yet" : "Connect an AWS account to see real spend"}
            </p>
            <p className="mt-1 max-w-sm text-[11px] font-mono" style={{ color: "rgba(244,240,230,0.3)" }}>
              {connected
                ? "Hit “Sync now” above — costs appear 24–48h after they’re incurred."
                : "Cost Explorer reports daily totals with a 24–48h lag; today’s spend shows up tomorrow."}
            </p>
          </div>
        )}
      </section>

      {/* ============================================================== */}
      {/* Optimization matrix                                              */}
      {/* ============================================================== */}
      <section className="glass-panel p-6">
        <div className="mb-6">
          <h3 className="text-base font-bold text-paper font-heading">Cost Breakdown & Optimization Matrix</h3>
          <p className="text-[10px] font-mono font-medium mt-0.5" style={{ color: "rgba(244,240,230,0.3)" }}>
            Itemized breakdown of instances ranked by cost impact
          </p>
        </div>
        <ServerTable
          servers={serverRows.sort((a, b) => (b.monthly_cost ?? 0) - (a.monthly_cost ?? 0))}
          onAction={handleServerAction}
        />
      </section>
    </main>
  );
}
