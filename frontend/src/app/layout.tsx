import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/AuthContext";

export const metadata: Metadata = {
  title: "CloudPulse AI — Enterprise Cost & Resource Monitor",
  description:
    "Enterprise-grade autonomous cloud infrastructure cost and resource optimization dashboard with realtime anomaly detection.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700;800;900&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="min-h-screen selection:bg-accent-yellow/30 selection:text-ink">
        {/* Grain overlay */}
        <div className="grain" />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
