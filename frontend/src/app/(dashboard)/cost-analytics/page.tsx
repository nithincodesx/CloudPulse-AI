"use client";

import { DollarSign, TrendingDown, TrendingUp, Filter } from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
import KpiCard from "@/components/KpiCard";
import ServerTable from "@/components/ServerTable";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";

export default function CostAnalyticsPage() {
  const { data, loading, handleServerAction } = useDashboard();
  const summary = data?.summary;
  
  if (loading && !data) {
    return <div className="p-6 text-paper/50">Loading analytics...</div>;
  }

  // Calculate potential savings (servers in warning/idle state)
  const serverRows = data
    ? data.servers.map((srv) => {
        const metrics = data.metrics[srv.id];
        return {
          ...srv,
          latest_metric: metrics?.[metrics.length - 1],
        };
      })
    : [];

  const projectedSavings = serverRows
    .filter((s) => s.status === "idle" || s.status === "warning")
    .reduce((acc, s) => acc + (s.latest_metric?.estimated_cost_per_hour ?? 0) * 0.5 * 730, 0);

  // Generate a mock history for the cost area chart based on the current hourly cost
  // In a real scenario, this would come from the backend's historical daily metrics.
  const baseHourly = summary?.hourly_cost_estimate ?? 0;
  const costChartData = Array.from({ length: 24 }).map((_, i) => {
    const time = new Date(Date.now() - (23 - i) * 3600000);
    const fluctuation = Math.sin(i / 2) * 0.05 + 1; // fake curve
    return {
      time: time.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      compute: (baseHourly * 0.7 * fluctuation).toFixed(3),
      network: (baseHourly * 0.2 * fluctuation).toFixed(3),
      storage: (baseHourly * 0.1).toFixed(3), // static storage cost
    };
  });

  return (
    <main className="flex-1 p-6 overflow-y-auto space-y-6">
      <section className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="MTD Total Spend"
          value={`$${summary?.monthly_cost_estimate ? (summary.monthly_cost_estimate * 0.6).toLocaleString() : 0}`} // rough MTD fake
          subtitle="Month-to-Date"
          icon={<DollarSign size={20} />}
          trend="up"
          trendLabel="+12% vs last month"
          highlight
        />
        <KpiCard
          label="Proj. Monthly Run Rate"
          value={`$${summary?.monthly_cost_estimate?.toLocaleString() ?? 0}`}
          subtitle="Estimated End-of-Month"
          icon={<TrendingUp size={20} />}
          trend={summary && summary.hourly_cost_estimate > 0.25 ? "up" : "down"}
          trendLabel="Over budget by 4%"
        />
        <KpiCard
          label="Hourly Burn Rate"
          value={`$${summary?.hourly_cost_estimate?.toFixed(3) ?? 0}`}
          subtitle="Cluster-wide aggregate"
          icon={<DollarSign size={20} />}
          trend="neutral"
          trendLabel="Stable"
        />
        <KpiCard
          label="Potential Savings"
          value={`$${Math.round(projectedSavings).toLocaleString()}`}
          subtitle="From idle/warning nodes"
          icon={<TrendingDown size={20} />}
          trend="down"
          trendLabel="Optimize 1 node"
          highlight={projectedSavings > 0}
        />
      </section>

      <section className="glass-panel p-6">
        <div className="mb-6">
          <div className="eyebrow mb-3">24-Hour Trend</div>
          <h3 className="text-base font-bold text-paper font-heading">Cost Fluctuations</h3>
        </div>
        <div className="h-[300px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={costChartData} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="colorCompute" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="colorNetwork" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(244,240,230,0.04)" vertical={false} />
              <XAxis 
                dataKey="time" 
                stroke="rgba(244,240,230,0.2)" 
                tick={{ fill: "rgba(244,240,230,0.4)", fontSize: 10, fontFamily: "var(--font-mono)" }}
                tickLine={false}
                axisLine={false}
                minTickGap={30}
              />
              <YAxis 
                stroke="rgba(244,240,230,0.2)"
                tick={{ fill: "rgba(244,240,230,0.4)", fontSize: 10, fontFamily: "var(--font-mono)" }}
                tickLine={false}
                axisLine={false}
                tickFormatter={(val) => `$${val}`}
              />
              <Tooltip 
                contentStyle={{
                  backgroundColor: "rgba(11,11,13,0.9)",
                  backdropFilter: "blur(12px)",
                  border: "1px solid rgba(244,240,230,0.08)",
                  borderRadius: "12px",
                  color: "#f4f0e6",
                  fontFamily: "var(--font-mono)",
                  fontSize: "11px",
                  boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
                }}
                itemStyle={{ color: "#f4f0e6" }}
              />
              <Area type="monotone" dataKey="compute" stackId="1" stroke="#10b981" fillOpacity={1} fill="url(#colorCompute)" />
              <Area type="monotone" dataKey="network" stackId="1" stroke="#06b6d4" fillOpacity={1} fill="url(#colorNetwork)" />
              <Area type="monotone" dataKey="storage" stackId="1" stroke="#ffe600" fillOpacity={0.1} fill="#ffe600" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="glass-panel p-6">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-paper font-heading">Cost Breakdown & Optimization Matrix</h3>
            <p className="text-[10px] font-mono font-medium mt-0.5 text-paper/30">Itemized breakdown of instances ranked by cost impact</p>
          </div>
          <button className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-[11px] font-mono font-semibold uppercase tracking-wider text-paper/40 border border-white/5 hover:bg-white/5 transition-all">
            <Filter size={14} /> Sort: Highest Cost
          </button>
        </div>
        <ServerTable servers={serverRows.sort((a,b) => (b.latest_metric?.estimated_cost_per_hour ?? 0) - (a.latest_metric?.estimated_cost_per_hour ?? 0))} onAction={handleServerAction} />
      </section>
    </main>
  );
}
