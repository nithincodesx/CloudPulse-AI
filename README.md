# CloudPulse AI ☁️⚡

**Autonomous Cloud Infrastructure Cost & Resource Monitoring Dashboard**

An enterprise-grade, SaaS-style dashboard that tracks real-time server utilization, flags budget anomalies, detects idle or over-provisioned infrastructure, and logs telemetry data to Supabase.

---

## Architecture

```
┌─────────────────┐     POST /api/metrics     ┌──────────────┐     ┌──────────┐
│  Telemetry Agent │ ────────────────────────▶ │  FastAPI     │────▶│ Supabase │
│  (psutil /host)  │                           │  Backend     │     │  (DB)    │
└─────────────────┘                           └──────┬───────┘     └──────────┘
                                                     │ GET /api/servers/status
                                                     ▼
                                              ┌──────────────┐
                                              │  Next.js      │
                                              │  Dashboard    │
                                              │  (Tailwind)   │
                                              └──────────────┘
```

## Quick Start

### 1. Supabase Setup

1. Create a Supabase project at [supabase.com](https://supabase.com)
2. Open the **SQL Editor** and paste the contents of `supabase-schema.sql`
3. Copy your project URL and anon key from **Settings → API**

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL and SUPABASE_KEY
uvicorn main:app --reload --port 8000
```

> The backend stores everything in **Supabase Postgres** — there is no local
> database. It reads `SUPABASE_URL` / `SUPABASE_KEY` from `.env` and will refuse
> to start if Supabase is unreachable or `supabase-schema.sql` hasn't been applied.

### 3. Telemetry Agent (separate terminal)

```bash
cd backend
source .venv/bin/activate
python telemetry_agent.py --server-id <UUID_FROM_SUPABASE> --interval 5
```

> `--server-id` is a UUID from the `servers` table. Any valid UUID works —
> unknown server IDs are auto-registered on first report.

### 4. Frontend

```bash
cd frontend
cp .env.local.example .env.local   # fill in Supabase keys
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) to see the dashboard.

---

## Features

| Feature | Description |
|---|---|
| **Real-time KPI cards** | Active nodes, avg CPU, monthly spend, alert count |
| **Interactive charts** | CPU & RAM area chart with per-server filtering |
| **Live alert feed** | HIGH_CPU, IDLE_RESOURCE, BUDGET_SPIKE alerts with dismiss |
| **Cost optimization table** | Per-node breakdown with projected savings |
| **5s auto-refresh** | Dashboard polls for updates every 5 seconds |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/metrics` | Ingest telemetry payload |
| `GET` | `/api/servers/status` | Aggregated server view |
| `GET` | `/api/servers/{id}/metrics` | Historical metrics for one server |
| `GET` | `/health` | Health check |
