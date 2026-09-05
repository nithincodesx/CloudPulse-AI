"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  CheckCircle2,
  Circle,
  Cloud,
  ShieldCheck,
  Server,
  ArrowRight,
  Sparkles,
  RefreshCw,
  X,
} from "lucide-react";
import AWSConnectionWizard from "./AWSConnectionWizard";
import { useDashboard } from "@/lib/DashboardContext";
import type { AWSConnection } from "@/lib/types";

interface OnboardingGuideProps {
  connections: AWSConnection[];
  serverCount: number;
  onRefresh: () => void;
}

export default function OnboardingGuide({
  connections,
  serverCount,
  onRefresh,
}: OnboardingGuideProps) {
  const [isWizardOpen, setIsWizardOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  if (dismissed) return null;

  const hasConnection = connections.some((c) => c.status === "connected");
  const hasResources = serverCount > 0;

  // If already connected with resources, show compact status or hide
  if (hasConnection && hasResources) {
    return null;
  }

  const steps = [
    {
      id: 1,
      title: "Create Workspace",
      desc: "Multi-tenant tenant workspace active",
      completed: true,
      icon: <CheckCircle2 size={16} className="text-emerald-400" />,
    },
    {
      id: 2,
      title: "Connect AWS Account",
      desc: "Cross-account IAM AssumeRole with ExternalId",
      completed: hasConnection,
      current: !hasConnection,
      action: !hasConnection ? (
        <button
          onClick={() => setIsWizardOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-500 shadow-lg"
        >
          <Cloud size={13} />
          Connect AWS
        </button>
      ) : null,
      icon: hasConnection ? (
        <CheckCircle2 size={16} className="text-emerald-400" />
      ) : (
        <Circle size={16} className="text-indigo-400" />
      ),
    },
    {
      id: 3,
      title: "Verify Permissions",
      desc: "Read-only EC2 & Cost Explorer verification",
      completed: hasConnection,
      current: hasConnection && !hasResources,
      icon: hasConnection ? (
        <CheckCircle2 size={16} className="text-emerald-400" />
      ) : (
        <Circle size={16} className="text-zinc-600" />
      ),
    },
    {
      id: 4,
      title: "Discover Infrastructure",
      desc: "Sync EC2 instances & daily costs",
      completed: hasResources,
      current: hasConnection && !hasResources,
      action: hasConnection && !hasResources ? (
        <Link
          href="/cost-analytics"
          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-500 shadow-lg"
        >
          <RefreshCw size={13} />
          Sync Infrastructure
        </Link>
      ) : null,
      icon: hasResources ? (
        <CheckCircle2 size={16} className="text-emerald-400" />
      ) : (
        <Circle size={16} className="text-zinc-600" />
      ),
    },
  ];

  const completedCount = steps.filter((s) => s.completed).length;
  const progressPercent = Math.round((completedCount / steps.length) * 100);

  return (
    <>
      <AWSConnectionWizard
        isOpen={isWizardOpen}
        onClose={() => setIsWizardOpen(false)}
        onConnectionSaved={() => {
          setIsWizardOpen(false);
          onRefresh();
        }}
      />

      <div className="rounded-2xl border border-indigo-500/20 bg-gradient-to-r from-[#12121e] via-[#101018] to-[#12121e] p-5 shadow-xl relative overflow-hidden">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-500/10 border border-indigo-500/25 text-indigo-400">
              <Sparkles size={18} />
            </span>
            <div>
              <h3 className="text-sm font-bold text-white">Getting Started with CloudPulse</h3>
              <p className="text-xs text-zinc-400 mt-0.5">
                Complete setup to unlock real-time infrastructure discovery & AI cost optimization.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <span className="text-xs font-mono font-bold text-indigo-400">{progressPercent}%</span>
              <div className="h-2 w-20 rounded-full bg-white/10 overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-indigo-500 to-emerald-400 transition-all duration-500"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>
            <button
              onClick={() => setDismissed(true)}
              className="text-zinc-500 hover:text-zinc-300 p-1"
            >
              <X size={15} />
            </button>
          </div>
        </div>

        {/* Step items */}
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((step) => (
            <div
              key={step.id}
              className={`rounded-xl border p-3.5 transition-all flex flex-col justify-between ${
                step.completed
                  ? "border-emerald-500/20 bg-emerald-950/10"
                  : step.current
                  ? "border-indigo-500/40 bg-indigo-950/20 shadow-md"
                  : "border-white/5 bg-white/[0.02] opacity-60"
              }`}
            >
              <div>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono font-bold uppercase tracking-wider text-zinc-500">
                    Step {step.id}
                  </span>
                  {step.icon}
                </div>
                <h4 className="text-xs font-semibold text-white mt-1.5">{step.title}</h4>
                <p className="text-[11px] text-zinc-400 mt-0.5 leading-snug">{step.desc}</p>
              </div>

              {step.action && <div className="mt-3">{step.action}</div>}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
