"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Sparkles,
  TrendingDown,
  DollarSign,
  AlertTriangle,
  Server,
  Zap,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Filter,
  ChevronDown,
  ChevronUp,
  Cpu,
  Layers,
  ArrowRight,
  Info,
  ShieldAlert,
  Loader2,
} from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
import KpiCard from "@/components/KpiCard";
import {
  fetchOptimizationSummary,
  fetchOptimizationRecommendations,
  triggerOptimizationAnalysis,
  updateRecommendationStatus,
} from "@/lib/supabase";
import type { OptimizationRecommendation, OptimizationSummary } from "@/lib/types";

const fmtMoney = (n: number) =>
  `$${(n || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function OptimizationPage() {
  const { data: dashboardData } = useDashboard();
  const [summary, setSummary] = useState<OptimizationSummary | null>(null);
  const [recommendations, setRecommendations] = useState<OptimizationRecommendation[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Filter States
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [statusFilter, setStatusFilter] = useState<string>("active");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadOptimizationData = useCallback(async () => {
    try {
      const [sum, recs] = await Promise.all([
        fetchOptimizationSummary(),
        fetchOptimizationRecommendations({ status: statusFilter }),
      ]);
      if (sum) setSummary(sum);
      if (recs) setRecommendations(recs);
    } catch (err) {
      console.warn("Failed to load optimization data:", err);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    loadOptimizationData();
  }, [loadOptimizationData]);

  const handleRunAnalysis = async () => {
    setAnalyzing(true);
    setMsg(null);
    try {
      const res = await triggerOptimizationAnalysis();
      if (res) {
        setSummary(res.summary);
        setRecommendations(res.recommendations);
        setMsg({
          type: "success",
          text: `Scan complete: Analyzed ${res.analyzed_servers_count} instances, generated ${res.recommendations_generated_count} optimization recommendations.`,
        });
      } else {
        setMsg({ type: "error", text: "Analysis completed with no new recommendations." });
      }
    } catch (err: any) {
      setMsg({ type: "error", text: err?.message || "Failed to run optimization analysis." });
    } finally {
      setAnalyzing(false);
    }
  };

  const handleStatusChange = async (recId: string, newStatus: "applied" | "dismissed") => {
    setActionLoading(recId);
    try {
      // Optimistic update
      setRecommendations((prev) => prev.filter((r) => r.id !== recId));
      if (summary) {
        setSummary((prev) =>
          prev
            ? {
                ...prev,
                total_opportunities_count: Math.max(0, prev.total_opportunities_count - 1),
              }
            : prev
        );
      }
      await updateRecommendationStatus(recId, newStatus);
      setMsg({
        type: "success",
        text: `Recommendation marked as ${newStatus}.`,
      });
    } catch (err) {
      console.error("Failed to update status:", err);
      loadOptimizationData();
    } finally {
      setActionLoading(null);
    }
  };

  // Filter recommendations
  const filteredRecs = recommendations.filter((r) => {
    if (typeFilter !== "ALL" && r.recommendation_type !== typeFilter) return false;
    if (severityFilter !== "ALL" && r.severity !== severityFilter) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchName = r.resource_name.toLowerCase().includes(q);
      const matchType = r.recommendation_type.toLowerCase().includes(q);
      const matchProblem = r.problem_summary.toLowerCase().includes(q);
      if (!matchName && !matchType && !matchProblem) return false;
    }
    return true;
  });

  const getSeverityBadge = (sev: string) => {
    switch (sev.toLowerCase()) {
      case "critical":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      case "warning":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      case "info":
      default:
        return "bg-sky-500/10 text-sky-400 border-sky-500/20";
    }
  };

  const getTypeBadge = (t: string) => {
    switch (t) {
      case "IDLE_RESOURCE":
        return "bg-purple-500/10 text-purple-400 border-purple-500/20";
      case "RIGHT_SIZING":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "LOW_UTILIZATION":
        return "bg-blue-500/10 text-blue-400 border-blue-500/20";
      case "COST_SPIKE":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      default:
        return "bg-zinc-500/10 text-zinc-400 border-zinc-500/20";
    }
  };

  return (
    <div className="space-y-6 pb-12 animate-fade-in">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border/40 pb-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="font-mono text-xs font-medium uppercase tracking-wider text-emerald-400">
              Rule-Based Cost Optimizer
            </span>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Cost Optimization & Savings
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Real-time infrastructure waste detection, right-sizing candidates, and verified AWS On-Demand savings.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRunAnalysis}
            disabled={analyzing}
            className="flex items-center gap-2 rounded-lg bg-primary/10 border border-primary/20 px-3.5 py-2 text-xs font-medium text-primary hover:bg-primary/20 transition-all shadow-sm active:scale-95 disabled:opacity-50"
          >
            {analyzing ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Scanning Infrastructure...
              </>
            ) : (
              <>
                <Sparkles className="h-3.5 w-3.5 text-amber-400" />
                Run Fleet Analysis
              </>
            )}
          </button>
        </div>
      </div>

      {/* Notification Message */}
      {msg && (
        <div
          className={`flex items-center justify-between p-3.5 rounded-xl border text-xs ${
            msg.type === "success"
              ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-300"
              : "bg-rose-500/10 border-rose-500/20 text-rose-300"
          }`}
        >
          <div className="flex items-center gap-2">
            {msg.type === "success" ? (
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-rose-400" />
            )}
            <span>{msg.text}</span>
          </div>
          <button
            onClick={() => setMsg(null)}
            className="text-muted-foreground hover:text-foreground font-mono text-xs"
          >
            ✕
          </button>
        </div>
      )}

      {/* 4 Core KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <KpiCard
          label="Total Monthly Spend"
          value={fmtMoney(summary?.total_monthly_spend || 0)}
          icon={<DollarSign className="h-4 w-4" />}
          trend="neutral"
          trendLabel="Current Fleet Cost"
        />
        <KpiCard
          label="Estimated Avoidable Spend"
          value={fmtMoney(summary?.estimated_avoidable_spend || 0)}
          icon={<AlertTriangle className="h-4 w-4" />}
          trend="up"
          trendLabel="Identified Waste"
          highlight={Boolean((summary?.estimated_avoidable_spend || 0) > 0)}
        />
        <KpiCard
          label="Potential Monthly Savings"
          value={fmtMoney(summary?.potential_monthly_savings || 0)}
          icon={<TrendingDown className="h-4 w-4" />}
          trend="down"
          trendLabel={`${
            summary?.total_monthly_spend
              ? Math.round(((summary.potential_monthly_savings || 0) / summary.total_monthly_spend) * 100)
              : 0
          }% reduction`}
        />
        <KpiCard
          label="Active Opportunities"
          value={summary?.total_opportunities_count ?? 0}
          icon={<Zap className="h-4 w-4" />}
          trend={summary?.by_severity_counts?.critical ? "up" : "neutral"}
          trendLabel={`${summary?.by_severity_counts?.critical ?? 0} Critical`}
        />
      </div>

      {/* Summary Highlight Cards (Highest Spend vs Highest Savings) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Highest Spend Resources */}
        <div className="rounded-xl border border-border/40 bg-card/60 backdrop-blur-md p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Server className="h-3.5 w-3.5 text-sky-400" />
              Highest-Cost Resources
            </h3>
            <span className="font-mono text-[11px] text-muted-foreground">Top 5</span>
          </div>

          {summary?.highest_cost_resources && summary.highest_cost_resources.length > 0 ? (
            <div className="space-y-2">
              {summary.highest_cost_resources.slice(0, 4).map((r, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2.5 rounded-lg bg-background/40 border border-border/30 text-xs"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="h-7 w-7 rounded-md bg-sky-500/10 border border-sky-500/20 flex items-center justify-center font-mono text-[10px] text-sky-400">
                      {r.instance_type !== "unknown" ? r.instance_type.split(".")[0] : "EC2"}
                    </div>
                    <div>
                      <div className="font-medium text-foreground">{r.resource_name}</div>
                      <div className="font-mono text-[11px] text-muted-foreground">
                        {r.instance_type} • {r.region}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono font-medium text-foreground">{fmtMoney(r.monthly_cost)}/mo</div>
                    <div className="text-[10px] text-muted-foreground">{r.source}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-muted-foreground">
              No resource cost data recorded yet.
            </div>
          )}
        </div>

        {/* Highest Savings Opportunities */}
        <div className="rounded-xl border border-border/40 bg-card/60 backdrop-blur-md p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5 text-amber-400" />
              Top Savings Opportunities
            </h3>
            <span className="font-mono text-[11px] text-emerald-400">High Impact</span>
          </div>

          {summary?.highest_savings_opportunities && summary.highest_savings_opportunities.length > 0 ? (
            <div className="space-y-2">
              {summary.highest_savings_opportunities.slice(0, 4).map((opp, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between p-2.5 rounded-lg bg-background/40 border border-border/30 text-xs"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="h-7 w-7 rounded-md bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center font-mono text-[10px] text-emerald-400">
                      save
                    </div>
                    <div>
                      <div className="font-medium text-foreground">{opp.resource_name}</div>
                      <div className="text-[11px] text-muted-foreground truncate max-w-[220px]">
                        {opp.action}
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-mono font-medium text-emerald-400">
                      +{fmtMoney(opp.monthly_savings)}/mo
                    </div>
                    <span className="text-[10px] text-muted-foreground uppercase">{opp.confidence} conf</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-6 text-center text-xs text-muted-foreground">
              Run fleet analysis to detect optimization opportunities.
            </div>
          )}
        </div>
      </div>

      {/* Filter Bar */}
      <div className="rounded-xl border border-border/40 bg-card/60 backdrop-blur-md p-3.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground mr-1">
            <Filter className="h-3.5 w-3.5" />
            <span>Filters:</span>
          </div>

          {/* Type Filter */}
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="rounded-lg bg-background/60 border border-border/50 px-2.5 py-1.5 text-xs text-foreground font-mono focus:outline-none focus:border-primary/50"
          >
            <option value="ALL">All Types</option>
            <option value="IDLE_RESOURCE">Idle Resource</option>
            <option value="RIGHT_SIZING">Right-Sizing</option>
            <option value="LOW_UTILIZATION">Low Utilization</option>
            <option value="COST_SPIKE">Cost Spike</option>
          </select>

          {/* Severity Filter */}
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="rounded-lg bg-background/60 border border-border/50 px-2.5 py-1.5 text-xs text-foreground font-mono focus:outline-none focus:border-primary/50"
          >
            <option value="ALL">All Severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg bg-background/60 border border-border/50 px-2.5 py-1.5 text-xs text-foreground font-mono focus:outline-none focus:border-primary/50"
          >
            <option value="active">Active Recommendations</option>
            <option value="applied">Applied</option>
            <option value="dismissed">Dismissed</option>
          </select>
        </div>

        {/* Search */}
        <input
          type="text"
          placeholder="Search by instance, rule, or issue..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="rounded-lg bg-background/60 border border-border/50 px-3 py-1.5 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/50 w-full sm:w-64"
        />
      </div>

      {/* Recommendations List / Table */}
      <div className="space-y-3">
        {loading ? (
          <div className="py-16 text-center text-xs text-muted-foreground flex flex-col items-center justify-center gap-2">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <span>Analyzing infrastructure recommendations...</span>
          </div>
        ) : filteredRecs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border/60 p-12 text-center space-y-3">
            <div className="h-10 w-10 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 flex items-center justify-center mx-auto">
              <CheckCircle2 className="h-5 w-5" />
            </div>
            <h3 className="text-sm font-medium text-foreground">No Optimization Issues Detected</h3>
            <p className="text-xs text-muted-foreground max-w-md mx-auto">
              All infrastructure nodes are operating within optimal utilization bounds, or recommendations have already been resolved.
            </p>
            <button
              onClick={handleRunAnalysis}
              disabled={analyzing}
              className="mt-2 inline-flex items-center gap-2 rounded-lg bg-primary/10 border border-primary/20 px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/20 transition-all"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${analyzing ? "animate-spin" : ""}`} />
              Re-Scan Fleet
            </button>
          </div>
        ) : (
          filteredRecs.map((rec) => {
            const isExpanded = expandedId === rec.id;
            return (
              <div
                key={rec.id || rec.server_id}
                className="rounded-xl border border-border/40 bg-card/60 backdrop-blur-md overflow-hidden transition-all hover:border-border/70"
              >
                {/* Main Card Header */}
                <div className="p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <div className="space-y-1.5 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold text-foreground text-sm">
                        {rec.resource_name}
                      </span>
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider border ${getTypeBadge(
                          rec.recommendation_type
                        )}`}
                      >
                        {rec.recommendation_type.replace("_", " ")}
                      </span>
                      <span
                        className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider border ${getSeverityBadge(
                          rec.severity
                        )}`}
                      >
                        {rec.severity}
                      </span>
                      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-mono text-muted-foreground bg-zinc-800/40 border border-zinc-700/30">
                        {rec.region || "us-east-1"}
                      </span>
                      <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-mono text-emerald-400 bg-emerald-950/30 border border-emerald-800/30">
                        {rec.pricing_source === "aws_catalog"
                          ? "AWS Verified Catalog"
                          : rec.pricing_source}
                      </span>
                    </div>

                    <p className="text-xs text-muted-foreground">{rec.problem_summary}</p>
                  </div>

                  {/* Pricing / Savings Pill */}
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <div className="font-mono text-xs text-muted-foreground">
                        Current: <span className="text-foreground">{fmtMoney(rec.current_cost_monthly)}/mo</span>
                      </div>
                      <div className="font-mono text-sm font-semibold text-emerald-400">
                        Save {fmtMoney(rec.estimated_savings_monthly)}/mo
                      </div>
                    </div>

                    {/* Action Buttons */}
                    {rec.status === "active" && (
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleStatusChange(rec.id, "applied")}
                          disabled={actionLoading === rec.id}
                          className="flex items-center gap-1 rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-3 py-1.5 text-xs font-medium text-emerald-400 hover:bg-emerald-500/20 transition-all active:scale-95 disabled:opacity-50"
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Apply
                        </button>
                        <button
                          onClick={() => handleStatusChange(rec.id, "dismissed")}
                          disabled={actionLoading === rec.id}
                          className="flex items-center gap-1 rounded-lg bg-zinc-800 border border-border/40 px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-all active:scale-95 disabled:opacity-50"
                        >
                          Dismiss
                        </button>
                      </div>
                    )}

                    {/* Expand Evidence Toggle */}
                    <button
                      onClick={() => setExpandedId(isExpanded ? null : rec.id)}
                      className="p-1.5 text-muted-foreground hover:text-foreground rounded-lg hover:bg-background/60 transition-all"
                      aria-label="Toggle Evidence"
                    >
                      {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                    </button>
                  </div>
                </div>

                {/* Recommendation & Target Resource Strip */}
                <div className="px-4 py-2.5 bg-background/40 border-t border-border/30 flex flex-wrap items-center justify-between text-xs text-muted-foreground gap-2">
                  <div className="flex items-center gap-2">
                    <Zap className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                    <span className="font-medium text-foreground">Action:</span>
                    <span>{rec.action_recommendation}</span>
                  </div>

                  {rec.target_resource_type && (
                    <div className="flex items-center gap-2 font-mono text-[11px] bg-background/60 px-2 py-0.5 rounded border border-border/40">
                      <span>{rec.evidence?.current_instance_type}</span>
                      <ArrowRight className="h-3 w-3 text-emerald-400" />
                      <span className="font-bold text-emerald-400">{rec.target_resource_type}</span>
                    </div>
                  )}
                </div>

                {/* Expandable Evidence Drawer */}
                {isExpanded && (
                  <div className="p-4 bg-background/80 border-t border-border/40 space-y-3 animate-fade-in text-xs">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
                      <Info className="h-3.5 w-3.5 text-sky-400" />
                      <span>Evidence & Telemetry Metrics</span>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-[11px]">
                      <div className="p-2.5 rounded-lg bg-card/70 border border-border/30">
                        <div className="text-muted-foreground text-[10px]">Average CPU</div>
                        <div className="text-foreground font-semibold text-sm mt-0.5">
                          {rec.evidence?.avg_cpu !== undefined ? `${rec.evidence.avg_cpu}%` : "—"}
                        </div>
                      </div>
                      <div className="p-2.5 rounded-lg bg-card/70 border border-border/30">
                        <div className="text-muted-foreground text-[10px]">Peak CPU</div>
                        <div className="text-foreground font-semibold text-sm mt-0.5">
                          {rec.evidence?.peak_cpu !== undefined ? `${rec.evidence.peak_cpu}%` : "—"}
                        </div>
                      </div>
                      <div className="p-2.5 rounded-lg bg-card/70 border border-border/30">
                        <div className="text-muted-foreground text-[10px]">Average RAM</div>
                        <div className="text-foreground font-semibold text-sm mt-0.5">
                          {rec.evidence?.avg_ram !== undefined ? `${rec.evidence.avg_ram}%` : "—"}
                        </div>
                      </div>
                      <div className="p-2.5 rounded-lg bg-card/70 border border-border/30">
                        <div className="text-muted-foreground text-[10px]">Telemetry Samples</div>
                        <div className="text-foreground font-semibold text-sm mt-0.5">
                          {rec.evidence?.sample_count ?? 0}
                        </div>
                      </div>
                    </div>

                    {rec.evidence?.waste_reasons && rec.evidence.waste_reasons.length > 0 && (
                      <div className="space-y-1 mt-2">
                        <div className="text-[11px] font-medium text-muted-foreground">Flagging Rationale:</div>
                        <ul className="list-disc list-inside space-y-1 text-muted-foreground text-[11px]">
                          {rec.evidence.waste_reasons.map((reason, rIdx) => (
                            <li key={rIdx}>{reason}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
