"use client";

import { useState, useEffect } from "react";
import {
  DollarSign,
  TrendingDown,
  TrendingUp,
  Cloud,
  AlertTriangle,
  RefreshCw,
  Plus,
  Sparkles,
  Loader2,
  Trash2,
  ShieldCheck,
  Activity,
  CheckCircle2,
  XCircle,
  AlertCircle,
  X,
} from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
import KpiCard from "@/components/KpiCard";
import CostModeBadge from "@/components/CostModeBadge";
import ServerTable from "@/components/ServerTable";
import AWSConnectionWizard from "@/components/AWSConnectionWizard";
import {
  fetchCloudStatus,
  fetchLatestInsight,
  generateInsight,
  triggerCostSync,
  fetchAWSConnections,
  verifyAWSConnection,
  syncAWSConnection,
  deleteAWSConnection,
  fetchAWSConnectionHealth,
} from "@/lib/supabase";
import type { DailyCost, WeeklyInsight, AWSConnection, AWSHealthDiagnosticResult } from "@/lib/types";
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

  // AWS Connections & Wizard
  const [connections, setConnections] = useState<AWSConnection[]>([]);
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [isVerifyingConnId, setIsVerifyingConnId] = useState<string | null>(null);
  const [diagnosingConnId, setDiagnosingConnId] = useState<string | null>(null);
  const [diagnosticResult, setDiagnosticResult] = useState<AWSHealthDiagnosticResult | null>(null);
  const [isDiagModalOpen, setIsDiagModalOpen] = useState(false);

  // Weekly AI summary panel
  const [insight, setInsight] = useState<WeeklyInsight | null>(null);
  const [insightLoading, setInsightLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [insightError, setInsightError] = useState<string | null>(null);

  const loadConnections = async () => {
    try {
      const conns = await fetchAWSConnections();
      setConnections(conns);
    } catch (err) {
      console.error("Failed to load AWS connections", err);
    }
  };

  useEffect(() => {
    loadConnections();
    fetchLatestInsight()
      .then((i) => {
        setInsight(i);
        setInsightLoading(false);
      })
      .catch(() => setInsightLoading(false));
  }, []);

  const handleGenerate = async () => {
    setGenerating(true);
    setInsightError(null);
    try {
      const result = await generateInsight();
      if (result.generated && result.insight) {
        setInsight(result.insight);
      } else {
        setInsightError(result.error ?? "Summary generation failed");
      }
    } catch (e) {
      setInsightError(e instanceof Error ? e.message : "Summary generation failed");
    } finally {
      setGenerating(false);
    }
  };

  const handleVerifyConnection = async (connId: string) => {
    setIsVerifyingConnId(connId);
    try {
      const res = await verifyAWSConnection(connId);
      if (res?.success) {
        setSyncMsg("Connection verified successfully with AWS STS.");
        await loadConnections();
        await loadData();
      } else {
        setSyncMsg(`Verification failed: ${res?.error_message || "Check IAM trust policy"}`);
      }
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Verification failed");
    } finally {
      setIsVerifyingConnId(null);
    }
  };

  const handleRunDiagnostics = async (connId: string) => {
    setDiagnosingConnId(connId);
    try {
      const res = await fetchAWSConnectionHealth(connId);
      if (res) {
        setDiagnosticResult(res);
        setIsDiagModalOpen(true);
        await loadConnections();
      } else {
        setSyncMsg("Could not retrieve diagnostics for connection.");
      }
    } catch (e) {
      setSyncMsg(e instanceof Error ? e.message : "Health check failed");
    } finally {
      setDiagnosingConnId(null);
    }
  };

  const handleDisconnect = async (connId: string) => {
    if (!confirm("Are you sure you want to disconnect this AWS account?")) return;
    try {
      await deleteAWSConnection(connId);
      await loadConnections();
      await loadData();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to disconnect AWS account");
    }
  };

  if (loading && !data) {
    return <div className="p-6 text-paper/50">Loading analytics...</div>;
  }

  const primaryConnection = connections.find((c) => c.status === "connected") || connections[0];
  const connected = !!data?.summary?.cloud_connected || connections.some((c) => c.status === "connected");
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
      if (primaryConnection?.id) {
        const result = await syncAWSConnection(primaryConnection.id);
        if (result?.cost_sync) {
          setSyncMsg(
            `Synced ${result.cost_sync.days_synced} day(s) · Discovered ${result.discovery?.discovered_count ?? 0} EC2 instance(s)`
          );
        } else {
          setSyncMsg("Sync completed successfully.");
        }
      } else {
        const result = await triggerCostSync();
        setSyncMsg(
          `Synced ${result.days_synced} day(s) · ${result.matched} matched` +
            (result.unmatched.length ? ` · unmatched tags: ${result.unmatched.join(", ")}` : "")
        );
      }
      await loadConnections();
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
          : (status.error ?? "No cloud connection found")
      );
    } catch (e) {
      setTestMsg(e instanceof Error ? e.message : "Connection test failed");
    } finally {
      setTesting(false);
    }
  };

  return (
    <main className="flex-1 p-6 overflow-y-auto space-y-6">
      <AWSConnectionWizard
        isOpen={isWizardOpen}
        onClose={() => setIsWizardOpen(false)}
        onConnectionSaved={() => {
          loadConnections();
          loadData();
        }}
      />

      {/* ============================================================== */}
      {/* Cloud Connection panel (SaaS Cross-Account IAM System)         */}
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
              <div className="eyebrow mb-1.5">Multi-Tenant AWS Integration</div>
              <h3 className="text-base font-bold text-paper font-heading">
                {connected ? (primaryConnection?.display_name || "AWS Cross-Account Connected") : "Simulated Cost Mode"}
              </h3>
              <div className="mt-2 flex items-center gap-2">
                <CostModeBadge connected={connected} />
                {primaryConnection && (
                  <span className="text-[11px] font-mono text-paper/50">
                    Acct: {primaryConnection.aws_account_id || "Cross-Account"} · {primaryConnection.region}
                  </span>
                )}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setIsWizardOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2 text-[11px] font-mono font-semibold uppercase tracking-wider transition-all"
              style={{
                background: "rgba(99,102,241,0.12)",
                color: "#818cf8",
                border: "1px solid rgba(99,102,241,0.25)",
              }}
            >
              <Plus size={13} />
              Connect AWS Account
            </button>

            {connected && (
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
            )}
          </div>
        </div>

        {syncMsg && (
          <p className="mt-3 text-[11px] font-mono" style={{ color: "rgba(16,185,129,0.9)" }}>
            {syncMsg}
          </p>
        )}

        {/* Connected accounts detail list */}
        {connections.length > 0 ? (
          <div className="mt-5 space-y-3">
            <div className="text-[11px] font-mono font-semibold text-paper/40 uppercase tracking-wider">
              Connected AWS Accounts ({connections.length})
            </div>
            <div className="grid grid-cols-1 gap-3">
              {connections.map((conn) => {
                const healthStatus = conn.health_status || "UNVERIFIED";
                return (
                  <div
                    key={conn.id}
                    className="flex flex-wrap items-center justify-between gap-4 rounded-xl p-3.5"
                    style={{
                      background: "rgba(244,240,230,0.02)",
                      border: "1px solid rgba(244,240,230,0.06)",
                    }}
                  >
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-paper text-xs">{conn.display_name}</span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-bold uppercase ${
                            conn.status === "connected"
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                              : "bg-red-500/10 text-red-400 border border-red-500/20"
                          }`}
                        >
                          {conn.status}
                        </span>
                        <span
                          className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-bold uppercase flex items-center gap-1 ${
                            healthStatus === "HEALTHY"
                              ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                              : healthStatus === "DEGRADED"
                              ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                              : healthStatus === "ERROR"
                              ? "bg-red-500/10 text-red-400 border border-red-500/20"
                              : "bg-gray-500/10 text-paper/50 border border-white/10"
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              healthStatus === "HEALTHY"
                                ? "bg-emerald-400"
                                : healthStatus === "DEGRADED"
                                ? "bg-amber-400"
                                : healthStatus === "ERROR"
                                ? "bg-red-400"
                                : "bg-paper/40"
                            }`}
                          />
                          {healthStatus}
                        </span>
                      </div>
                      <div className="font-mono text-[10px] text-paper/50 truncate max-w-lg">
                        {conn.role_arn || "Role ARN not configured"} · Region: {conn.region}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleRunDiagnostics(conn.id)}
                        disabled={diagnosingConnId === conn.id}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[10px] font-mono font-medium text-indigo-400 hover:text-indigo-300 hover:bg-indigo-500/10 border border-indigo-500/20 transition-all disabled:opacity-50"
                        title="Run granular IAM, EC2, and Cost Explorer health checks"
                      >
                        <Activity size={11} className={diagnosingConnId === conn.id ? "animate-spin" : ""} />
                        {diagnosingConnId === conn.id ? "Checking..." : "Diagnose"}
                      </button>
                      <button
                        onClick={() => handleVerifyConnection(conn.id)}
                        disabled={isVerifyingConnId === conn.id}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[10px] font-mono font-medium text-paper/60 hover:text-paper hover:bg-white/5 border border-white/5 transition-all disabled:opacity-50"
                      >
                        <RefreshCw size={11} className={isVerifyingConnId === conn.id ? "animate-spin" : ""} />
                        Verify
                      </button>
                      <button
                        onClick={() => handleDisconnect(conn.id)}
                        className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[10px] font-mono font-medium text-accent-red/70 hover:text-accent-red hover:bg-red-500/10 border border-red-500/10 transition-all"
                      >
                        <Trash2 size={11} />
                        Disconnect
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        ) : (
          <div className="mt-5 rounded-xl px-4 py-4" style={{ background: "rgba(99,102,241,0.04)", border: "1px solid rgba(99,102,241,0.15)" }}>
            <div className="flex items-start gap-3">
              <ShieldCheck size={18} className="text-indigo-400 shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-semibold text-paper">
                  Secure Cross-Account SaaS Connection
                </p>
                <p className="mt-1 text-[11px] text-paper/60 leading-relaxed">
                  CloudPulse uses 100% read-only cross-account IAM role assumption via AWS STS with unique ExternalId tokens.
                  No root credentials or static secret keys are ever transmitted or stored.
                </p>
                <div className="mt-3">
                  <button
                    onClick={() => setIsWizardOpen(true)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 transition-all shadow-lg"
                  >
                    <Plus size={13} />
                    Launch 4-Step Connection Wizard
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* ============================================================== */}
      {/* AI Weekly Summary                                                */}
      {/* ============================================================== */}
      <section className="glass-panel p-6">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className="flex h-9 w-9 items-center justify-center rounded-xl"
              style={{
                background: "rgba(200,168,255,0.08)",
                border: "1px solid rgba(200,168,255,0.15)",
                boxShadow: "0 0 12px rgba(200,168,255,0.08)",
              }}
            >
              <Sparkles size={16} className="text-accent-purple" />
            </div>
            <div>
              <h3 className="text-base font-bold text-paper font-heading">AI Weekly Summary</h3>
              <p className="text-[10px] font-mono font-medium mt-0.5" style={{ color: "rgba(244,240,230,0.3)" }}>
                LLM-written plain-English recap of the week
              </p>
            </div>
          </div>
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="inline-flex items-center gap-2 rounded-xl px-4 py-2 text-[11px] font-mono font-semibold uppercase tracking-wider transition-all disabled:opacity-50"
            style={{
              background: "rgba(200,168,255,0.08)",
              color: "#c8a8ff",
              border: "1px solid rgba(200,168,255,0.2)",
            }}
          >
            {generating ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {generating ? "Generating…" : "Generate weekly summary"}
          </button>
        </div>

        {insightError && (
          <div
            className="mb-4 rounded-xl px-4 py-3 text-[12px]"
            style={{
              background: "rgba(232,70,44,0.08)",
              color: "rgba(244,240,230,0.8)",
              border: "1px solid rgba(232,70,44,0.2)",
            }}
          >
            <span className="font-semibold text-accent-red">Could not generate:</span> {insightError}
          </div>
        )}

        {insightLoading ? (
          <div className="flex items-center gap-3 py-8 text-sm" style={{ color: "rgba(244,240,230,0.3)" }}>
            <Loader2 size={15} className="animate-spin" /> Loading latest summary…
          </div>
        ) : insight ? (
          <div>
            <p className="whitespace-pre-wrap text-sm leading-relaxed" style={{ color: "rgba(244,240,230,0.85)" }}>
              {insight.summary}
            </p>
            <p className="mt-4 text-[10px] font-mono" style={{ color: "rgba(244,240,230,0.3)" }}>
              Week of {insight.period_start} → {insight.period_end} · {insight.provider}/{insight.model} ·{" "}
              {insight.meta.server_count ?? "—"} servers · {insight.meta.alert_count ?? 0} alerts · total cost $
              {(insight.meta.total_cost ?? 0).toFixed(2)}
            </p>
          </div>
        ) : (
          <div className="rounded-xl px-4 py-6 text-center" style={{ background: "rgba(244,240,230,0.02)" }}>
            <p className="text-sm font-medium" style={{ color: "rgba(244,240,230,0.4)" }}>
              No weekly summary yet
            </p>
            <p className="mt-1 text-[11px] font-mono" style={{ color: "rgba(244,240,230,0.3)" }}>
              The job runs every Monday at 09:00 UTC — or press “Generate weekly summary” now.
            </p>
          </div>
        )}

        <p className="mt-5 border-t pt-3 text-[10px] font-mono leading-relaxed" style={{ color: "rgba(244,240,230,0.25)", borderColor: "rgba(244,240,230,0.06)" }}>
          Anomaly detection uses statistical z-scores over a 7-day rolling baseline — not machine learning. This
          summary is written by an LLM from real alerts and AWS Cost Explorer data (costs lag 24–48h); it never
          invents figures.
        </p>
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

      {/* ============================================================== */}
      {/* AWS Health Diagnostic Result Modal                             */}
      {/* ============================================================== */}
      {isDiagModalOpen && diagnosticResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fade-in">
          <div
            className="w-full max-w-xl rounded-2xl p-6 shadow-2xl space-y-5"
            style={{
              background: "#0d0e12",
              border: "1px solid rgba(244,240,230,0.1)",
            }}
          >
            <div className="flex items-center justify-between border-b border-white/5 pb-4">
              <div className="flex items-center gap-3">
                <div
                  className={`w-9 h-9 rounded-xl flex items-center justify-center ${
                    diagnosticResult.health_status === "HEALTHY"
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                      : diagnosticResult.health_status === "DEGRADED"
                      ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                      : "bg-red-500/10 text-red-400 border border-red-500/20"
                  }`}
                >
                  <Activity size={18} />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-paper">AWS Health Diagnostics</h3>
                  <p className="text-[10px] font-mono text-paper/40">
                    Connection: {diagnosticResult.connection_id}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setIsDiagModalOpen(false)}
                className="p-1.5 rounded-lg text-paper/40 hover:text-paper hover:bg-white/5 transition-all"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex items-center justify-between p-3.5 rounded-xl bg-white/[0.02] border border-white/5">
              <div className="space-y-1">
                <span className="text-[10px] font-mono text-paper/40 uppercase">Overall Health Status</span>
                <div className="text-sm font-semibold text-paper">{diagnosticResult.summary}</div>
              </div>
              <span
                className={`px-2.5 py-1 rounded-md text-xs font-mono font-bold uppercase ${
                  diagnosticResult.health_status === "HEALTHY"
                    ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                    : diagnosticResult.health_status === "DEGRADED"
                    ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                    : "bg-red-500/15 text-red-400 border border-red-500/30"
                }`}
              >
                {diagnosticResult.health_status}
              </span>
            </div>

            <div className="space-y-2.5">
              <div className="text-[11px] font-mono font-semibold text-paper/40 uppercase tracking-wider">
                Granular Health Checks
              </div>
              {Object.entries(diagnosticResult.checks).map(([checkName, check]) => {
                const isPass = check.status === "PASS";
                return (
                  <div
                    key={checkName}
                    className="p-3 rounded-xl border flex items-start justify-between gap-3 text-xs"
                    style={{
                      background: isPass ? "rgba(16,185,129,0.02)" : "rgba(239,68,68,0.04)",
                      borderColor: isPass ? "rgba(16,185,129,0.15)" : "rgba(239,68,68,0.2)",
                    }}
                  >
                    <div className="flex items-start gap-2.5">
                      {isPass ? (
                        <CheckCircle2 size={16} className="text-emerald-400 shrink-0 mt-0.5" />
                      ) : (
                        <XCircle size={16} className="text-red-400 shrink-0 mt-0.5" />
                      )}
                      <div>
                        <div className="font-semibold text-paper capitalize">
                          {checkName.replace(/_/g, " ")}
                        </div>
                        <div className="text-[11px] text-paper/60 mt-0.5">
                          {check.message}
                        </div>
                        {check.error && (
                          <div className="mt-1.5 p-2 rounded bg-red-950/40 border border-red-800/30 text-[10px] font-mono text-red-300">
                            {check.error}
                          </div>
                        )}
                      </div>
                    </div>
                    {check.latency_ms !== undefined && check.latency_ms !== null && (
                      <span className="text-[10px] font-mono text-paper/40 shrink-0">
                        {check.latency_ms}ms
                      </span>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="flex justify-end pt-2">
              <button
                onClick={() => setIsDiagModalOpen(false)}
                className="px-4 py-2 rounded-xl text-xs font-mono font-semibold bg-white/10 text-paper hover:bg-white/15 transition-all"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
