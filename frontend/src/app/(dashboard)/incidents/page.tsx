"use client";

import React, { useState, useEffect, useTransition } from "react";
import {
  Flame,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Sparkles,
  Bot,
  Send,
  MessageSquare,
  ChevronRight,
  RefreshCw,
  Server,
  Activity,
  ArrowUpRight,
  ShieldAlert,
  Search,
  Filter,
  Check,
  Zap,
} from "lucide-react";
import {
  fetchIncidents,
  fetchIncidentDetail,
  updateIncidentStatus,
  addIncidentNote,
  triggerIncidentInvestigation,
} from "@/lib/supabase";
import type { Incident, IncidentTimeline, IncidentNote, AIInvestigation } from "@/lib/types";

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isInvestigating, setIsInvestigating] = useState<boolean>(false);
  const [newNoteText, setNewNoteText] = useState<string>("");
  const [authorName, setAuthorName] = useState<string>("Operator");
  const [resolutionText, setResolutionText] = useState<string>("");
  const [showResolveModal, setShowResolveModal] = useState<boolean>(false);
  const [isPending, startTransition] = useTransition();

  const loadData = async () => {
    setIsLoading(true);
    try {
      const data = await fetchIncidents(statusFilter);
      setIncidents(data);
      if (selectedIncident) {
        const updated = await fetchIncidentDetail(selectedIncident.id);
        if (updated) setSelectedIncident(updated);
      } else if (data.length > 0 && !selectedIncident) {
        // Auto-select first incident on large screens
        const first = await fetchIncidentDetail(data[0].id);
        setSelectedIncident(first);
      }
    } catch (err) {
      console.error("Failed to load incidents", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [statusFilter]);

  const handleSelectIncident = async (inc: Incident) => {
    const detail = await fetchIncidentDetail(inc.id);
    setSelectedIncident(detail || inc);
  };

  const handleStatusTransition = async (newStatus: "open" | "acknowledged" | "resolved", notes?: string) => {
    if (!selectedIncident) return;
    try {
      const updated = await updateIncidentStatus(selectedIncident.id, newStatus, authorName, notes);
      if (updated) {
        setSelectedIncident(updated);
        setIncidents((prev) => prev.map((i) => (i.id === updated.id ? { ...i, status: updated.status } : i)));
        setShowResolveModal(false);
        setResolutionText("");
      }
    } catch (err) {
      console.error("Failed to update status", err);
    }
  };

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedIncident || !newNoteText.trim()) return;
    try {
      const note = await addIncidentNote(selectedIncident.id, authorName, newNoteText.trim());
      if (note) {
        setNewNoteText("");
        const refreshed = await fetchIncidentDetail(selectedIncident.id);
        if (refreshed) setSelectedIncident(refreshed);
      }
    } catch (err) {
      console.error("Failed to add note", err);
    }
  };

  const handleRunInvestigation = async () => {
    if (!selectedIncident) return;
    setIsInvestigating(true);
    try {
      const result = await triggerIncidentInvestigation(selectedIncident.id);
      if (result) {
        const refreshed = await fetchIncidentDetail(selectedIncident.id);
        if (refreshed) setSelectedIncident(refreshed);
      }
    } catch (err) {
      console.error("Failed to run investigation", err);
    } finally {
      setIsInvestigating(false);
    }
  };

  const filteredIncidents = incidents.filter((inc) => {
    const matchesSearch =
      inc.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      inc.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (inc.servers?.server_name || "").toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSearch;
  });

  const openCount = incidents.filter((i) => i.status === "open").length;
  const ackCount = incidents.filter((i) => i.status === "acknowledged").length;
  const resolvedCount = incidents.filter((i) => i.status === "resolved").length;

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <Flame size={16} />
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-white">Incident Center</h1>
          </div>
          <p className="mt-1 text-sm text-zinc-400">
            Real-time infrastructure incident triage, automated multi-channel notifications, and grounded AI investigations.
          </p>
        </div>

        <button
          onClick={loadData}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-[#16161a] px-3.5 py-2 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/5 hover:text-white"
        >
          <RefreshCw size={13} className={cn(isLoading && "animate-spin text-indigo-400")} />
          Refresh Feed
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-white/5 bg-[#0e0e12] p-4 shadow-lg">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-400">Total Recorded</span>
            <Activity size={15} className="text-zinc-500" />
          </div>
          <div className="mt-2 text-2xl font-bold text-white">{incidents.length}</div>
          <div className="mt-1 text-xs text-zinc-500">Across all monitored compute nodes</div>
        </div>

        <div className="rounded-xl border border-red-500/20 bg-[#140b0d] p-4 shadow-lg">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-red-400">Active / Open</span>
            <AlertTriangle size={15} className="text-red-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-red-300">{openCount}</div>
          <div className="mt-1 text-xs text-red-500/80">Requires operator attention</div>
        </div>

        <div className="rounded-xl border border-amber-500/20 bg-[#14120b] p-4 shadow-lg">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-amber-400">In Triage</span>
            <Clock size={15} className="text-amber-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-amber-300">{ackCount}</div>
          <div className="mt-1 text-xs text-amber-500/80">Acknowledged by team</div>
        </div>

        <div className="rounded-xl border border-emerald-500/20 bg-[#0b140e] p-4 shadow-lg">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-emerald-400">Resolved</span>
            <CheckCircle2 size={15} className="text-emerald-400" />
          </div>
          <div className="mt-2 text-2xl font-bold text-emerald-300">{resolvedCount}</div>
          <div className="mt-1 text-xs text-emerald-500/80">Root causes addressed</div>
        </div>
      </div>

      {/* Main Split Layout */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: Incidents List */}
        <div className="space-y-4 lg:col-span-5">
          {/* Controls Bar */}
          <div className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
              <input
                type="text"
                placeholder="Search incidents or nodes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-[#0e0e12] py-2 pl-9 pr-3 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
              />
            </div>

            {/* Status Filter Tabs */}
            <div className="flex rounded-lg border border-white/10 bg-[#0e0e12] p-1 text-xs">
              {(["all", "open", "acknowledged", "resolved"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setStatusFilter(tab)}
                  className={cn(
                    "rounded-md px-2.5 py-1 font-medium capitalize transition-all",
                    statusFilter === tab
                      ? "bg-white/10 text-white shadow-sm"
                      : "text-zinc-400 hover:text-white"
                  )}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>

          {/* Incidents Cards List */}
          <div className="space-y-2.5">
            {isLoading && incidents.length === 0 ? (
              <div className="rounded-xl border border-white/5 bg-[#0e0e12] p-8 text-center text-sm text-zinc-500">
                Loading incidents...
              </div>
            ) : filteredIncidents.length === 0 ? (
              <div className="rounded-xl border border-white/5 bg-[#0e0e12] p-8 text-center text-sm text-zinc-500">
                No incidents match the active filters.
              </div>
            ) : (
              filteredIncidents.map((inc) => {
                const isSelected = selectedIncident?.id === inc.id;
                const sevColor =
                  inc.severity === "critical"
                    ? "text-red-400 border-red-500/20 bg-red-500/10"
                    : inc.severity === "warning"
                    ? "text-amber-400 border-amber-500/20 bg-amber-500/10"
                    : "text-blue-400 border-blue-500/20 bg-blue-500/10";

                const statusBadge =
                  inc.status === "open"
                    ? "bg-red-500/10 text-red-400 border-red-500/30"
                    : inc.status === "acknowledged"
                    ? "bg-amber-500/10 text-amber-400 border-amber-500/30"
                    : "bg-emerald-500/10 text-emerald-400 border-emerald-500/30";

                return (
                  <div
                    key={inc.id}
                    onClick={() => handleSelectIncident(inc)}
                    className={cn(
                      "group relative cursor-pointer rounded-xl border p-4 transition-all hover:bg-white/[0.03]",
                      isSelected
                        ? "border-indigo-500/60 bg-[#121218] shadow-lg ring-1 ring-indigo-500/30"
                        : "border-white/5 bg-[#0e0e12]"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className={cn("rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider", sevColor)}>
                          {inc.severity}
                        </span>
                        <span className={cn("rounded-md border px-2 py-0.5 text-[10px] font-medium capitalize", statusBadge)}>
                          {inc.status}
                        </span>
                      </div>
                      <span className="text-[11px] text-zinc-500">
                        {inc.created_at ? new Date(inc.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}
                      </span>
                    </div>

                    <h3 className="mt-2 text-sm font-semibold text-white group-hover:text-indigo-300">
                      {inc.title}
                    </h3>

                    <p className="mt-1 line-clamp-2 text-xs text-zinc-400">{inc.description}</p>

                    <div className="mt-3 flex items-center justify-between border-t border-white/5 pt-2.5 text-[11px] text-zinc-500">
                      <span className="flex items-center gap-1.5 text-zinc-300">
                        <Server size={12} className="text-zinc-500" />
                        {inc.servers?.server_name || "Server"}
                      </span>
                      <span className="font-mono text-[10px] text-zinc-500">{inc.incident_type}</span>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right Column: Detailed Incident Inspection Pane */}
        <div className="lg:col-span-7">
          {selectedIncident ? (
            <div className="space-y-5 rounded-xl border border-white/10 bg-[#0e0e12] p-6 shadow-2xl">
              {/* Top Banner & Status Action Buttons */}
              <div className="flex flex-col gap-4 border-b border-white/10 pb-5 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        "rounded-md border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider",
                        selectedIncident.severity === "critical"
                          ? "border-red-500/30 bg-red-500/10 text-red-400"
                          : selectedIncident.severity === "warning"
                          ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
                          : "border-blue-500/30 bg-blue-500/10 text-blue-400"
                      )}
                    >
                      {selectedIncident.severity}
                    </span>
                    <span className="font-mono text-xs text-zinc-500">ID: {selectedIncident.id.slice(0, 8)}...</span>
                  </div>
                  <h2 className="mt-2 text-lg font-bold text-white">{selectedIncident.title}</h2>
                  <p className="mt-1 text-xs text-zinc-400">{selectedIncident.description}</p>
                </div>

                {/* Status Transitions */}
                <div className="flex flex-wrap items-center gap-2">
                  {selectedIncident.status === "open" && (
                    <button
                      onClick={() => handleStatusTransition("acknowledged")}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs font-semibold text-amber-300 hover:bg-amber-500/20"
                    >
                      <Clock size={13} />
                      Acknowledge
                    </button>
                  )}

                  {selectedIncident.status !== "resolved" && (
                    <button
                      onClick={() => setShowResolveModal(true)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
                    >
                      <CheckCircle2 size={13} />
                      Resolve Incident
                    </button>
                  )}

                  {selectedIncident.status === "resolved" && (
                    <button
                      onClick={() => handleStatusTransition("open", "Reopened for further investigation")}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-700 bg-white/5 px-3 py-1.5 text-xs font-medium text-zinc-300 hover:bg-white/10"
                    >
                      <RefreshCw size={13} />
                      Reopen
                    </button>
                  )}
                </div>
              </div>

              {/* Server Specs Bar */}
              {selectedIncident.server_details && (
                <div className="grid grid-cols-2 gap-3 rounded-lg border border-white/5 bg-[#14141a] p-3 text-xs sm:grid-cols-4">
                  <div>
                    <span className="text-zinc-500">Resource</span>
                    <p className="font-semibold text-white">{selectedIncident.server_details.server_name || "Node"}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">AWS Instance ID</span>
                    <p className="font-mono text-zinc-300">{selectedIncident.server_details.aws_instance_id || "Agent"}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">Region</span>
                    <p className="text-zinc-300">{selectedIncident.server_details.aws_region || "us-east-1"}</p>
                  </div>
                  <div>
                    <span className="text-zinc-500">Instance Type</span>
                    <p className="text-indigo-300">{selectedIncident.server_details.specifications?.type || "Standard"}</p>
                  </div>
                </div>
              )}

              {/* AI Investigation Block */}
              <div className="rounded-xl border border-indigo-500/20 bg-gradient-to-b from-[#161426] to-[#0f0e1a] p-4 shadow-xl">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-500/20 text-indigo-400">
                      <Bot size={15} />
                    </span>
                    <h4 className="text-sm font-bold text-white">Grounded AI Investigation</h4>
                    <span className="rounded-full bg-indigo-500/10 px-2 py-0.5 text-[10px] font-medium text-indigo-300 border border-indigo-500/30">
                      Strict Deterministic Facts
                    </span>
                  </div>

                  <button
                    onClick={handleRunInvestigation}
                    disabled={isInvestigating}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white transition-all hover:bg-indigo-500 disabled:opacity-50"
                  >
                    <Sparkles size={13} className={cn(isInvestigating && "animate-spin")} />
                    {isInvestigating ? "Analyzing..." : "Investigate with AI"}
                  </button>
                </div>

                {selectedIncident.ai_investigation && Object.keys(selectedIncident.ai_investigation).length > 0 ? (
                  <div className="mt-4 space-y-4 text-xs text-zinc-300">
                    {/* Summary */}
                    <div className="rounded-lg border border-indigo-500/20 bg-indigo-950/20 p-3">
                      <span className="font-semibold text-indigo-300">Executive Summary: </span>
                      <span>{selectedIncident.ai_investigation.summary}</span>
                    </div>

                    {/* Telemetry Explanation & Cost Impact */}
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                        <span className="font-semibold text-zinc-300">Operational Explanation:</span>
                        <p className="mt-1 text-zinc-400">{selectedIncident.ai_investigation.incident_explanation}</p>
                      </div>
                      <div className="rounded-lg border border-white/5 bg-white/[0.02] p-3">
                        <span className="font-semibold text-zinc-300">Cost & Run-Rate Impact:</span>
                        <p className="mt-1 text-zinc-400">{selectedIncident.ai_investigation.cost_impact_explanation}</p>
                      </div>
                    </div>

                    {/* Root Cause Hypotheses */}
                    {selectedIncident.ai_investigation.root_cause_hypotheses?.length > 0 && (
                      <div>
                        <span className="font-semibold text-zinc-300">Root Cause Hypotheses:</span>
                        <ul className="mt-1.5 list-disc space-y-1 pl-4 text-zinc-400">
                          {selectedIncident.ai_investigation.root_cause_hypotheses.map((h, idx) => (
                            <li key={idx}>{h}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Prioritized Action Steps */}
                    {selectedIncident.ai_investigation.prioritized_actions?.length > 0 && (
                      <div>
                        <span className="font-semibold text-zinc-300">Prioritized Remediation Actions:</span>
                        <div className="mt-2 space-y-1.5">
                          {selectedIncident.ai_investigation.prioritized_actions.map((act, idx) => {
                            const pColor =
                              act.priority === "Critical"
                                ? "text-red-400 bg-red-500/10 border-red-500/20"
                                : act.priority === "High"
                                ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
                                : "text-blue-400 bg-blue-500/10 border-blue-500/20";
                            return (
                              <div key={idx} className="flex items-start gap-2.5 rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                                <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold uppercase", pColor)}>
                                  {act.priority}
                                </span>
                                <div className="flex-1">
                                  <p className="font-medium text-white">{act.action}</p>
                                  <p className="text-[11px] text-zinc-400">Rationale: {act.rationale}</p>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="mt-3 text-xs text-zinc-500">
                    No AI investigation performed yet. Click &quot;Investigate with AI&quot; to synthesize telemetry facts and cost impacts.
                  </p>
                )}
              </div>

              {/* Chronological Incident Timeline */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400">Lifecycle Audit Timeline</h4>
                <div className="mt-3 space-y-3">
                  {selectedIncident.timeline && selectedIncident.timeline.length > 0 ? (
                    selectedIncident.timeline.map((item, idx) => (
                      <div key={item.id || idx} className="flex items-start gap-3 text-xs">
                        <div className="relative mt-1 flex h-4 w-4 items-center justify-center rounded-full bg-indigo-500/20 text-indigo-400">
                          <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" />
                        </div>
                        <div className="flex-1 rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                          <div className="flex items-center justify-between">
                            <span className="font-semibold text-zinc-300">
                              [{item.event_type}] <span className="font-normal text-zinc-400">by {item.actor}</span>
                            </span>
                            <span className="text-[10px] text-zinc-500">
                              {new Date(item.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" })}
                            </span>
                          </div>
                          <p className="mt-1 text-zinc-400">{item.message}</p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-zinc-500">No timeline events recorded.</p>
                  )}
                </div>
              </div>

              {/* Operator Notes & Composer */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400">Operator Notes</h4>
                <div className="mt-2 space-y-2">
                  {selectedIncident.notes && selectedIncident.notes.length > 0 ? (
                    selectedIncident.notes.map((note) => (
                      <div key={note.id} className="rounded-lg border border-white/5 bg-[#14141a] p-3 text-xs">
                        <div className="flex items-center justify-between text-zinc-500">
                          <span className="font-medium text-zinc-300">{note.author_name}</span>
                          <span className="text-[10px]">{new Date(note.created_at).toLocaleTimeString()}</span>
                        </div>
                        <p className="mt-1 text-zinc-300">{note.note_text}</p>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-zinc-500">No notes attached to this incident.</p>
                  )}
                </div>

                {/* Note Composer Form */}
                <form onSubmit={handleAddNote} className="mt-3 flex gap-2">
                  <input
                    type="text"
                    placeholder="Add an operational note or hypothesis..."
                    value={newNoteText}
                    onChange={(e) => setNewNoteText(e.target.value)}
                    className="flex-1 rounded-lg border border-white/10 bg-[#16161c] px-3 py-2 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                  />
                  <button
                    type="submit"
                    disabled={!newNoteText.trim()}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-white/10 px-3.5 py-2 text-xs font-semibold text-white transition-all hover:bg-white/20 disabled:opacity-40"
                  >
                    <Send size={12} />
                    Post Note
                  </button>
                </form>
              </div>
            </div>
          ) : (
            <div className="flex h-96 flex-col items-center justify-center rounded-xl border border-white/5 bg-[#0e0e12] p-8 text-center text-zinc-500">
              <ShieldAlert size={36} className="mb-3 text-zinc-600" />
              <p className="text-sm font-medium text-zinc-400">No incident selected</p>
              <p className="mt-1 text-xs">Select an incident from the feed to view its timeline, notes, and AI investigation.</p>
            </div>
          )}
        </div>
      </div>

      {/* Resolve Incident Modal */}
      {showResolveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-[#111116] p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white">Resolve Incident</h3>
            <p className="mt-1 text-xs text-zinc-400">
              Document the root cause and remediation steps before closing out this incident.
            </p>

            <textarea
              rows={4}
              placeholder="Root cause summary (e.g. Cleared stuck worker process, resized memory limit)..."
              value={resolutionText}
              onChange={(e) => setResolutionText(e.target.value)}
              className="mt-4 w-full rounded-xl border border-white/10 bg-[#16161e] p-3 text-xs text-white placeholder-zinc-500 focus:border-emerald-500 focus:outline-none"
            />

            <div className="mt-5 flex justify-end gap-2.5">
              <button
                onClick={() => setShowResolveModal(false)}
                className="rounded-lg border border-white/10 bg-white/5 px-3.5 py-2 text-xs font-medium text-zinc-300 hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                onClick={() => handleStatusTransition("resolved", resolutionText)}
                className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500"
              >
                <Check size={13} />
                Confirm Resolution
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
