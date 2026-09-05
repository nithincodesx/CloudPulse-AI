"use client";

import React, { useState, useEffect } from "react";
import {
  Building2,
  Users,
  Shield,
  Plus,
  Trash2,
  Mail,
  Loader2,
  CheckCircle2,
  BarChart3,
  HardDrive,
  Activity,
  AlertCircle,
} from "lucide-react";
import { useAuth } from "@/lib/AuthContext";
import {
  fetchOrganizations,
  fetchOrgMembers,
  inviteOrgMember,
  updateOrgMemberRole,
  removeOrgMember,
  fetchOrgUsage,
  updateOrganization,
} from "@/lib/supabase";
import type { Organization, OrganizationMember, OrganizationUsage, OrgRole } from "@/lib/types";

export default function WorkspaceSettingsPage() {
  const { user } = useAuth();
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const [activeOrg, setActiveOrg] = useState<Organization | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [usage, setUsage] = useState<OrganizationUsage | null>(null);
  const [loading, setLoading] = useState(true);

  // Invite state
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<OrgRole>("MEMBER");
  const [inviting, setInviting] = useState(false);
  const [inviteMsg, setInviteMsg] = useState<string | null>(null);

  // Edit org state
  const [editName, setEditName] = useState("");
  const [savingOrg, setSavingOrg] = useState(false);

  const loadData = async () => {
    if (!user) return;
    setLoading(true);
    try {
      const orgList = await fetchOrganizations(user.id, user.email);
      setOrgs(orgList);
      const cur = orgList[0] || null;
      setActiveOrg(cur);
      if (cur) {
        setEditName(cur.name);
        const [memList, usageData] = await Promise.all([
          fetchOrgMembers(cur.id),
          fetchOrgUsage(cur.id),
        ]);
        setMembers(memList);
        setUsage(usageData);
      }
    } catch (err) {
      console.error("Failed to load workspace data", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [user]);

  const isOwner = activeOrg?.user_role === "OWNER";
  const isAdminOrOwner = isOwner || activeOrg?.user_role === "ADMIN";

  const handleSaveOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrg || !editName.trim()) return;
    setSavingOrg(true);
    try {
      const updated = await updateOrganization(activeOrg.id, { name: editName.trim() }, user?.id);
      if (updated) {
        setActiveOrg(updated);
        alert("Workspace settings saved.");
      }
    } catch (err: any) {
      alert(err.message || "Failed to save settings");
    } finally {
      setSavingOrg(false);
    }
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeOrg || !inviteEmail.trim()) return;
    setInviting(true);
    setInviteMsg(null);
    try {
      const invited = await inviteOrgMember(
        activeOrg.id,
        inviteEmail.trim(),
        inviteRole,
        user?.id,
        user?.email
      );
      if (invited) {
        setInviteMsg(`Invitation sent to ${inviteEmail}`);
        setInviteEmail("");
        const memList = await fetchOrgMembers(activeOrg.id);
        setMembers(memList);
      }
    } catch (err: any) {
      setInviteMsg(`Failed: ${err.message}`);
    } finally {
      setInviting(false);
    }
  };

  const handleRoleChange = async (memberId: string, newRole: OrgRole) => {
    if (!activeOrg) return;
    try {
      await updateOrgMemberRole(activeOrg.id, memberId, newRole, user?.id, user?.email);
      const memList = await fetchOrgMembers(activeOrg.id);
      setMembers(memList);
    } catch (err: any) {
      alert(err.message || "Failed to update role");
    }
  };

  const handleRemoveMember = async (memberId: string) => {
    if (!activeOrg || !confirm("Are you sure you want to remove this member?")) return;
    try {
      await removeOrgMember(activeOrg.id, memberId, user?.id, user?.email);
      const memList = await fetchOrgMembers(activeOrg.id);
      setMembers(memList);
    } catch (err: any) {
      alert(err.message || "Failed to remove member");
    }
  };

  if (loading) {
    return <div className="p-6 text-paper/50">Loading workspace settings...</div>;
  }

  return (
    <main className="flex-1 p-6 overflow-y-auto space-y-6">
      {/* Header */}
      <div>
        <div className="eyebrow mb-1">Multi-Tenant Management</div>
        <h1 className="text-2xl font-bold text-white font-heading">Workspace & RBAC Settings</h1>
        <p className="text-xs text-zinc-400 mt-1">
          Manage tenant workspace parameters, role-based access control, and subscription usage.
        </p>
      </div>

      {/* Usage & Plan Tier Overview */}
      {usage && (
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-white/10 bg-[#121218] p-4">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Plan Tier</span>
            <span className="text-base font-bold text-indigo-400 mt-1 block uppercase">
              {usage.plan_tier}
            </span>
            <span className="text-[11px] text-zinc-400 mt-1 block">
              {usage.retention_days} days metric retention
            </span>
          </div>

          <div className="rounded-xl border border-white/10 bg-[#121218] p-4">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Connected AWS Accounts</span>
            <span className="text-base font-bold text-white mt-1 block">
              {usage.connected_aws_accounts} / {usage.max_aws_connections}
            </span>
            <span className="text-[11px] text-emerald-400 mt-1 block">
              {usage.max_aws_connections - usage.connected_aws_accounts} available slots
            </span>
          </div>

          <div className="rounded-xl border border-white/10 bg-[#121218] p-4">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Monitored Nodes</span>
            <span className="text-base font-bold text-white mt-1 block">
              {usage.monitored_nodes} Instances
            </span>
            <span className="text-[11px] text-zinc-400 mt-1 block">
              Across all regions & accounts
            </span>
          </div>

          <div className="rounded-xl border border-white/10 bg-[#121218] p-4">
            <span className="text-[10px] uppercase font-bold text-zinc-500 block">Telemetry (Last 30 Days)</span>
            <span className="text-base font-bold text-white mt-1 block">
              {usage.telemetry_metrics_30d.toLocaleString()} points
            </span>
            <span className="text-[11px] text-zinc-400 mt-1 block">
              {usage.telemetry_metrics_24h.toLocaleString()} in last 24h
            </span>
          </div>
        </section>
      )}

      {/* Workspace Profile */}
      <section className="rounded-2xl border border-white/10 bg-[#121218] p-6">
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <Building2 size={16} className="text-indigo-400" />
          Workspace Profile
        </h3>

        {activeOrg && (
          <form onSubmit={handleSaveOrg} className="mt-4 max-w-lg space-y-4">
            <div>
              <label className="block text-xs font-medium text-zinc-400">Workspace Name</label>
              <input
                type="text"
                disabled={!isOwner}
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                className="mt-1 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none disabled:opacity-60"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-zinc-400">Tenant Slug</label>
              <input
                type="text"
                disabled
                value={activeOrg.slug}
                className="mt-1 w-full rounded-lg border border-white/5 bg-black/40 p-2.5 font-mono text-xs text-zinc-500 cursor-not-allowed"
              />
            </div>

            {isOwner && (
              <button
                type="submit"
                disabled={savingOrg}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
              >
                {savingOrg ? "Saving..." : "Save Workspace Profile"}
              </button>
            )}
          </form>
        )}
      </section>

      {/* Member Management & Roles */}
      <section className="rounded-2xl border border-white/10 bg-[#121218] p-6 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <Users size={16} className="text-indigo-400" />
              Members & Role-Based Access Control
            </h3>
            <p className="text-xs text-zinc-400 mt-1">
              Control permissions across OWNER, ADMIN, MEMBER, and VIEWER roles.
            </p>
          </div>
        </div>

        {/* Invite Member form */}
        {isAdminOrOwner && (
          <form onSubmit={handleInvite} className="flex flex-wrap items-end gap-3 rounded-xl border border-white/5 bg-[#16161e] p-4">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs font-medium text-zinc-300">Invite by Email</label>
              <input
                type="email"
                required
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                placeholder="colleague@company.com"
                className="mt-1 w-full rounded-lg border border-white/10 bg-[#0e0e12] p-2 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-zinc-300">Role</label>
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value as OrgRole)}
                className="mt-1 rounded-lg border border-white/10 bg-[#0e0e12] p-2 text-xs text-white focus:border-indigo-500 focus:outline-none"
              >
                <option value="ADMIN">ADMIN (Manage AWS & Resources)</option>
                <option value="MEMBER">MEMBER (View & Investigate)</option>
                <option value="VIEWER">VIEWER (Read-Only)</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={inviting || !inviteEmail.trim()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500 disabled:opacity-50"
            >
              {inviting && <Loader2 size={13} className="animate-spin" />}
              <Plus size={13} />
              Invite Member
            </button>
          </form>
        )}

        {inviteMsg && (
          <p className="text-xs font-mono text-emerald-400">{inviteMsg}</p>
        )}

        {/* Members List */}
        <div className="divide-y divide-white/5 rounded-xl border border-white/10 bg-[#16161e] overflow-hidden">
          {members.map((m) => (
            <div key={m.id} className="flex flex-wrap items-center justify-between gap-4 p-4 text-xs">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-indigo-500/10 text-indigo-400 font-bold">
                  {(m.invited_email || "U")[0].toUpperCase()}
                </div>
                <div>
                  <p className="font-semibold text-white">{m.invited_email || `User ${m.user_id.slice(0, 8)}`}</p>
                  <p className="text-[10px] text-zinc-500 font-mono">Added {new Date(m.created_at || "").toLocaleDateString()}</p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {isOwner && m.role !== "OWNER" ? (
                  <select
                    value={m.role}
                    onChange={(e) => handleRoleChange(m.id, e.target.value as OrgRole)}
                    className="rounded-lg border border-white/10 bg-[#121218] px-2.5 py-1 text-xs text-white focus:outline-none"
                  >
                    <option value="ADMIN">ADMIN</option>
                    <option value="MEMBER">MEMBER</option>
                    <option value="VIEWER">VIEWER</option>
                  </select>
                ) : (
                  <span className="rounded bg-indigo-500/10 border border-indigo-500/20 px-2 py-0.5 text-[10px] font-mono font-bold text-indigo-400 uppercase">
                    {m.role}
                  </span>
                )}

                {isAdminOrOwner && m.role !== "OWNER" && (
                  <button
                    onClick={() => handleRemoveMember(m.id)}
                    className="rounded p-1.5 text-zinc-400 hover:bg-red-500/10 hover:text-red-400 transition-all"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
