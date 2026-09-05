"use client";

import React, { useState } from "react";
import { Menu, RefreshCw, Bell, LogOut, Cloud } from "lucide-react";
import { useDashboard } from "@/lib/DashboardContext";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthContext";
import { triggerResourceDiscovery } from "@/lib/supabase";
import AWSAccountSelector from "./AWSAccountSelector";
import OrgSwitcher from "./OrgSwitcher";

interface TopbarProps {
  setSidebarOpen: (val: boolean) => void;
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export default function Topbar({ setSidebarOpen }: TopbarProps) {
  const { data, loading, isLive, setIsLive, alertFeedOpen, setAlertFeedOpen, loadData } = useDashboard();
  const { user, signOut } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const summary = data?.summary;
  const [discovering, setDiscovering] = useState(false);
  const [discMsg, setDiscMsg] = useState<string | null>(null);

  const handleDiscover = async () => {
    setDiscovering(true);
    setDiscMsg(null);
    try {
      const res = await triggerResourceDiscovery();
      setDiscMsg(`Discovered ${res.discovered_count} EC2 instances`);
      await loadData();
    } catch (err: any) {
      setDiscMsg(err.message || "Discovery failed");
    } finally {
      setDiscovering(false);
      setTimeout(() => setDiscMsg(null), 4000);
    }
  };

  const handleSignOut = async () => {
    await signOut();
    router.replace("/login");
  };

  let title = "Dashboard";
  if (pathname === "/servers") {
    title = "Fleet Management";
  } else if (pathname === "/cost-analytics") {
    title = "Cost Analytics";
  } else if (pathname === "/incidents") {
    title = "Incident Center";
  } else if (pathname === "/alert-rules") {
    title = "Alert Rules & Channels";
  } else if (pathname === "/optimization") {
    title = "Cost Optimization";
  }

  const nodesCount = summary?.total_nodes ?? 1;
  const subtitle = `${nodesCount} ${nodesCount === 1 ? "NODE" : "NODES"} MONITORED`;

  return (
    <header
      className="sticky top-0 z-30 flex-shrink-0"
      style={{
        background: "#121212",
        borderBottom: "1px solid rgba(244,240,230,0.06)",
      }}
    >
      <div className="flex items-center justify-between px-6 py-4 w-full">
        {/* Left Group (Contextual Page Info) */}
        <div className="flex items-center gap-4">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden text-paper/40 hover:text-paper transition-colors"
          >
            <Menu size={20} />
          </button>
          <div className="flex flex-col">
            <h2 className="text-base md:text-lg font-bold text-white font-heading tracking-tight leading-none">
              {title}
            </h2>
            <p
              className="text-[9px] font-mono font-medium tracking-[0.2em] uppercase leading-none mt-1.5 text-paper/30"
            >
              {subtitle}
            </p>
          </div>
        </div>

        {/* Right Group (Controls) */}
        <div className="flex items-center gap-3">
            {/* Multi-Tenant Organization Switcher */}
            <OrgSwitcher />

            {/* Multi-Tenant AWS Account Selector */}
            <AWSAccountSelector
              onAccountChanged={() => {
                loadData();
              }}
            />

            {/* Status Indicator (Pill) */}
            <button
              onClick={() => setIsLive(!isLive)}
              className="flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[10px] font-mono font-bold uppercase tracking-wider transition-all border border-white/10 bg-[#1d1d1f]/50 text-[#06b6d4] hover:bg-[#1d1d1f]"
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full bg-[#06b6d4]",
                  isLive && "animate-pulse shadow-[0_0_8px_#06b6d4]"
                )}
              />
              LIVE
            </button>

            {/* Icon 1: Refresh Button */}
            <button
              onClick={() => loadData()}
              className="flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-transparent text-white hover:bg-white/5 transition-all cursor-pointer"
              title="Refresh Data"
            >
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
            </button>

            {/* Icon 2: Alert notification button */}
            <button
              onClick={() => setAlertFeedOpen(!alertFeedOpen)}
              className="relative flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-transparent text-white hover:bg-white/5 transition-all cursor-pointer"
              title="Toggle Alert Feed"
            >
              <Bell size={13} />
              {/* Alert Badge */}
              <span
                className="absolute -top-1 -right-1 flex h-[16px] min-w-[16px] items-center justify-center rounded-full text-[9px] font-bold text-white bg-[#e8462c] shadow-[0_0_8px_rgba(232,70,44,0.6)] px-1"
              >
                {summary?.active_alerts_count ?? 605}
              </span>
            </button>

            {/* Signed-in user + logout */}
            {user && (
              <div className="hidden sm:flex items-center gap-2 pl-1 border-l border-white/10 ml-1">
                <span
                  className="max-w-[140px] truncate text-[11px] font-medium text-paper/60"
                  title={user.email ?? ""}
                >
                  {user.email}
                </span>
                <button
                  onClick={handleSignOut}
                  className="flex h-8 items-center gap-1.5 rounded-full border border-white/10 bg-transparent px-2.5 text-[11px] font-medium text-paper/70 hover:bg-white/5 hover:text-white transition-all cursor-pointer"
                  title="Sign out"
                >
                  <LogOut size={13} />
                </button>
              </div>
            )}
          </div>
        </div>
    </header>
  );
}
