"use client";

import React, { useState, useEffect } from "react";
import {
  ShieldCheck,
  ShieldAlert,
  Check,
  Copy,
  ExternalLink,
  ChevronRight,
  ChevronLeft,
  X,
  Sparkles,
  RefreshCw,
  Server,
  Cloud,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import {
  initiateAWSConnection,
  saveAWSConnection,
  verifyAWSConnection,
} from "@/lib/supabase";
import type { AWSConnection, AWSConnectionInitiateResult } from "@/lib/types";

function cn(...classes: (string | boolean | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

interface AWSConnectionWizardProps {
  isOpen: boolean;
  onClose: () => void;
  onConnectionSaved: (connection: AWSConnection) => void;
}

export default function AWSConnectionWizard({
  isOpen,
  onClose,
  onConnectionSaved,
}: AWSConnectionWizardProps) {
  const [step, setStep] = useState<number>(1);
  const [region, setRegion] = useState<string>("us-east-1");
  const [initiateData, setInitiateData] = useState<AWSConnectionInitiateResult | null>(null);
  const [isLoadingInit, setIsLoadingInit] = useState<boolean>(false);

  // Form Inputs
  const [displayName, setDisplayName] = useState<string>("AWS Production Account");
  const [roleArn, setRoleArn] = useState<string>("");
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [activePolicyTab, setActivePolicyTab] = useState<"trust" | "permissions">("trust");

  // Verification state
  const [isVerifying, setIsVerifying] = useState<boolean>(false);
  const [savedConn, setSavedConn] = useState<AWSConnection | null>(null);
  const [verifyError, setVerifyError] = useState<string | null>(null);

  // Fetch initiate details when wizard opens
  useEffect(() => {
    if (isOpen) {
      setStep(1);
      setRoleArn("");
      setVerifyError(null);
      setSavedConn(null);
      fetchInitiate();
    }
  }, [isOpen, region]);

  const fetchInitiate = async () => {
    setIsLoadingInit(true);
    try {
      const data = await initiateAWSConnection(region);
      if (data) setInitiateData(data);
    } catch (err) {
      console.error("Failed to initiate AWS setup", err);
    } finally {
      setIsLoadingInit(false);
    }
  };

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  const isValidArn = /^arn:aws:iam::\d{12}:role\/[\w+=,.@\-_/]+$/.test(roleArn.trim());

  const handleSaveAndVerify = async () => {
    if (!isValidArn || !initiateData) return;
    setIsVerifying(true);
    setVerifyError(null);

    try {
      const conn = await saveAWSConnection({
        role_arn: roleArn.trim(),
        external_id: initiateData.external_id,
        display_name: displayName.trim() || "AWS Account",
        region,
      });

      if (conn) {
        setSavedConn(conn);
        if (conn.status === "connected") {
          setStep(4);
          onConnectionSaved(conn);
        } else {
          // If status is error, attempt an explicit verify call to get detailed error diagnostic
          const verifyRes = await verifyAWSConnection(conn.id);
          if (verifyRes?.success && verifyRes.connection) {
            setSavedConn(verifyRes.connection);
            setStep(4);
            onConnectionSaved(verifyRes.connection);
          } else {
            setVerifyError(verifyRes?.error_message || conn.error_message || "Failed to assume IAM Role.");
          }
        }
      }
    } catch (err: any) {
      setVerifyError(err.message || "Failed to save and verify AWS connection.");
    } finally {
      setIsVerifying(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-2xl border border-white/10 bg-[#0e0e12] shadow-2xl overflow-hidden">
        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-white/10 px-6 py-4 bg-white/[0.02]">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
              <Cloud size={16} />
            </span>
            <div>
              <h2 className="text-base font-bold text-white">Connect AWS Account</h2>
              <p className="text-xs text-zinc-400">Multi-tenant cross-account IAM role assumption via STS</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white"
          >
            <X size={16} />
          </button>
        </div>

        {/* Steps Breadcrumbs */}
        <div className="flex items-center justify-between border-b border-white/5 px-6 py-2.5 bg-[#121218] text-xs">
          {[
            { num: 1, label: "Permissions" },
            { num: 2, label: "IAM Role" },
            { num: 3, label: "Enter ARN" },
            { num: 4, label: "Connected" },
          ].map((s, idx) => (
            <React.Fragment key={s.num}>
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold",
                    step === s.num
                      ? "bg-indigo-600 text-white"
                      : step > s.num
                      ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                      : "bg-white/5 text-zinc-500"
                  )}
                >
                  {step > s.num ? <Check size={11} /> : s.num}
                </span>
                <span
                  className={cn(
                    "font-medium",
                    step === s.num ? "text-white" : step > s.num ? "text-zinc-300" : "text-zinc-500"
                  )}
                >
                  {s.label}
                </span>
              </div>
              {idx < 3 && <div className="h-px w-8 bg-white/10" />}
            </React.Fragment>
          ))}
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-6 text-xs text-zinc-300">
          {/* STEP 1: Security & Least-Privilege Overview */}
          {step === 1 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-semibold text-white">How CloudPulse Connects to Your AWS Account</h3>
                <p className="mt-1 text-zinc-400">
                  CloudPulse uses cross-account IAM role assumption with a cryptographically unique <strong>ExternalId</strong>.
                  We never ask for or store permanent AWS access keys or secrets.
                </p>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {/* What CloudPulse can do */}
                <div className="rounded-xl border border-emerald-500/20 bg-emerald-950/10 p-4">
                  <span className="flex items-center gap-1.5 font-bold text-emerald-400">
                    <ShieldCheck size={14} />
                    CloudPulse CAN:
                  </span>
                  <ul className="mt-2.5 space-y-1.5 text-zinc-300">
                    <li className="flex items-start gap-1.5">
                      <Check size={12} className="mt-0.5 text-emerald-400 shrink-0" />
                      <span>Read EC2 instance metadata & specifications</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <Check size={12} className="mt-0.5 text-emerald-400 shrink-0" />
                      <span>Read EC2 tags to group server telemetry</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <Check size={12} className="mt-0.5 text-emerald-400 shrink-0" />
                      <span>Read Cost Explorer daily spend & savings</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <Check size={12} className="mt-0.5 text-emerald-400 shrink-0" />
                      <span>Identify idle & oversized instances</span>
                    </li>
                  </ul>
                </div>

                {/* What CloudPulse CANNOT do */}
                <div className="rounded-xl border border-red-500/20 bg-red-950/10 p-4">
                  <span className="flex items-center gap-1.5 font-bold text-red-400">
                    <ShieldAlert size={14} />
                    CloudPulse CANNOT:
                  </span>
                  <ul className="mt-2.5 space-y-1.5 text-zinc-300">
                    <li className="flex items-start gap-1.5">
                      <X size={12} className="mt-0.5 text-red-400 shrink-0" />
                      <span>Start, stop, or terminate instances</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <X size={12} className="mt-0.5 text-red-400 shrink-0" />
                      <span>Delete or modify resources or volumes</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <X size={12} className="mt-0.5 text-red-400 shrink-0" />
                      <span>Modify Security Groups or VPCs</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <X size={12} className="mt-0.5 text-red-400 shrink-0" />
                      <span>Create or alter IAM permissions</span>
                    </li>
                  </ul>
                </div>
              </div>

              <div className="rounded-xl border border-indigo-500/20 bg-indigo-950/20 p-3.5 flex items-start gap-3">
                <Sparkles size={16} className="mt-0.5 text-indigo-400 shrink-0" />
                <div>
                  <p className="font-semibold text-white">Temporary Credentials Only</p>
                  <p className="mt-0.5 text-[11px] text-zinc-400">
                    When CloudPulse syncs your costs or discovers instances, it generates a temporary 1-hour session via AWS STS.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* STEP 2: IAM Role Setup (CloudFormation + Manual) */}
          {step === 2 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-semibold text-white">Create CloudPulse Read-Only IAM Role</h3>
                <p className="mt-1 text-zinc-400">
                  Deploy the pre-configured role in your AWS account using 1-Click CloudFormation or configure manually.
                </p>
              </div>

              {/* 1-Click CloudFormation Launch Button */}
              {initiateData && (
                <div className="rounded-xl border border-indigo-500/30 bg-gradient-to-r from-indigo-950/40 via-purple-950/20 to-indigo-950/40 p-4">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    <div>
                      <span className="font-bold text-white flex items-center gap-1.5">
                        <Sparkles size={14} className="text-indigo-400" />
                        Option A: 1-Click CloudFormation (Recommended)
                      </span>
                      <p className="mt-0.5 text-[11px] text-zinc-400">
                        Automatically provisions the role with the correct ExternalId condition in 2 minutes.
                      </p>
                    </div>

                    <a
                      href={initiateData.cloudformation_quick_create_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white shadow-lg transition-all hover:bg-indigo-500 shrink-0"
                    >
                      <ExternalLink size={13} />
                      Launch in AWS Console
                    </a>
                  </div>
                </div>
              )}

              {/* Manual IAM Setup Box */}
              <div className="rounded-xl border border-white/10 bg-[#121218] p-4">
                <span className="font-bold text-zinc-300">Option B: Manual IAM Role Creation</span>
                <p className="mt-1 text-[11px] text-zinc-400">
                  In AWS IAM Console, create a new Role with &quot;Another AWS account&quot; and configure:
                </p>

                {/* ExternalId & Account ID fields */}
                <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                  <div className="rounded-lg border border-white/5 bg-[#16161e] p-2.5">
                    <span className="text-[10px] uppercase font-bold text-zinc-500">Your Unique ExternalId</span>
                    <div className="mt-1 flex items-center justify-between">
                      <span className="font-mono text-xs text-indigo-300">{initiateData?.external_id || "Generating..."}</span>
                      <button
                        onClick={() => initiateData && handleCopy(initiateData.external_id, "ext_id")}
                        className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-white"
                      >
                        {copiedKey === "ext_id" ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                      </button>
                    </div>
                  </div>

                  <div className="rounded-lg border border-white/5 bg-[#16161e] p-2.5">
                    <span className="text-[10px] uppercase font-bold text-zinc-500">CloudPulse AWS Account ID</span>
                    <div className="mt-1 flex items-center justify-between">
                      <span className="font-mono text-xs text-zinc-300">{initiateData?.cloudpulse_account_id || "123456789012"}</span>
                      <button
                        onClick={() => initiateData && handleCopy(initiateData.cloudpulse_account_id, "acc_id")}
                        className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-white"
                      >
                        {copiedKey === "acc_id" ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                      </button>
                    </div>
                  </div>
                </div>

                {/* Policy Tabs */}
                <div className="mt-3">
                  <div className="flex border-b border-white/10 text-[11px]">
                    <button
                      onClick={() => setActivePolicyTab("trust")}
                      className={cn(
                        "px-3 py-1.5 font-semibold border-b-2 transition-all",
                        activePolicyTab === "trust" ? "border-indigo-500 text-white" : "border-transparent text-zinc-400"
                      )}
                    >
                      Trust Policy JSON
                    </button>
                    <button
                      onClick={() => setActivePolicyTab("permissions")}
                      className={cn(
                        "px-3 py-1.5 font-semibold border-b-2 transition-all",
                        activePolicyTab === "permissions" ? "border-indigo-500 text-white" : "border-transparent text-zinc-400"
                      )}
                    >
                      Permissions Policy JSON
                    </button>
                  </div>

                  <div className="relative mt-2">
                    <pre className="max-h-36 overflow-x-auto rounded-lg border border-white/5 bg-black/40 p-3 font-mono text-[10px] text-zinc-300">
                      {JSON.stringify(
                        activePolicyTab === "trust" ? initiateData?.trust_policy : initiateData?.permissions_policy,
                        null,
                        2
                      )}
                    </pre>
                    <button
                      onClick={() =>
                        initiateData &&
                        handleCopy(
                          JSON.stringify(
                            activePolicyTab === "trust" ? initiateData.trust_policy : initiateData.permissions_policy,
                            null,
                            2
                          ),
                          "policy_json"
                        )
                      }
                      className="absolute right-2 top-2 rounded bg-white/10 px-2 py-1 text-[10px] text-zinc-300 hover:bg-white/20 hover:text-white flex items-center gap-1"
                    >
                      {copiedKey === "policy_json" ? <Check size={11} className="text-emerald-400" /> : <Copy size={11} />}
                      <span>Copy Policy</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* STEP 3: Enter Role ARN & Connection Name */}
          {step === 3 && (
            <div className="space-y-4">
              <div>
                <h3 className="text-sm font-semibold text-white">Enter Role ARN & Region</h3>
                <p className="mt-1 text-zinc-400">
                  After creating the IAM Role in your AWS account, copy its Role ARN and paste it below.
                </p>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-300">Display Name / Alias</label>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="e.g. AWS Production Fleet"
                    className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-zinc-300">Primary AWS Region</label>
                    <select
                      value={region}
                      onChange={(e) => setRegion(e.target.value)}
                      className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#16161e] p-2.5 text-xs text-white focus:border-indigo-500 focus:outline-none"
                    >
                      <option value="us-east-1">us-east-1 (N. Virginia)</option>
                      <option value="us-west-2">us-west-2 (Oregon)</option>
                      <option value="ap-south-1">ap-south-1 (Mumbai)</option>
                      <option value="eu-west-1">eu-west-1 (Ireland)</option>
                      <option value="eu-central-1">eu-central-1 (Frankfurt)</option>
                      <option value="ap-southeast-1">ap-southeast-1 (Singapore)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-zinc-300">ExternalId (Auto-Assigned)</label>
                    <input
                      type="text"
                      disabled
                      value={initiateData?.external_id || ""}
                      className="mt-1.5 w-full rounded-lg border border-white/5 bg-black/40 p-2.5 font-mono text-xs text-zinc-500 cursor-not-allowed"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-zinc-300">AWS Role ARN</label>
                  <input
                    type="text"
                    value={roleArn}
                    onChange={(e) => setRoleArn(e.target.value)}
                    placeholder="arn:aws:iam::123456789012:role/CloudPulseReadOnlyRole"
                    className={cn(
                      "mt-1.5 w-full rounded-lg border p-2.5 font-mono text-xs text-white placeholder-zinc-500 focus:outline-none",
                      roleArn.trim().length > 0 && !isValidArn
                        ? "border-red-500/50 bg-red-950/10 focus:border-red-500"
                        : isValidArn
                        ? "border-emerald-500/50 bg-emerald-950/10 focus:border-emerald-500"
                        : "border-white/10 bg-[#16161e] focus:border-indigo-500"
                    )}
                  />
                  {roleArn.trim().length > 0 && !isValidArn && (
                    <p className="mt-1 text-[11px] text-red-400">
                      Expected format: arn:aws:iam::123456789012:role/RoleName
                    </p>
                  )}
                </div>

                {verifyError && (
                  <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-3.5 text-xs text-red-300 flex items-start gap-2.5">
                    <AlertTriangle size={15} className="mt-0.5 shrink-0 text-red-400" />
                    <div>
                      <p className="font-semibold">Verification Failed</p>
                      <p className="mt-0.5 text-[11px] text-red-300/90">{verifyError}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 4: Connected Success Screen */}
          {step === 4 && savedConn && (
            <div className="flex flex-col items-center justify-center space-y-4 py-4 text-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 shadow-xl">
                <CheckCircle2 size={32} />
              </div>

              <div>
                <h3 className="text-base font-bold text-white">AWS Account Connected!</h3>
                <p className="mt-1 text-xs text-zinc-400">
                  CloudPulse successfully assumed the IAM Role and verified read access.
                </p>
              </div>

              <div className="w-full rounded-xl border border-white/10 bg-[#121218] p-4 text-left space-y-2 text-xs">
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <span className="text-zinc-500">Account ID</span>
                  <span className="font-mono font-semibold text-white">{savedConn.aws_account_id || "Verified"}</span>
                </div>
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <span className="text-zinc-500">Display Name</span>
                  <span className="font-medium text-white">{savedConn.display_name}</span>
                </div>
                <div className="flex items-center justify-between border-b border-white/5 pb-2">
                  <span className="text-zinc-500">Role ARN</span>
                  <span className="font-mono text-zinc-300 truncate max-w-xs">{savedConn.role_arn}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-zinc-500">Region</span>
                  <span className="text-zinc-300">{savedConn.region}</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer Controls */}
        <div className="flex items-center justify-between border-t border-white/10 px-6 py-4 bg-white/[0.02]">
          {step > 1 && step < 4 ? (
            <button
              onClick={() => setStep(step - 1)}
              className="inline-flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-zinc-300 hover:bg-white/10"
            >
              <ChevronLeft size={14} />
              Back
            </button>
          ) : (
            <div />
          )}

          {step === 1 && (
            <button
              onClick={() => setStep(2)}
              className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
            >
              Next: Configure IAM Role
              <ChevronRight size={14} />
            </button>
          )}

          {step === 2 && (
            <button
              onClick={() => setStep(3)}
              className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
            >
              Next: Enter Role ARN
              <ChevronRight size={14} />
            </button>
          )}

          {step === 3 && (
            <button
              onClick={handleSaveAndVerify}
              disabled={!isValidArn || isVerifying}
              className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              <RefreshCw size={13} className={cn(isVerifying && "animate-spin")} />
              {isVerifying ? "Verifying with AWS STS..." : "Verify & Connect"}
            </button>
          )}

          {step === 4 && (
            <button
              onClick={onClose}
              className="rounded-lg bg-indigo-600 px-5 py-2 text-xs font-semibold text-white hover:bg-indigo-500"
            >
              Done
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
