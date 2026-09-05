"use client";

import React, { useState, useEffect } from "react";
import {
  Sliders,
  BellRing,
  Plus,
  Trash2,
  Send,
  CheckCircle2,
  XCircle,
  Clock,
  Zap,
  Webhook,
  Mail,
  MessageSquare,
  ShieldAlert,
  AlertTriangle,
  Sparkles,
  RefreshCw,
  Check,
} from "lucide-react";
import {
  fetchAlertRules,
  saveAlertRule,
  deleteAlertRule,
  fetchNotificationChannels,
  saveNotificationChannel,
  deleteNotificationChannel,
  testNotificationChannel,
  fetchNotificationLogs,
} from "@/lib/supabase";
import type { AlertRule, NotificationChannel, NotificationLog } from "@/lib/types";

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export default function AlertRulesPage() {
  const [activeTab, setActiveTab] = useState<"rules" | "channels" | "logs">("rules");
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [logs, setLogs] = useState<NotificationLog[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [testingChannelId, setTestingChannelId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; success: boolean; message: string } | null>(null);

  // Modals state
  const [showRuleModal, setShowRuleModal] = useState<boolean>(false);
  const [showChannelModal, setShowChannelModal] = useState<boolean>(false);

  // New Rule Form
  const [ruleName, setRuleName] = useState<string>("");
  const [ruleType, setRuleType] = useState<AlertRule["rule_type"]>("CPU_ANOMALY");
  const [ruleThreshold, setRuleThreshold] = useState<number>(85);
  const [ruleSeverity, setRuleSeverity] = useState<"info" | "warning" | "critical">("warning");
  const [ruleCooldown, setRuleCooldown] = useState<number>(15);
  const [ruleChannels, setRuleChannels] = useState<string[]>(["webhook"]);

  // New Channel Form
  const [channelName, setChannelName] = useState<string>("");
  const [channelType, setChannelType] = useState<"webhook" | "discord" | "slack" | "email">("discord");
  const [channelUrl, setChannelUrl] = useState<string>("");
  const [channelEmail, setChannelEmail] = useState<string>("");
  const [channelSecret, setChannelSecret] = useState<string>("");

  const loadAll = async () => {
    setIsLoading(true);
    try {
      const [r, c, l] = await Promise.all([
        fetchAlertRules(),
        fetchNotificationChannels(),
        fetchNotificationLogs(),
      ]);
      setRules(r);
      setChannels(c);
      setLogs(l);
    } catch (err) {
      console.error("Failed to load alert config", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const handleToggleRule = async (rule: AlertRule) => {
    try {
      const updated = await saveAlertRule({
        ...rule,
        enabled: !rule.enabled,
      });
      if (updated) {
        setRules((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
      }
    } catch (err) {
      console.error("Failed to toggle rule", err);
    }
  };

  const handleDeleteRule = async (ruleId: string) => {
    try {
      const ok = await deleteAlertRule(ruleId);
      if (ok) {
        setRules((prev) => prev.filter((r) => r.id !== ruleId));
      }
    } catch (err) {
      console.error("Failed to delete rule", err);
    }
  };

  const handleCreateRule = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ruleName.trim()) return;

    let config: Record<string, any> = {};
    if (ruleType === "CPU_ANOMALY" || ruleType === "RAM_ANOMALY" || ruleType === "NETWORK_ANOMALY") {
      config = { threshold: Number(ruleThreshold) };
    } else if (ruleType === "SAVINGS_THRESHOLD") {
      config = { savings_min: Number(ruleThreshold) };
    }

    try {
      const saved = await saveAlertRule({
        name: ruleName.trim(),
        rule_type: ruleType,
        condition_config: config,
        severity: ruleSeverity,
        cooldown_minutes: Number(ruleCooldown),
        channels: ruleChannels,
        enabled: true,
      });

      if (saved) {
        setRules((prev) => [saved, ...prev]);
        setShowRuleModal(false);
        setRuleName("");
        setRuleThreshold(85);
      }
    } catch (err) {
      console.error("Failed to create rule", err);
    }
  };

  const handleCreateChannel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!channelName.trim()) return;

    const config: Record<string, any> = {};
    if (channelType === "email") {
      config.email = channelEmail.trim();
    } else {
      config.url = channelUrl.trim();
      if (channelSecret.trim()) config.secret = channelSecret.trim();
    }

    try {
      const saved = await saveNotificationChannel({
        name: channelName.trim(),
        channel_type: channelType,
        config,
        enabled: true,
      });

      if (saved) {
        setChannels((prev) => [saved, ...prev]);
        setShowChannelModal(false);
        setChannelName("");
        setChannelUrl("");
        setChannelEmail("");
      }
    } catch (err) {
      console.error("Failed to create channel", err);
    }
  };

  const handleDeleteChannel = async (channelId: string) => {
    try {
      const ok = await deleteNotificationChannel(channelId);
      if (ok) {
        setChannels((prev) => prev.filter((c) => c.id !== channelId));
      }
    } catch (err) {
      console.error("Failed to delete channel", err);
    }
  };

  const handleTestChannel = async (channelId: string) => {
    setTestingChannelId(channelId);
    setTestResult(null);
    try {
      const res = await testNotificationChannel(channelId);
      if (res && res.status === "sent") {
        setTestResult({ id: channelId, success: true, message: "Test notification dispatched successfully!" });
      } else {
        setTestResult({ id: channelId, success: false, message: res?.error_message || "Delivery failed" });
      }
      // Refresh logs
      const updatedLogs = await fetchNotificationLogs();
      setLogs(updatedLogs);
    } catch (err: any) {
      setTestResult({ id: channelId, success: false, message: err.message || "Failed to test channel" });
    } finally {
      setTestingChannelId(null);
    }
  };

  return (
    <div className="space-y-6 pb-12">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Sliders size={16} />
            </span>
            <h1 className="text-2xl font-bold tracking-tight text-white">Alert Rules & Notification Pipeline</h1>
          </div>
          <p className="mt-1 text-sm text-zinc-400">
            Define metric anomaly thresholds, configure Webhook / Discord / Slack channels, and audit delivery logs.
          </p>
        </div>

        <button
          onClick={loadAll}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-white/10 bg-[#16161a] px-3.5 py-2 text-xs font-medium text-zinc-300 transition-colors hover:bg-white/5 hover:text-white"
        >
          <RefreshCw size={13} className={cn(isLoading && "animate-spin text-indigo-400")} />
          Refresh
        </button>
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-white/10">
        <button
          onClick={() => setActiveTab("rules")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-semibold transition-all",
            activeTab === "rules"
              ? "border-indigo-500 text-white"
              : "border-transparent text-zinc-400 hover:text-zinc-200"
          )}
        >
          <BellRing size={14} />
          Alert Rules ({rules.length})
        </button>
        <button
          onClick={() => setActiveTab("channels")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-semibold transition-all",
            activeTab === "channels"
              ? "border-indigo-500 text-white"
              : "border-transparent text-zinc-400 hover:text-zinc-200"
          )}
        >
          <Webhook size={14} />
          Notification Channels ({channels.length})
        </button>
        <button
          onClick={() => setActiveTab("logs")}
          className={cn(
            "flex items-center gap-2 border-b-2 px-4 py-2.5 text-xs font-semibold transition-all",
            activeTab === "logs"
              ? "border-indigo-500 text-white"
              : "border-transparent text-zinc-400 hover:text-zinc-200"
          )}
        >
          <Clock size={14} />
          Delivery Audit Logs ({logs.length})
        </button>
      </div>

      {/* Tab Content: Rules */}
      {activeTab === "rules" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-400">
              Rules are evaluated continuously upon metric telemetry ingestion and cost syncs.
            </p>
            <button
              onClick={() => setShowRuleModal(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-lg transition-all hover:bg-indigo-500"
            >
              <Plus size={14} />
              Create Alert Rule
            </button>
          </div>

          <div className="overflow-hidden rounded-xl border border-white/5 bg-[#0e0e12] shadow-xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-white/5 bg-white/[0.02] text-[11px] font-semibold text-zinc-400">
                  <tr>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Rule Name</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Condition</th>
                    <th className="px-4 py-3">Severity</th>
                    <th className="px-4 py-3">Cooldown</th>
                    <th className="px-4 py-3">Channels</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {rules.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-4 py-8 text-center text-zinc-500">
                        No alert rules created yet. Click &quot;Create Alert Rule&quot; above to set one up.
                      </td>
                    </tr>
                  ) : (
                    rules.map((rule) => {
                      const sevColor =
                        rule.severity === "critical"
                          ? "text-red-400 bg-red-500/10 border-red-500/20"
                          : rule.severity === "warning"
                          ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
                          : "text-blue-400 bg-blue-500/10 border-blue-500/20";

                      let conditionStr = "Custom conditions";
                      if (rule.condition_config?.threshold !== undefined) {
                        conditionStr = `Value ≥ ${rule.condition_config.threshold}${
                          rule.rule_type === "NETWORK_ANOMALY" ? " MB" : "%"
                        }`;
                      } else if (rule.condition_config?.savings_min !== undefined) {
                        conditionStr = `Fleet Savings ≥ $${rule.condition_config.savings_min}/mo`;
                      } else if (rule.rule_type === "IDLE_RESOURCE") {
                        conditionStr = "CPU < 5% & RAM < 15%";
                      } else if (rule.rule_type === "BUDGET_SPIKE") {
                        conditionStr = "Spend > 2× baseline";
                      }

                      return (
                        <tr key={rule.id} className="transition-colors hover:bg-white/[0.02]">
                          <td className="px-4 py-3">
                            <button
                              onClick={() => handleToggleRule(rule)}
                              className={cn(
                                "relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none",
                                rule.enabled ? "bg-indigo-600" : "bg-zinc-700"
                              )}
                            >
                              <span
                                className={cn(
                                  "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
                                  rule.enabled ? "translate-x-4" : "translate-x-0"
                                )}
                              />
                            </button>
                          </td>
                          <td className="px-4 py-3 font-semibold text-white">{rule.name}</td>
                          <td className="px-4 py-3 font-mono text-[11px] text-zinc-400">{rule.rule_type}</td>
                          <td className="px-4 py-3 text-zinc-300">{conditionStr}</td>
                          <td className="px-4 py-3">
                            <span className={cn("rounded border px-2 py-0.5 text-[10px] font-bold uppercase", sevColor)}>
                              {rule.severity}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-zinc-400">{rule.cooldown_minutes}m</td>
                          <td className="px-4 py-3">
                            <div className="flex gap-1">
                              {rule.channels?.map((ch, idx) => (
                                <span
                                  key={idx}
                                  className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-mono text-zinc-300"
                                >
                                  {ch}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              onClick={() => handleDeleteRule(rule.id)}
                              className="rounded p-1.5 text-zinc-500 transition-colors hover:bg-red-500/10 hover:text-red-400"
                            >
                              <Trash2 size={14} />
                            </button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab Content: Notification Channels */}
      {activeTab === "channels" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-400">
              Configure Webhooks, Discord, Slack, or Email recipients to receive notifications with cooldown suppression.
            </p>
            <button
              onClick={() => setShowChannelModal(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white shadow-lg transition-all hover:bg-indigo-500"
            >
              <Plus size={14} />
              Add Channel
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {channels.length === 0 ? (
              <div className="col-span-full rounded-xl border border-white/5 bg-[#0e0e12] p-8 text-center text-xs text-zinc-500">
                No notification channels configured. Click &quot;Add Channel&quot; to set up Discord, Slack, Webhook, or Email.
              </div>
            ) : (
              channels.map((ch) => {
                const icon =
                  ch.channel_type === "discord" ? (
                    <MessageSquare size={16} className="text-indigo-400" />
                  ) : ch.channel_type === "slack" ? (
                    <Zap size={16} className="text-amber-400" />
                  ) : ch.channel_type === "email" ? (
                    <Mail size={16} className="text-emerald-400" />
                  ) : (
                    <Webhook size={16} className="text-blue-400" />
                  );

                const isTesting = testingChannelId === ch.id;
                const result = testResult?.id === ch.id ? testResult : null;

                return (
                  <div
                    key={ch.id}
                    className="flex flex-col justify-between rounded-xl border border-white/10 bg-[#0e0e12] p-4 shadow-xl"
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/5 border border-white/10">
                            {icon}
                          </span>
                          <div>
                            <h4 className="text-sm font-semibold text-white">{ch.name}</h4>
                            <span className="font-mono text-[10px] uppercase text-zinc-400">{ch.channel_type}</span>
                          </div>
                        </div>

                        <button
                          onClick={() => handleDeleteChannel(ch.id)}
                          className="rounded p-1 text-zinc-500 hover:bg-red-500/10 hover:text-red-400"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>

                      <div className="mt-3 rounded-lg border border-white/5 bg-[#14141a] p-2 text-[11px] text-zinc-400">
                        <span className="text-zinc-500">Target: </span>
                        <span className="font-mono text-zinc-300 break-all">
                          {ch.config?.url || ch.config?.email || "Configured"}
                        </span>
                      </div>
                    </div>

                    <div className="mt-4 pt-3 border-t border-white/5">
                      {result && (
                        <div
                          className={cn(
                            "mb-2 rounded-md p-2 text-[11px]",
                            result.success ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20" : "bg-red-500/10 text-red-300 border border-red-500/20"
                          )}
                        >
                          {result.message}
                        </div>
                      )}

                      <button
                        onClick={() => handleTestChannel(ch.id)}
                        disabled={isTesting}
                        className="w-full inline-flex items-center justify-center gap-1.5 rounded-lg border border-white/10 bg-white/5 py-1.5 text-xs font-semibold text-zinc-200 hover:bg-white/10 disabled:opacity-50"
                      >
                        <Send size={12} className={cn(isTesting && "animate-spin")} />
                        {isTesting ? "Sending Test..." : "Send Test Notification"}
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Tab Content: Notification Audit Logs */}
      {activeTab === "logs" && (
        <div className="space-y-4">
          <div className="overflow-hidden rounded-xl border border-white/5 bg-[#0e0e12] shadow-xl">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-white/5 bg-white/[0.02] text-[11px] font-semibold text-zinc-400">
                  <tr>
                    <th className="px-4 py-3">Timestamp</th>
                    <th className="px-4 py-3">Channel</th>
                    <th className="px-4 py-3">Severity</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Recipient Target</th>
                    <th className="px-4 py-3">Details / Error</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {logs.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-4 py-8 text-center text-zinc-500">
                        No notification delivery logs recorded yet.
                      </td>
                    </tr>
                  ) : (
                    logs.map((log) => {
                      const statusBadge =
                        log.status === "sent"
                          ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                          : log.status === "cooldown_skipped"
                          ? "text-amber-400 bg-amber-500/10 border-amber-500/20"
                          : "text-red-400 bg-red-500/10 border-red-500/20";

                      return (
                        <tr key={log.id} className="transition-colors hover:bg-white/[0.02]">
                          <td className="px-4 py-3 text-zinc-400">
                            {log.created_at ? new Date(log.created_at).toLocaleString([], { dateStyle: "short", timeStyle: "short" }) : "—"}
                          </td>
                          <td className="px-4 py-3 font-mono uppercase text-zinc-300">{log.channel_type}</td>
                          <td className="px-4 py-3">
                            <span className="rounded bg-white/5 px-2 py-0.5 text-[10px] uppercase font-bold text-zinc-300">
                              {log.severity}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={cn("rounded border px-2 py-0.5 text-[10px] font-semibold capitalize", statusBadge)}>
                              {log.status.replace("_", " ")}
                            </span>
                          </td>
                          <td className="px-4 py-3 font-mono text-[11px] text-zinc-400 max-w-xs truncate">
                            {log.recipient_target || "—"}
                          </td>
                          <td className="px-4 py-3 text-zinc-400 max-w-sm truncate">
                            {log.error_message || (log.payload?.title ? log.payload.title : "OK")}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Create Alert Rule Modal */}
      {showRuleModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#111116] p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white">Create Alert Rule</h3>
            <p className="mt-1 text-xs text-zinc-400">
              Configure trigger thresholds, severity levels, and cooldown intervals.
            </p>

            <form onSubmit={handleCreateRule} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-300">Rule Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Production CPU Saturation"
                  value={ruleName}
                  onChange={(e) => setRuleName(e.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-300">Rule Type</label>
                  <select
                    value={ruleType}
                    onChange={(e) => setRuleType(e.target.value as any)}
                    className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="CPU_ANOMALY">CPU Anomaly</option>
                    <option value="RAM_ANOMALY">RAM Anomaly</option>
                    <option value="NETWORK_ANOMALY">Network Anomaly</option>
                    <option value="IDLE_RESOURCE">Idle Resource</option>
                    <option value="BUDGET_SPIKE">Budget Spike</option>
                    <option value="SAVINGS_THRESHOLD">Savings Threshold</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300">
                    {ruleType === "SAVINGS_THRESHOLD" ? "Min Savings ($/mo)" : "Threshold Value"}
                  </label>
                  <input
                    type="number"
                    value={ruleThreshold}
                    onChange={(e) => setRuleThreshold(Number(e.target.value))}
                    className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-300">Severity</label>
                  <select
                    value={ruleSeverity}
                    onChange={(e) => setRuleSeverity(e.target.value as any)}
                    className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  >
                    <option value="critical">Critical</option>
                    <option value="warning">Warning</option>
                    <option value="info">Info</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300">Cooldown (Minutes)</label>
                  <input
                    type="number"
                    min={1}
                    max={1440}
                    value={ruleCooldown}
                    onChange={(e) => setRuleCooldown(Number(e.target.value))}
                    className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300">Target Channels</label>
                <div className="mt-2 flex flex-wrap gap-2">
                  {["webhook", "discord", "slack", "email"].map((ch) => {
                    const isSelected = ruleChannels.includes(ch);
                    return (
                      <button
                        type="button"
                        key={ch}
                        onClick={() => {
                          if (isSelected) {
                            if (ruleChannels.length > 1) {
                              setRuleChannels(ruleChannels.filter((c) => c !== ch));
                            }
                          } else {
                            setRuleChannels([...ruleChannels, ch]);
                          }
                        }}
                        className={cn(
                          "rounded-lg border px-3 py-1 text-xs font-medium capitalize transition-all",
                          isSelected
                            ? "border-indigo-500/50 bg-indigo-500/20 text-indigo-300"
                            : "border-white/10 bg-white/5 text-zinc-400"
                        )}
                      >
                        {ch}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="mt-6 flex justify-end gap-2.5 border-t border-white/10 pt-4">
                <button
                  type="button"
                  onClick={() => setShowRuleModal(false)}
                  className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs font-medium text-zinc-300 hover:bg-white/10"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
                >
                  Save Rule
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add Notification Channel Modal */}
      {showChannelModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#111116] p-6 shadow-2xl">
            <h3 className="text-base font-bold text-white">Add Notification Channel</h3>
            <p className="mt-1 text-xs text-zinc-400">
              Integrate with webhooks, Discord, Slack, or email notifications.
            </p>

            <form onSubmit={handleCreateChannel} className="mt-4 space-y-4">
              <div>
                <label className="block text-xs font-medium text-zinc-300">Channel Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. SRE Team Discord"
                  value={channelName}
                  onChange={(e) => setChannelName(e.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-300">Channel Type</label>
                <select
                  value={channelType}
                  onChange={(e) => setChannelType(e.target.value as any)}
                  className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                >
                  <option value="discord">Discord Webhook</option>
                  <option value="slack">Slack Incoming Webhook</option>
                  <option value="webhook">Generic HTTP Webhook</option>
                  <option value="email">Email Alert</option>
                </select>
              </div>

              {channelType === "email" ? (
                <div>
                  <label className="block text-xs font-medium text-zinc-300">Recipient Email</label>
                  <input
                    type="email"
                    required
                    placeholder="sre-alerts@company.com"
                    value={channelEmail}
                    onChange={(e) => setChannelEmail(e.target.value)}
                    className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                  />
                </div>
              ) : (
                <>
                  <div>
                    <label className="block text-xs font-medium text-zinc-300">Webhook URL</label>
                    <input
                      type="url"
                      required
                      placeholder="https://discord.com/api/webhooks/... or https://hooks.slack.com/..."
                      value={channelUrl}
                      onChange={(e) => setChannelUrl(e.target.value)}
                      className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                    />
                  </div>

                  {channelType === "webhook" && (
                    <div>
                      <label className="block text-xs font-medium text-zinc-300">HMAC Secret (Optional)</label>
                      <input
                        type="password"
                        placeholder="Shared secret for X-CloudPulse-Signature header verification"
                        value={channelSecret}
                        onChange={(e) => setChannelSecret(e.target.value)}
                        className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                      />
                    </div>
                  )}
                </>
              )}

              <div className="mt-6 flex justify-end gap-2.5 border-t border-white/10 pt-4">
                <button
                  type="button"
                  onClick={() => setShowChannelModal(false)}
                  className="rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs font-medium text-zinc-300 hover:bg-white/10"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
                >
                  Save Channel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
