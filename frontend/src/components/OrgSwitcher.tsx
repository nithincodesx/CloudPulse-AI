"use client";

import React, { useState, useEffect } from "react";
import {
  Building2,
  ChevronDown,
  Plus,
  Check,
  Shield,
  Loader2,
  X,
  Sparkles,
} from "lucide-react";
import { fetchOrganizations, createOrganization } from "@/lib/supabase";
import type { Organization } from "@/lib/types";
import { useAuth } from "@/lib/AuthContext";

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export default function OrgSwitcher() {
  const { user } = useAuth();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newOrgName, setNewOrgName] = useState("");
  const [newOrgPlan, setNewOrgPlan] = useState("free");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const loadOrgs = async () => {
    if (!user) return;
    try {
      const list = await fetchOrganizations(user.id, user.email);
      setOrgs(list);
      if (list.length > 0 && !selectedOrgId) {
        setSelectedOrgId(list[0].id);
        if (typeof window !== "undefined") {
          localStorage.setItem("cloudpulse_active_org", list[0].id);
        }
      }
    } catch (err) {
      console.error("Failed to load organizations", err);
    }
  };

  useEffect(() => {
    loadOrgs();
  }, [user]);

  const activeOrg = orgs.find((o) => o.id === selectedOrgId) || orgs[0];

  const handleSelect = (orgId: string) => {
    setSelectedOrgId(orgId);
    if (typeof window !== "undefined") {
      localStorage.setItem("cloudpulse_active_org", orgId);
    }
    setIsOpen(false);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const created = await createOrganization(newOrgName.trim(), newOrgPlan, user?.id, user?.email);
      if (created) {
        setOrgs((prev) => [...prev, created]);
        setSelectedOrgId(created.id);
        if (typeof window !== "undefined") {
          localStorage.setItem("cloudpulse_active_org", created.id);
        }
        setIsModalOpen(false);
        setNewOrgName("");
      }
    } catch (err: any) {
      setCreateError(err.message || "Failed to create organization");
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      {/* Dropdown button in Topbar */}
      <div className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-medium text-zinc-300 transition-all hover:bg-white/5 border border-white/5 bg-[#121218]"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Building2 size={12} />
          </span>
          <span className="max-w-[130px] truncate font-semibold text-white">
            {activeOrg ? activeOrg.name : "Personal Workspace"}
          </span>
          {activeOrg?.user_role && (
            <span className="rounded bg-white/10 px-1 py-0.5 text-[9px] font-mono text-zinc-400 uppercase">
              {activeOrg.user_role}
            </span>
          )}
          <ChevronDown size={13} className="text-zinc-500" />
        </button>

        {isOpen && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
            <div className="absolute left-0 mt-2 z-50 w-64 rounded-xl border border-white/10 bg-[#121218] p-2 shadow-2xl backdrop-blur-xl">
              <div className="px-2 py-1.5 text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                Switch Workspace
              </div>

              <div className="max-h-56 overflow-y-auto space-y-1">
                {orgs.map((org) => (
                  <button
                    key={org.id}
                    onClick={() => handleSelect(org.id)}
                    className={cn(
                      "flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-left text-xs transition-all",
                      org.id === activeOrg?.id
                        ? "bg-indigo-600/15 text-white border border-indigo-500/30"
                        : "text-zinc-300 hover:bg-white/5"
                    )}
                  >
                    <div className="flex items-center gap-2 truncate">
                      <Building2 size={13} className="text-zinc-400 shrink-0" />
                      <div className="truncate">
                        <p className="font-semibold truncate">{org.name}</p>
                        <p className="text-[10px] text-zinc-500">{org.plan_tier.toUpperCase()} · {org.members_count ?? 1} members</p>
                      </div>
                    </div>
                    {org.id === activeOrg?.id && <Check size={13} className="text-indigo-400 shrink-0" />}
                  </button>
                ))}
              </div>

              <div className="mt-2 border-t border-white/5 pt-1.5">
                <button
                  onClick={() => {
                    setIsOpen(false);
                    setIsModalOpen(true);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-semibold text-indigo-400 hover:bg-indigo-500/10 transition-all"
                >
                  <Plus size={14} />
                  <span>Create Workspace</span>
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Modal: Create Workspace */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#0e0e12] p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                  <Building2 size={15} />
                </span>
                <h3 className="text-sm font-bold text-white">Create New Workspace</h3>
              </div>
              <button
                onClick={() => setIsModalOpen(false)}
                className="rounded-lg p-1 text-zinc-400 hover:bg-white/10 hover:text-white"
              >
                <X size={15} />
              </button>
            </div>

            <form onSubmit={handleCreate} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-300">Workspace / Organization Name</label>
                <input
                  type="text"
                  required
                  value={newOrgName}
                  onChange={(e) => setNewOrgName(e.target.value)}
                  placeholder="e.g. Acme Cloud Fleet"
                  className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300">Plan Tier</label>
                <select
                  value={newOrgPlan}
                  onChange={(e) => setNewOrgPlan(e.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                >
                  <option value="free">Free (Up to 5 AWS Accounts · 30d retention)</option>
                  <option value="starter">Starter (Up to 10 AWS Accounts · 60d retention)</option>
                  <option value="pro">Pro (Up to 25 AWS Accounts · 90d retention)</option>
                  <option value="enterprise">Enterprise (Unlimited AWS Accounts · 365d retention)</option>
                </select>
              </div>

              {createError && (
                <div className="rounded-lg bg-red-950/20 border border-red-500/30 p-2.5 text-xs text-red-300">
                  {createError}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="rounded-lg border border-white/10 px-4 py-2 text-xs font-medium text-zinc-400 hover:bg-white/5"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating || !newOrgName.trim()}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
                >
                  {creating && <Loader2 size={13} className="animate-spin" />}
                  {creating ? "Creating..." : "Create Workspace"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
