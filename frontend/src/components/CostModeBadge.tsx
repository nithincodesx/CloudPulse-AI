"use client";

import { Cloud, AlertTriangle } from "lucide-react";

interface CostModeBadgeProps {
  connected: boolean;
  small?: boolean;
}

/**
 * Honest cost-mode label. Green when real AWS Cost Explorer data is synced;
 * amber "SIMULATED MODE" when no cloud account is connected — in which case
 * the UI must not show any fabricated cost figure.
 */
export default function CostModeBadge({ connected, small = false }: CostModeBadgeProps) {
  const sizing = small ? "px-2 py-0.5 text-[9px]" : "px-2.5 py-1 text-[10px]";
  const glyph = small ? 9 : 11;

  if (connected) {
    return (
      <span
        className={`inline-flex items-center gap-1.5 rounded-full font-mono font-bold uppercase tracking-wider ${sizing}`}
        style={{
          background: "rgba(16,185,129,0.12)",
          color: "#10b981",
          border: "1px solid rgba(16,185,129,0.25)",
        }}
        title="Cost data sourced from AWS Cost Explorer"
      >
        <Cloud size={glyph} />
        AWS · Real data
      </span>
    );
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full font-mono font-bold uppercase tracking-wider ${sizing}`}
      style={{
        background: "rgba(255,230,0,0.10)",
        color: "#ffe600",
        border: "1px solid rgba(255,230,0,0.22)",
      }}
      title="No cloud account connected — connect AWS to see real spend"
    >
      <AlertTriangle size={glyph} />
      Simulated mode
    </span>
  );
}
