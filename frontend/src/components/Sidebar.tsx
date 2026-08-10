"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Server,
  DollarSign,
  Bell,
  BarChart3,
  ChevronDown,
  X,
  Zap,
  Sparkles,
  ShieldCheck,
  TrendingDown,
  Layers,
} from "lucide-react";

function TopoLogo() {
  return (
    <div
      className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#1d1d1f] overflow-hidden border border-white/10"
      style={{
        boxShadow: "0 0 15px rgba(255, 255, 255, 0.08)",
      }}
    >
      <svg
        width="100%"
        height="100%"
        viewBox="0 0 100 100"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        className="opacity-90"
      >
        {/* Concentric-circle topographic lines */}
        <circle cx="50" cy="50" r="10" stroke="rgba(255, 255, 255, 0.85)" strokeWidth="1.5" strokeDasharray="3 2" />
        <circle cx="50" cy="50" r="20" stroke="rgba(255, 255, 255, 0.65)" strokeWidth="1.5" />
        <path d="M 50 15 A 35 35 0 0 0 15 50" stroke="rgba(255, 255, 255, 0.45)" strokeWidth="1.5" />
        <path d="M 50 85 A 35 35 0 0 0 85 50" stroke="rgba(255, 255, 255, 0.45)" strokeWidth="1.5" />
        <circle cx="50" cy="50" r="30" stroke="rgba(128, 128, 128, 0.55)" strokeWidth="1.5" />
        <circle cx="50" cy="50" r="40" stroke="rgba(255, 255, 255, 0.25)" strokeWidth="1.5" />
        {/* Topo style wavy lines */}
        <path d="M 10 30 Q 30 20 50 30 T 90 30" stroke="rgba(128, 128, 128, 0.35)" strokeWidth="1" />
        <path d="M 10 70 Q 30 80 50 70 T 90 70" stroke="rgba(128, 128, 128, 0.35)" strokeWidth="1" />
      </svg>
    </div>
  );
}

interface SidebarProps {
  sidebarOpen: boolean;
  setSidebarOpen: (val: boolean) => void;
}

interface LinkItem {
  label: string;
  href: string;
  icon?: React.ReactNode;
  badge?: string;
  description?: string;
}

interface NavSection {
  title: string;
  icon: React.ReactNode;
  value: "infrastructure" | "cost" | "monitoring";
  links: LinkItem[];
}

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export default function Sidebar({ sidebarOpen, setSidebarOpen }: SidebarProps) {
  const pathname = usePathname();
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    infrastructure: false,
    cost: false,
    monitoring: false,
  });

  const sections: NavSection[] = [
    {
      title: "Infrastructure",
      icon: <Server size={16} />,
      value: "infrastructure",
      links: [
        {
          label: "Fleet Inventory",
          href: "/servers",
          icon: <Layers size={13} />,
          description: "Active compute nodes and specifications",
        },
        {
          label: "Provision Node",
          href: "/servers", // Pointing to servers with detail panel
          icon: <Sparkles size={13} />,
          badge: "New",
          description: "Register new virtual server telemetry",
        },
      ],
    },
    {
      title: "Cost & Run Rates",
      icon: <DollarSign size={16} />,
      value: "cost",
      links: [
        {
          label: "Cost Analytics",
          href: "/cost-analytics",
          icon: <TrendingDown size={13} />,
          description: "Resource billing run-rates & savings",
        },
        {
          label: "Anomaly Budgets",
          href: "/cost-analytics",
          icon: <ShieldCheck size={13} />,
          description: "Heuristics and budget threshold configurations",
        },
      ],
    },
    {
      title: "Monitoring",
      icon: <Bell size={16} />,
      value: "monitoring",
      links: [
        {
          label: "Active Alerts",
          href: "/", // Main alert feed in landing dashboard page
          icon: <Zap size={13} />,
          badge: "Live",
          description: "High CPU & network exception stream",
        },
        {
          label: "Resource Spikes",
          href: "/",
          icon: <BarChart3 size={13} />,
          description: "Time-series resource charts",
        },
      ],
    },
  ];

  // Auto-expand accordion section containing the active path on mount/pathname changes
  useEffect(() => {
    const activeSection = sections.find((sec) =>
      sec.links.some((l) => l.href === pathname && l.label !== "Active Alerts" && l.label !== "Resource Spikes")
    );
    if (activeSection) {
      setOpenSections((prev) => ({
        ...prev,
        [activeSection.value]: true,
      }));
    }
  }, [pathname]);

  const toggleSection = (section: string) => {
    setOpenSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  return (
    <>
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-[260px] transform transition-transform duration-400 lg:static lg:translate-x-0 flex-shrink-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{
          background: "linear-gradient(180deg, rgba(11,11,13,0.96) 0%, rgba(7,7,10,0.98) 100%)",
          backdropFilter: "blur(24px) saturate(160%)",
          borderRight: "1px solid rgba(244,240,230,0.06)",
        }}
      >
        <div className="flex h-full flex-col">
          {/* Brand header */}
          <div
            className="flex items-center justify-between px-6 py-5"
            style={{ borderBottom: "1px solid rgba(244,240,230,0.06)" }}
          >
            <div className="flex items-center gap-3">
              <TopoLogo />
              <div>
                <h1 className="text-[15px] font-bold text-paper tracking-wide font-heading">
                  CloudPulse
                </h1>
                <p
                  className="text-[9px] font-mono font-medium uppercase tracking-[0.3em]"
                  style={{ color: "var(--color-accent-yellow)" }}
                >
                  Enterprise
                </p>
              </div>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              className="lg:hidden text-paper/30 hover:text-paper transition-colors"
            >
              <X size={18} />
            </button>
          </div>

          {/* Navigation Items */}
          <nav className="flex-1 space-y-1.5 px-4 py-6 overflow-y-auto">
            {/* Top-Level Dashboard Link */}
            <Link
              href="/"
              className={cn(
                "group relative flex items-center gap-3 rounded-xl px-4 py-3 text-[13px] font-semibold transition-all duration-200 border border-transparent",
                pathname === "/"
                  ? "bg-accent-yellow/5 text-accent-yellow border-accent-yellow/10"
                  : "text-paper/40 hover:bg-white/[0.02] hover:text-paper"
              )}
            >
              {pathname === "/" && (
                <div
                  className="absolute inset-y-2 left-0 w-[3px] rounded-full"
                  style={{
                    background: "var(--color-accent-yellow)",
                    boxShadow: "0 0 10px rgba(255,230,0,0.5)",
                  }}
                />
              )}
              <span className={pathname === "/" ? "text-accent-yellow" : "text-paper/40 group-hover:text-paper/60"}>
                <Activity size={16} />
              </span>
              <span>Overview Dashboard</span>
            </Link>

            {/* Accordion Sections */}
            {sections.map((sec) => {
              const isOpen = openSections[sec.value];
              // Check if any link in this section is currently active
              const isSectionActive = sec.links.some((l) => l.href === pathname && l.label !== "Active Alerts" && l.label !== "Resource Spikes");

              return (
                <div key={sec.value} className="space-y-1">
                  <button
                    type="button"
                    onClick={() => toggleSection(sec.value)}
                    className={cn(
                      "flex w-full items-center gap-3 rounded-xl px-4 py-3 text-[13px] font-semibold transition-all duration-200",
                      "text-paper/40 hover:bg-white/[0.02] hover:text-paper",
                      isSectionActive && "text-paper"
                    )}
                  >
                    <span className={cn(
                      "transition-colors",
                      isSectionActive ? "text-accent-yellow" : "text-paper/40"
                    )}>
                      {sec.icon}
                    </span>
                    <span className="flex-1 text-left">{sec.title}</span>
                    <ChevronDown
                      size={13}
                      className={cn(
                        "text-paper/30 transition-transform duration-300",
                        isOpen && "rotate-180 text-paper/60"
                      )}
                    />
                  </button>

                  {/* Smooth height expand grid animation */}
                  <div
                    className={cn(
                      "grid transition-[grid-template-rows,opacity] duration-300 ease-out",
                      isOpen ? "grid-rows-[1fr] opacity-100 pb-1.5" : "grid-rows-[0fr] opacity-0 pointer-events-none"
                    )}
                  >
                    <div className="overflow-hidden">
                      <div className="ml-5 border-l border-white/5 pl-4 flex flex-col gap-1 mt-1">
                        {sec.links.map((link) => {
                          const active = pathname === link.href && (link.label === "Fleet Inventory" || link.label === "Provision Node" || link.label === "Cost Analytics" || link.label === "Anomaly Budgets");
                          
                          // Handle special home pages links active highlights
                          const isSpecialActive = (pathname === "/" && (link.label === "Active Alerts" || link.label === "Resource Spikes"));
                          const isHighlighted = active || isSpecialActive;

                          return (
                            <Link
                              key={link.label}
                              href={link.href}
                              className={cn(
                                "group relative flex flex-col gap-0.5 rounded-lg px-3 py-2 transition-all duration-200 border border-transparent",
                                isHighlighted
                                  ? "bg-accent-yellow/5 text-accent-yellow border-accent-yellow/10"
                                  : "text-paper/45 hover:bg-white/[0.015] hover:text-paper/85"
                              )}
                            >
                              {isHighlighted && (
                                <div
                                  className="absolute inset-y-2 left-0 w-[3px] rounded-full"
                                  style={{
                                    background: "var(--color-accent-yellow)",
                                    boxShadow: "0 0 10px rgba(255,230,0,0.5)",
                                  }}
                                />
                              )}
                              <div className="flex items-center gap-2">
                                {link.icon && (
                                  <span className={isHighlighted ? "text-accent-yellow" : "text-paper/30 group-hover:text-paper/50"}>
                                    {link.icon}
                                  </span>
                                )}
                                <span className="text-[12.5px] font-semibold tracking-wide">
                                  {link.label}
                                </span>
                                {link.badge && (
                                  <span className="rounded-full border border-accent-yellow/20 bg-accent-yellow/10 px-1.5 py-0.5 text-[9px] font-bold text-accent-yellow tracking-wider uppercase scale-90 origin-left">
                                    {link.badge}
                                  </span>
                                )}
                              </div>
                              {link.description && (
                                <span className="text-[10px] text-paper/20 font-medium ml-5 group-hover:text-paper/35 transition-colors">
                                  {link.description}
                                </span>
                              )}
                            </Link>
                          );
                        })}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </nav>

          {/* Bottom Card */}
          <div className="p-5" style={{ borderTop: "1px solid rgba(244,240,230,0.06)" }}>
            <div
              className="rounded-xl p-4"
              style={{
                background: "linear-gradient(180deg, rgba(22,22,26,0.8) 0%, rgba(11,11,13,0.9) 100%)",
                border: "1px solid rgba(244,240,230,0.04)",
              }}
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  className="live-dot h-2 w-2 rounded-full bg-accent-green"
                  style={{ boxShadow: "0 0 8px rgba(16,185,129,0.5)" }}
                />
                <span className="text-[11px] font-semibold text-paper/70">System Nominal</span>
              </div>
              <p className="text-[10px] font-mono" style={{ color: "rgba(244,240,230,0.25)" }}>
                v2.4.0-enterprise
              </p>
            </div>
          </div>
        </div>
      </aside>

      {/* Mobile Sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          style={{ background: "rgba(7,7,10,0.7)", backdropFilter: "blur(4px)" }}
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </>
  );
}
