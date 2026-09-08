"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { fetchDashboardData, resolveAlert, updateServerStatus, terminateServer } from "./supabase";
import type { DashboardData, Server } from "./types";

interface DashboardContextType {
  data: DashboardData | null;
  loading: boolean;
  isLive: boolean;
  setIsLive: (val: boolean) => void;
  alertFeedOpen: boolean;
  setAlertFeedOpen: (val: boolean) => void;
  loadData: (force?: boolean) => Promise<void>;
  addServerToState: (newServer: Server) => void;
  handleDismissAlert: (alertId: string) => Promise<void>;
  handleServerAction: (serverId: string, action: "optimize" | "terminate", userId?: string) => Promise<boolean>;
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isLive, setIsLive] = useState(true);
  const [alertFeedOpen, setAlertFeedOpen] = useState(false);

  const loadData = useCallback(
    async (force = false) => {
      if (!force && !isLive && data) return;
      try {
        const result = await fetchDashboardData();
        setData(result);
      } catch (err) {
        console.warn("Could not connect to backend server (http://localhost:8000):", err);
      } finally {
        setLoading(false);
      }
    },
    [isLive, data]
  );

  const addServerToState = useCallback((newServer: Server) => {
    setData((prev) => {
      // If there's no data yet (backend is down/loading), create a minimal shell
      // so the new server is visible immediately in the fleet inventory.
      if (!prev) {
        return {
          servers: [newServer],
          metrics: {},
          active_alerts: [],
          summary: {
            total_nodes: 1,
            active_nodes: newServer.status === 'active' ? 1 : 0,
            warning_nodes: newServer.status === 'warning' ? 1 : 0,
            critical_nodes: newServer.status === 'critical' ? 1 : 0,
            idle_nodes: newServer.status === 'idle' ? 1 : 0,
            active_alerts_count: 0,
            avg_cpu_load_pct: 0,
            monthly_cost_estimate: 0,
            hourly_cost_estimate: 0,
            aws_discovered_nodes: 0,
            agent_nodes: 1,
          },
          costs: {},
        };
      }
      if (prev.servers.some((s) => s.id === newServer.id)) return prev;
      return {
        ...prev,
        servers: [newServer, ...prev.servers],
        summary: {
          ...prev.summary,
          total_nodes: prev.summary.total_nodes + 1,
          active_nodes:
            newServer.status === "active"
              ? prev.summary.active_nodes + 1
              : prev.summary.active_nodes,
          agent_nodes: (prev.summary.agent_nodes ?? 0) + 1,
        },
      };
    });
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(() => loadData(), 5000); // 5s poll
    return () => clearInterval(interval);
  }, [loadData]);

  const handleDismissAlert = async (alertId: string) => {
    setData((prev) =>
      prev
        ? {
            ...prev,
            active_alerts: prev.active_alerts.filter((a) => a.id !== alertId),
            summary: {
              ...prev.summary,
              active_alerts_count: Math.max(0, prev.summary.active_alerts_count - 1),
            },
          }
        : prev
    );
    try {
      await resolveAlert(alertId);
    } catch (err) {
      console.error("Failed to dismiss alert on backend:", err);
    }
    loadData(true);
  };

  const handleServerAction = async (serverId: string, action: "optimize" | "terminate", userId?: string): Promise<boolean> => {
    if (action === "optimize") {
      setData((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          servers: prev.servers.map((s) => (s.id === serverId ? { ...s, status: "active" } : s)),
        };
      });
      try {
        await updateServerStatus(serverId, "active", userId);
      } catch (err) {
        console.error("Failed to update server status on backend:", err);
      }
      loadData(true);
      return true;
    } else if (action === "terminate") {
      // Optimistically remove server from global context state
      setData((prev) => {
        if (!prev) return prev;
        const targetServer = prev.servers.find((s) => s.id === serverId);
        const filteredServers = prev.servers.filter((s) => s.id !== serverId);
        const isTargetActive = targetServer?.status === "active";
        return {
          ...prev,
          servers: filteredServers,
          summary: {
            ...prev.summary,
            total_nodes: Math.max(0, prev.summary.total_nodes - 1),
            active_nodes: isTargetActive ? Math.max(0, prev.summary.active_nodes - 1) : prev.summary.active_nodes,
          },
        };
      });
      try {
        const res = await terminateServer(serverId, userId);
        loadData(true);
        return res.success;
      } catch (err) {
        console.error("Failed to terminate server:", err);
        loadData(true);
        return false;
      }
    }
    return false;
  };

  return (
    <DashboardContext.Provider
      value={{
        data,
        loading,
        isLive,
        setIsLive,
        alertFeedOpen,
        setAlertFeedOpen,
        loadData,
        addServerToState,
        handleDismissAlert,
        handleServerAction,
      }}
    >
      {children}
    </DashboardContext.Provider>
  );
}

export function useDashboard() {
  const context = useContext(DashboardContext);
  if (!context) {
    throw new Error("useDashboard must be used within a DashboardProvider");
  }
  return context;
}
