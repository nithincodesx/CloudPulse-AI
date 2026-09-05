"use client";

import React, { useState, useEffect } from "react";
import {
  Cloud,
  ChevronDown,
  Plus,
  Check,
  RefreshCw,
  ExternalLink,
  Trash2,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import {
  fetchAWSConnections,
  syncAWSConnection,
  deleteAWSConnection,
} from "@/lib/supabase";
import type { AWSConnection } from "@/lib/types";
import AWSConnectionWizard from "./AWSConnectionWizard";

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

interface AWSAccountSelectorProps {
  onAccountChanged?: (account: AWSConnection | null) => void;
}

export default function AWSAccountSelector({ onAccountChanged }: AWSAccountSelectorProps) {
  const [connections, setConnections] = useState<AWSConnection[]>([]);
  const [activeConnection, setActiveConnection] = useState<AWSConnection | null>(null);
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [isWizardOpen, setIsWizardOpen] = useState<boolean>(false);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);

  const loadConnections = async () => {
    try {
      const data = await fetchAWSConnections();
      setConnections(data);
      if (data.length > 0 && !activeConnection) {
        // Pick first connected or first connection
        const connected = data.find((c) => c.status === "connected") || data[0];
        setActiveConnection(connected);
        onAccountChanged?.(connected);
      } else if (data.length === 0) {
        setActiveConnection(null);
        onAccountChanged?.(null);
      }
    } catch (err) {
      console.error("Failed to load AWS connections", err);
    }
  };

  useEffect(() => {
    loadConnections();
  }, []);

  const handleSelect = (conn: AWSConnection) => {
    setActiveConnection(conn);
    setIsOpen(false);
    onAccountChanged?.(conn);
  };

  const handleSyncActive = async () => {
    if (!activeConnection) return;
    setIsSyncing(true);
    try {
      await syncAWSConnection(activeConnection.id);
      await loadConnections();
    } catch (err) {
      console.error("Failed to sync connection", err);
    } finally {
      setIsSyncing(false);
    }
  };

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      await deleteAWSConnection(id);
      await loadConnections();
    } catch (err) {
      console.error("Failed to delete connection", err);
    }
  };

  return (
    <>
      <div className="relative">
        <button
          onClick={() => setIsOpen(!isOpen)}
          className="flex items-center gap-2 rounded-xl border border-white/10 bg-[#121218] px-3 py-1.5 text-xs font-medium text-zinc-300 transition-all hover:border-white/20 hover:bg-white/5"
        >
          <Cloud size={14} className={cn(activeConnection?.status === "connected" ? "text-emerald-400" : "text-amber-400")} />
          <span className="max-w-[130px] truncate text-white">
            {activeConnection ? activeConnection.display_name : "No AWS Account"}
          </span>
          {activeConnection?.aws_account_id && (
            <span className="rounded bg-white/5 px-1 py-0.2 text-[10px] font-mono text-zinc-400">
              {activeConnection.aws_account_id.slice(-4)}
            </span>
          )}
          <ChevronDown size={13} className="text-zinc-500" />
        </button>

        {/* Dropdown Menu */}
        {isOpen && (
          <div className="absolute right-0 top-full z-50 mt-2 w-72 rounded-2xl border border-white/10 bg-[#111116] p-2 shadow-2xl backdrop-blur-xl">
            <div className="px-3 py-2 border-b border-white/5">
              <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">Connected AWS Accounts</span>
            </div>

            <div className="mt-1 max-h-56 space-y-1 overflow-y-auto">
              {connections.length === 0 ? (
                <div className="p-3 text-center text-xs text-zinc-500">
                  No AWS accounts connected yet.
                </div>
              ) : (
                connections.map((c) => {
                  const isSelected = activeConnection?.id === c.id;
                  return (
                    <div
                      key={c.id}
                      onClick={() => handleSelect(c)}
                      className={cn(
                        "group flex cursor-pointer items-center justify-between rounded-xl p-2.5 text-xs transition-all",
                        isSelected ? "bg-indigo-600/20 text-white" : "text-zinc-300 hover:bg-white/5 hover:text-white"
                      )}
                    >
                      <div className="flex items-center gap-2 truncate">
                        <span
                          className={cn(
                            "h-2 w-2 rounded-full",
                            c.status === "connected" ? "bg-emerald-400" : "bg-red-400"
                          )}
                        />
                        <div className="truncate">
                          <p className="font-semibold truncate">{c.display_name}</p>
                          <p className="font-mono text-[10px] text-zinc-500">{c.aws_account_id || "Unverified"}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={(e) => handleDelete(c.id, e)}
                          className="rounded p-1 text-zinc-500 hover:bg-red-500/20 hover:text-red-400"
                          title="Disconnect AWS Account"
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            <div className="mt-2 pt-2 border-t border-white/5">
              <button
                onClick={() => {
                  setIsOpen(false);
                  setIsWizardOpen(true);
                }}
                className="w-full flex items-center justify-center gap-1.5 rounded-xl bg-indigo-600/20 py-2 text-xs font-semibold text-indigo-300 hover:bg-indigo-600 hover:text-white transition-all"
              >
                <Plus size={13} />
                Connect New AWS Account
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Connection Wizard Modal */}
      <AWSConnectionWizard
        isOpen={isWizardOpen}
        onClose={() => setIsWizardOpen(false)}
        onConnectionSaved={(conn) => {
          setActiveConnection(conn);
          loadConnections();
          onAccountChanged?.(conn);
        }}
      />
    </>
  );
}
