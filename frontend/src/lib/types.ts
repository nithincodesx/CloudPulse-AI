export interface Server {
  id: string;
  server_name: string;
  ip_address?: string;
  ingestion_token?: string;
  cost_tag?: string;
  status: "active" | "warning" | "critical" | "idle";
  specifications?: {
    vcpus?: number;
    ram_gb?: number;
    type?: string;
  };
  created_at?: string;
}

export interface MetricRow {
  cpu_usage: number;
  ram_usage: number;
  network_traffic: number;
  recorded_at: string;
}

/** A daily cost row pulled from AWS Cost Explorer (real spend). */
export interface DailyCost {
  id: string;
  server_id: string;
  cost_date: string;
  amount: number;
  currency: string;
  source: string;
}

export interface Alert {
  id: string;
  server_id: string;
  alert_type: "HIGH_CPU" | "IDLE_RESOURCE" | "BUDGET_SPIKE" | "NETWORK_ANOMALY";
  message: string;
  resolved: boolean;
  created_at: string;
  servers?: { server_name: string };
}

export interface Summary {
  total_nodes: number;
  active_nodes: number;
  warning_nodes: number;
  critical_nodes: number;
  idle_nodes: number;
  avg_cpu_load_pct: number;
  monthly_cost_estimate: number;
  hourly_cost_estimate: number;
  active_alerts_count: number;
  /** "aws_cost_explorer" when real data is synced, "simulated" otherwise. */
  cost_source?: "aws_cost_explorer" | "simulated";
  cloud_connected?: boolean;
  last_cost_sync?: string;
}

export interface CloudStatus {
  connected: boolean;
  provider: string | null;
  cost_tag_key: string;
  last_sync: string | null;
  days_of_data: number;
  cost_source: "aws_cost_explorer" | "simulated";
  error: string | null;
}

export interface SyncResult {
  days_synced: number;
  matched: number;
  unmatched: string[];
  total_amount: number;
  error: string | null;
}

export interface DashboardData {
  servers: Server[];
  metrics: Record<string, MetricRow[]>;
  active_alerts: Alert[];
  summary: Summary;
  /** server_id → daily cost rows (real spend) when AWS is connected. */
  costs?: Record<string, DailyCost[]>;
  cloud?: CloudStatus;
}
