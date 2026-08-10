"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Cloud, Loader2, LogIn, Mail, UserPlus } from "lucide-react";
import { useAuth } from "@/lib/AuthContext";

type Mode = "signin" | "signup";

export default function LoginPage() {
  const { user, isLoading, signInWithPassword, signInWithOtp, signUp } = useAuth();
  const router = useRouter();

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Already signed in → straight to the dashboard.
  useEffect(() => {
    if (!isLoading && user) router.replace("/");
  }, [isLoading, user, router]);

  if (isLoading) {
    return <Splash />;
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      if (mode === "signin") {
        const { error } = await signInWithPassword(email, password);
        if (error) setError(error);
        else router.replace("/");
      } else {
        const { error } = await signUp(email, password);
        if (error) setError(error);
        else setNotice("Account created — check your email to confirm, then sign in.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const sendMagicLink = async () => {
    setError(null);
    setNotice(null);
    setSubmitting(true);
    try {
      const { error } = await signInWithOtp(email);
      if (error) setError(error);
      else setNotice(`Magic link sent to ${email} — check your inbox.`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main
      className="flex min-h-screen items-center justify-center px-4"
      style={{ background: "radial-gradient(1200px 600px at 50% -10%, #1b1b20 0%, #0b0b0d 60%)" }}
    >
      <div
        className="w-full max-w-md rounded-2xl border p-8"
        style={{
          background: "rgba(18,18,18,0.9)",
          borderColor: "rgba(244,240,230,0.08)",
          boxShadow: "0 24px 64px rgba(0,0,0,0.5)",
        }}
      >
        <div className="mb-8 flex flex-col items-center gap-3">
          <div
            className="flex h-14 w-14 items-center justify-center rounded-2xl"
            style={{ background: "#16161a", boxShadow: "inset 0 1px 2px rgba(255,255,255,0.06)" }}
          >
            <Cloud size={26} style={{ color: "#ffe600" }} />
          </div>
          <div className="text-center">
            <h1 className="font-heading text-lg font-extrabold tracking-tight" style={{ color: "#fff" }}>
              CloudPulse AI
            </h1>
            <p className="mt-1 font-mono text-[11px] uppercase tracking-[0.2em]" style={{ color: "#8a8780" }}>
              {mode === "signin" ? "Sign in to continue" : "Create an account"}
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="font-mono text-[11px] uppercase tracking-widest" style={{ color: "#8a8780" }}>
              Email
            </span>
            <input
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
              style={{
                background: "#0b0b0d",
                borderColor: "rgba(244,240,230,0.10)",
                color: "#f4f0e6",
              }}
            />
          </label>

          {mode === "signin" && (
            <label className="flex flex-col gap-1.5">
              <span className="font-mono text-[11px] uppercase tracking-widest" style={{ color: "#8a8780" }}>
                Password
              </span>
              <input
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="rounded-lg border px-3 py-2.5 text-sm outline-none transition-colors"
                style={{
                  background: "#0b0b0d",
                  borderColor: "rgba(244,240,230,0.10)",
                  color: "#f4f0e6",
                }}
              />
            </label>
          )}

          {error && (
            <p className="rounded-md px-3 py-2 text-xs" style={{ background: "rgba(232,70,44,0.12)", color: "#ff8a75" }}>
              {error}
            </p>
          )}
          {notice && (
            <p className="rounded-md px-3 py-2 text-xs" style={{ background: "rgba(16,185,129,0.12)", color: "#6ee7b7" }}>
              {notice}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-opacity disabled:opacity-50"
            style={{ background: "#ffe600", color: "#0b0b0d" }}
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : mode === "signin" ? <LogIn size={16} /> : <UserPlus size={16} />}
            {mode === "signin" ? "Sign in" : "Create account"}
          </button>
        </form>

        <div className="my-5 flex items-center gap-3">
          <div className="h-px flex-1" style={{ background: "rgba(244,240,230,0.08)" }} />
          <span className="font-mono text-[10px] uppercase tracking-widest" style={{ color: "#5f5d58" }}>
            or
          </span>
          <div className="h-px flex-1" style={{ background: "rgba(244,240,230,0.08)" }} />
        </div>

        <button
          type="button"
          onClick={sendMagicLink}
          disabled={submitting || !email}
          className="flex w-full items-center justify-center gap-2 rounded-lg border px-4 py-2.5 text-sm transition-colors disabled:opacity-50"
          style={{ borderColor: "rgba(244,240,230,0.14)", color: "#f4f0e6" }}
        >
          <Mail size={16} style={{ color: "#ffe600" }} />
          Email me a sign-in link
        </button>

        <p className="mt-6 text-center text-xs" style={{ color: "#8a8780" }}>
          {mode === "signin" ? "New to CloudPulse?" : "Already have an account?"}{" "}
          <button
            type="button"
            onClick={() => {
              setMode(mode === "signin" ? "signup" : "signin");
              setError(null);
              setNotice(null);
            }}
            className="font-semibold underline-offset-2 hover:underline"
            style={{ color: "#ffe600" }}
          >
            {mode === "signin" ? "Create an account" : "Sign in"}
          </button>
        </p>
      </div>
    </main>
  );
}

function Splash() {
  return (
    <main className="flex min-h-screen items-center justify-center" style={{ background: "#0b0b0d" }}>
      <Loader2 size={24} className="animate-spin" style={{ color: "#ffe600" }} />
    </main>
  );
}
