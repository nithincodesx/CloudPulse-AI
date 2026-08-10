"use client";

import {
  Server,
  Cpu,
  HardDrive,
  TrendingDown,
  Activity,
  Settings,
  PowerOff,
} from "lucide-react";

interface MetricRow {
  cpu_usage: number;
  ram_usage: number;
  estimated_cost_per_hour: number;
}

interface ServerRow {
  id: string;
  server_name: string;
  ip_address?: string;
  status: "active" | "warning" | "critical" | "idle";
  specifications?: {
    vcpus?: number;
    ram_gb?: number;
    type?: string;
  };
  latest_metric?: MetricRow;
}

interface ServerTableProps {
  servers: ServerRow[];
  onAction?: (serverId: string, action: "optimize" | "terminate") => void;
  onRowClick?: (serverId: string) => void;
}

const statusMeta: Record<
  string,
  { label: string; color: string; dotColor: string }
> = {
  active:   { label: "Normal",   color: "#10b981", dotColor: "#10b981" },
  warning:  { label: "Warning",  color: "#ffe600", dotColor: "#ffe600" },
  critical: { label: "Critical", color: "#e8462c", dotColor: "#e8462c" },
  idle:     { label: "Idle",     color: "#8a8780", dotColor: "#6b6960" },
};

function projectedSavings(costPerHour: number): number {
  return Math.round(costPerHour * 0.5 * 730 * 100) / 100;
}

function MetricBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="metric-bar">
      <div
        className="metric-bar-fill"
        style={{ width: `${Math.min(value, 100)}%`, background: color }}
      />
    </div>
  );
}

export default function ServerTable({ servers, onAction, onRowClick }: ServerTableProps) {
  const totalSavings = servers
    .filter((s) => s.status === "idle" || s.status === "warning")
    .reduce(
      (acc, s) =>
        acc + projectedSavings(s.latest_metric?.estimated_cost_per_hour ?? 0),
      0
    );

  return (
    <div className="space-y-5">
      {/* Savings banner */}
      {totalSavings > 0 && (
        <div
          className="flex items-center gap-4 rounded-2xl p-4"
          style={{
            background: "linear-gradient(135deg, rgba(16,185,129,0.08) 0%, transparent 60%)",
            border: "1px solid rgba(16,185,129,0.15)",
          }}
        >
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl"
            style={{
              background: "linear-gradient(180deg, #16161a 0%, #0b0b0d 100%)",
              boxShadow: "inset 0 2px 4px rgba(0,0,0,0.5), 0 2px 4px rgba(255,255,255,0.06)",
            }}
          >
            <TrendingDown size={18} className="text-accent-green" />
          </div>
          <p className="text-sm" style={{ color: "rgba(244,240,230,0.7)" }}>
            <span className="font-bold text-accent-green text-lg mr-1.5 drop-shadow-md">
              ${totalSavings.toFixed(2)}
            </span>
            <span className="font-medium">
              projected monthly savings by downsizing underutilized nodes
            </span>
          </p>
        </div>
      )}

      {/* Table */}
      <div
        className="overflow-x-auto rounded-2xl"
        style={{
          background: "linear-gradient(180deg, rgba(22,22,26,0.6) 0%, rgba(11,11,13,0.7) 100%)",
          border: "1px solid rgba(244,240,230,0.06)",
          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.03)",
        }}
      >
        <table className="w-full text-left text-sm">
          <thead>
            <tr style={{ borderBottom: "1px solid rgba(244,240,230,0.06)" }}>
              {["Node", "Status", "CPU", "RAM", "Monthly Est.", "Savings", "Action"].map(
                (h, i) => (
                  <th
                    key={h}
                    className={`px-5 py-4 text-[10px] font-mono font-medium tracking-[0.28em] uppercase ${i === 6 ? "text-right" : ""}`}
                    style={{ color: "rgba(244,240,230,0.35)" }}
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {servers.map((s) => {
              const meta = statusMeta[s.status] ?? statusMeta.active;
              const m = s.latest_metric;
              const cost = m?.estimated_cost_per_hour ?? 0;
              const monthly = Math.round(cost * 730 * 100) / 100;
              const savings =
                s.status === "idle" || s.status === "warning"
                  ? projectedSavings(cost)
                  : 0;

              return (
                <tr
                  key={s.id}
                  data-server-id={s.id}
                  className={`group transition-colors duration-200 ${onRowClick ? "cursor-pointer" : ""}`}
                  style={{ borderBottom: "1px solid rgba(244,240,230,0.04)" }}
                  onClick={() => onRowClick?.(s.id)}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background = "rgba(244,240,230,0.02)")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = "transparent")
                  }
                >
                  {/* Node */}
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div
                        className="flex h-10 w-10 items-center justify-center rounded-xl transition-all"
                        style={{
                          background: "linear-gradient(180deg, #16161a 0%, #0b0b0d 100%)",
                          boxShadow: "inset 0 2px 4px rgba(0,0,0,0.5), 0 2px 4px rgba(255,255,255,0.06)",
                        }}
                      >
                        <Server
                          size={16}
                          className="text-surface-400 group-hover:text-accent-yellow transition-colors"
                        />
                      </div>
                      <div>
                        <p className="font-semibold text-paper tracking-wide text-[13px]">
                          {s.server_name}
                        </p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <Activity size={9} style={{ color: "rgba(244,240,230,0.25)" }} />
                          <p
                            className="text-[10px] font-mono tracking-wider"
                            style={{ color: "rgba(244,240,230,0.3)" }}
                          >
                            {s.ip_address ?? "auto-assigned"}
                          </p>
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* Status */}
                  <td className="px-5 py-4">
                    <span
                      className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[10px] font-mono font-semibold uppercase tracking-[0.16em]"
                      style={{
                        background: `${meta.color}10`,
                        color: meta.color,
                        border: `1px solid ${meta.color}20`,
                      }}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${s.status !== "idle" ? "animate-pulse" : ""}`}
                        style={{
                          background: meta.dotColor,
                          boxShadow: s.status !== "idle" ? `0 0 8px ${meta.dotColor}60` : "none",
                        }}
                      />
                      {meta.label}
                    </span>
                  </td>

                  {/* CPU */}
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      <Cpu size={13} style={{ color: "rgba(244,240,230,0.25)" }} />
                      <div>
                        <span className="font-mono text-sm font-bold text-paper">
                          {m ? `${m.cpu_usage.toFixed(1)}%` : "—"}
                        </span>
                        {m && <MetricBar value={m.cpu_usage} color="#ffe600" />}
                      </div>
                    </div>
                  </td>

                  {/* RAM */}
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      <HardDrive size={13} style={{ color: "rgba(244,240,230,0.25)" }} />
                      <div>
                        <span className="font-mono text-sm font-bold text-paper">
                          {m ? `${m.ram_usage.toFixed(1)}%` : "—"}
                        </span>
                        {m && <MetricBar value={m.ram_usage} color="#c8a8ff" />}
                      </div>
                    </div>
                  </td>

                  {/* Monthly */}
                  <td className="px-5 py-4 font-mono text-sm font-medium" style={{ color: "rgba(244,240,230,0.6)" }}>
                    ${monthly.toFixed(2)}
                  </td>

                  {/* Savings */}
                  <td className="px-5 py-4">
                    {savings > 0 ? (
                      <span className="font-mono text-sm font-bold text-accent-green drop-shadow-sm">
                        -${savings.toFixed(2)}
                      </span>
                    ) : (
                      <span style={{ color: "rgba(244,240,230,0.15)" }}>—</span>
                    )}
                  </td>

                  {/* Action */}
                  <td className="px-5 py-4 text-right">
                    {s.status === "warning" && onAction && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onAction(s.id, "optimize");
                        }}
                        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-[11px] font-mono font-semibold tracking-wider uppercase transition-all"
                        style={{
                          background: "rgba(244,240,230,0.04)",
                          color: "rgba(244,240,230,0.5)",
                          border: "1px solid rgba(244,240,230,0.08)",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "#ffe600";
                          e.currentTarget.style.color = "#0a0a0b";
                          e.currentTarget.style.borderColor = "#ffe600";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "rgba(244,240,230,0.04)";
                          e.currentTarget.style.color = "rgba(244,240,230,0.5)";
                          e.currentTarget.style.borderColor = "rgba(244,240,230,0.08)";
                        }}
                      >
                        <Settings size={13} /> Optimize
                      </button>
                    )}
                    {s.status === "idle" && onAction && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onAction(s.id, "terminate");
                        }}
                        className="inline-flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-[11px] font-mono font-semibold tracking-wider uppercase transition-all"
                        style={{
                          background: "rgba(244,240,230,0.04)",
                          color: "rgba(244,240,230,0.5)",
                          border: "1px solid rgba(244,240,230,0.08)",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = "#e8462c";
                          e.currentTarget.style.color = "#fafaf7";
                          e.currentTarget.style.borderColor = "#e8462c";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "rgba(244,240,230,0.04)";
                          e.currentTarget.style.color = "rgba(244,240,230,0.5)";
                          e.currentTarget.style.borderColor = "rgba(244,240,230,0.08)";
                        }}
                      >
                        <PowerOff size={13} /> Terminate
                      </button>
                    )}
                    {s.status !== "warning" && s.status !== "idle" && (
                      <span className="text-[11px]" style={{ color: "rgba(244,240,230,0.15)" }}>—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {servers.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20">
          <div
            className="h-16 w-16 rounded-2xl flex items-center justify-center mb-4"
            style={{
              background: "linear-gradient(180deg, #16161a 0%, #0b0b0d 100%)",
              boxShadow: "inset 0 3px 6px rgba(0,0,0,0.65), inset 0 -2px 4px rgba(255,255,255,0.06), 0 2px 4px rgba(255,255,255,0.08)",
            }}
          >
            <Server size={28} style={{ color: "rgba(244,240,230,0.2)" }} />
          </div>
          <p className="text-sm font-medium" style={{ color: "rgba(244,240,230,0.35)" }}>
            No servers registered
          </p>
        </div>
      )}
    </div>
  );
}
