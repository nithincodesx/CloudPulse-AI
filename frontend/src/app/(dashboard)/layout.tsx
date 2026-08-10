"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import { DashboardProvider } from "@/lib/DashboardContext";
import { useAuth } from "@/lib/AuthContext";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { session, isLoading } = useAuth();
  const router = useRouter();

  // Client-side auth guard: unauthenticated visitors are bounced to /login.
  useEffect(() => {
    if (!isLoading && !session) router.replace("/login");
  }, [isLoading, session, router]);

  if (isLoading || !session) {
    return (
      <div className="flex min-h-screen items-center justify-center" style={{ background: "#0b0b0d" }}>
        <Loader2 size={24} className="animate-spin" style={{ color: "#ffe600" }} />
      </div>
    );
  }

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
