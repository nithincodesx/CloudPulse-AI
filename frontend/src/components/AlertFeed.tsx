"use client";

import { AlertTriangle, Zap, DollarSign, CheckCircle, Wifi, Check } from "lucide-react";

interface Alert {
  id: string;
  alert_type: "HIGH_CPU" | "IDLE_RESOURCE" | "BUDGET_SPIKE" | "NETWORK_ANOMALY";
  message: string;
  resolved: boolean;
  created_at: string;
  servers?: { server_name: string };
}

interface AlertFeedProps {
  alerts: Alert[];
  onDismiss: (id: string) => void;
}

const alertConfig: Record<
  string,
  { icon: React.ReactNode; accentColor: string; label: string }
> = {
  HIGH_CPU: {
    icon: <Zap size={14} />,
    accentColor: "#e8462c",
    label: "High CPU",
  },
  IDLE_RESOURCE: {
    icon: <AlertTriangle size={14} />,
    accentColor: "#ffe600",
    label: "Idle Resource",
  },
  BUDGET_SPIKE: {
    icon: <DollarSign size={14} />,
    accentColor: "#ff8f7a",
    label: "Budget Spike",
  },
  NETWORK_ANOMALY: {
    icon: <Wifi size={14} />,
    accentColor: "#c8a8ff",
    label: "Net Anomaly",
  },
};

function timeAgo(dateStr: string) {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function AlertFeed({ alerts, onDismiss }: AlertFeedProps) {
  return (
    <div className="alert-feed flex flex-col gap-3 overflow-y-auto pr-1" style={{ maxHeight: 420 }}>
      {alerts.length === 0 && (
        <div className="flex flex-col items-center justify-center py-14">
          <div
            className="h-14 w-14 rounded-2xl flex items-center justify-center mb-4"
            style={{
              background: "linear-gradient(180deg, #16161a 0%, #0b0b0d 100%)",
              boxShadow: "inset 0 3px 6px rgba(0,0,0,0.65), inset 0 -2px 4px rgba(255,255,255,0.06), 0 2px 4px rgba(255,255,255,0.08)",
            }}
          >
            <CheckCircle size={24} className="text-accent-green" />
          </div>
          <p className="text-sm font-semibold" style={{ color: "rgba(244,240,230,0.5)" }}>
            All clear — no active alerts
          </p>
        </div>
      )}
      {alerts.map((alert) => {
        const cfg = alertConfig[alert.alert_type] ?? alertConfig.HIGH_CPU;
        const isCritical = alert.alert_type === "HIGH_CPU" || alert.alert_type === "NETWORK_ANOMALY";
        return (
          <div
            key={alert.id}
            className={`group relative rounded-2xl p-4 transition-all duration-400 cursor-default ${isCritical ? "alert-critical" : ""}`}
            style={{
              background: "linear-gradient(180deg, rgba(22,22,26,0.9) 0%, rgba(11,11,13,0.95) 100%)",
              border: `1px solid ${cfg.accentColor}18`,
              boxShadow: `inset 0 1px 0 rgba(255,255,255,0.04), 0 0 20px ${cfg.accentColor}10`,
            }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3">
                <div
                  className="mt-0.5 rounded-xl p-2 flex items-center justify-center"
                  style={{
                    background: `${cfg.accentColor}15`,
                    color: cfg.accentColor,
                    boxShadow: `0 0 12px ${cfg.accentColor}20`,
                  }}
                >
                  {cfg.icon}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span
                      className="inline-block rounded-full px-2.5 py-0.5 text-[9px] font-mono font-semibold uppercase tracking-[0.18em]"
                      style={{
                        background: `${cfg.accentColor}12`,
                        color: cfg.accentColor,
                      }}
                    >
                      {cfg.label}
                    </span>
                    {alert.servers?.server_name && (
                      <span className="truncate text-[11px] font-semibold font-mono" style={{ color: "rgba(244,240,230,0.55)" }}>
                        {alert.servers.server_name}
                      </span>
                    )}
                  </div>
                  <p className="text-xs leading-relaxed" style={{ color: "rgba(244,240,230,0.7)" }}>
                    {alert.message}
                  </p>
                  <p className="mt-2 text-[10px] font-mono font-medium uppercase tracking-[0.2em]" style={{ color: "rgba(244,240,230,0.25)" }}>
                    {timeAgo(alert.created_at)}
                  </p>
                </div>
              </div>
              <button
                onClick={() => onDismiss(alert.id)}
                className="shrink-0 flex items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-[10px] font-mono font-semibold tracking-wider uppercase opacity-0 group-hover:opacity-100 transition-all duration-300"
                style={{
                  background: "rgba(244,240,230,0.06)",
                  color: "rgba(244,240,230,0.4)",
                  border: "1px solid rgba(244,240,230,0.08)",
                }}
                title="Mark as resolved"
              >
                <Check size={11} />
                Resolve
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
