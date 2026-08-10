"use client";

import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import { DashboardProvider } from "@/lib/DashboardContext";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <DashboardProvider>
      <div className="flex min-h-screen dashboard-bg">
        <Sidebar sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />
        
        {/* Main content container */}
        <div className="flex flex-1 flex-col min-w-0 overflow-hidden relative">
          <Topbar setSidebarOpen={setSidebarOpen} />
          {children}
        </div>
      </div>
    </DashboardProvider>
  );
}
