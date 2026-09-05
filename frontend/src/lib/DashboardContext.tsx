"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import { fetchDashboardData, resolveAlert, updateServerStatus } from "./supabase";
import type { DashboardData } from "./types";

interface DashboardContextType {
  data: DashboardData | null;
  loading: boolean;
  isLive: boolean;
  setIsLive: (val: boolean) => void;
  alertFeedOpen: boolean;
  setAlertFeedOpen: (val: boolean) => void;
  loadData: () => Promise<void>;
  handleDismissAlert: (alertId: string) => Promise<void>;
  handleServerAction: (serverId: string, action: "optimize" | "terminate") => Promise<void>;
}

const DashboardContext = createContext<DashboardContextType | undefined>(undefined);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [isLive, setIsLive] = useState(true);
  const [alertFeedOpen, setAlertFeedOpen] = useState(false);

  const loadData = useCallback(async () => {
    if (!isLive && data) return;
    try {
      const result = await fetchDashboardData();
      setData(result);
    } catch (err) {
      console.warn("Could not connect to backend server (http://localhost:8000):", err);
    } finally {
      setLoading(false);
    }
  }, [isLive, data]);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000); // 5s poll
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
    loadData();
  };

  const handleServerAction = async (serverId: string, action: "optimize" | "terminate") => {
    const newStatus = action === "optimize" ? "active" : "idle";
    setData((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        servers: prev.servers.map((s) => (s.id === serverId ? { ...s, status: newStatus } : s)),
      };
    });
    try {
      await updateServerStatus(serverId, newStatus);
    } catch (err) {
      console.error("Failed to update server status on backend:", err);
    }
    loadData();
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
