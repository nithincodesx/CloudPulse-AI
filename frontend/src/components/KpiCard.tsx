"use client";

import { ArrowUp, ArrowDown, Minus } from "lucide-react";

interface KpiCardProps {
  label: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  trend?: "up" | "down" | "neutral";
  trendLabel?: string;
  highlight?: boolean;
  accent?: string;
  /** Optional status badge (e.g. cost-mode label) rendered under the label. */
  badge?: React.ReactNode;
}

const trendMeta: Record<string, { color: string; icon: React.ReactNode }> = {
  up:      { color: "text-accent-red",   icon: <ArrowUp size={13} /> },
  down:    { color: "text-accent-green", icon: <ArrowDown size={13} /> },
  neutral: { color: "text-surface-400",  icon: <Minus size={13} /> },
};

export default function KpiCard({
  label,
  value,
  subtitle,
  icon,
  trend,
  trendLabel,
  highlight = false,
  badge,
}: KpiCardProps) {
  return (
    <div className="premium-pill group cursor-default">
      <div className="dark-tile flex flex-col gap-4 p-5 rounded-[16px]">
        {/* Header row */}
        <div className="flex items-start justify-between relative z-10">
          <div className="space-y-1.5">
            <p
              className="text-[10px] font-mono font-medium tracking-[0.28em] uppercase"
              style={{ color: "rgba(244,240,230,0.45)" }}
            >
              {label}
            </p>
            {badge}
          </div>
          <div
            className={`flex h-10 w-10 items-center justify-center rounded-xl ${
              highlight
                ? "bg-accent-red/20 text-accent-orange"
                : "bg-surface-800 text-accent-yellow"
            }`}
            style={{
              boxShadow:
                "0 8px 16px -6px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.08), inset 0 -2px 4px rgba(0,0,0,0.4)",
            }}
          >
            {icon}
          </div>
        </div>

        {/* Value */}
        <div className="relative z-10">
          <p className="kpi-value text-3xl font-extrabold tracking-tight text-paper font-heading drop-shadow-md">
            {value}
          </p>
          {subtitle && (
            <p className="text-xs mt-1" style={{ color: "rgba(244,240,230,0.35)" }}>
              {subtitle}
            </p>
          )}
        </div>

        {/* Trend */}
        {trend && trendLabel && (
          <div className="flex items-center gap-2 relative z-10 pt-2 border-t" style={{ borderColor: "rgba(244,240,230,0.06)" }}>
            <span className={`flex items-center gap-1 text-xs font-semibold tracking-wide ${trendMeta[trend].color}`}>
              {trendMeta[trend].icon}
              {trendLabel}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
