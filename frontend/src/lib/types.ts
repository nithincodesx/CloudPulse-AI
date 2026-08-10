export interface Server {
  id: string;
  server_name: string;
  ip_address?: string;
  ingestion_token?: string;
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
  estimated_cost_per_hour: number;
  recorded_at: string;
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
}

export interface DashboardData {
  servers: Server[];
  metrics: Record<string, MetricRow[]>;
  active_alerts: Alert[];
  summary: Summary;
}
