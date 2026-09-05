"use client";

import { useState } from "react";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import { DashboardProvider } from "@/lib/DashboardContext";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <DashboardProvider>
      <div className="flex min-h-screen bg-[#07070a] dashboard-bg text-[#f4f0e6]">
        <Sidebar sidebarOpen={sidebarOpen} setSidebarOpen={setSidebarOpen} />

        {/* Main content container */}
        <div className="flex flex-1 flex-col min-w-0 overflow-hidden relative">
          <Topbar setSidebarOpen={setSidebarOpen} />
          <main className="flex-1 overflow-y-auto px-4 md:px-8 py-6">
            {children}
          </main>
        </div>
      </div>
    </DashboardProvider>
  );
}
