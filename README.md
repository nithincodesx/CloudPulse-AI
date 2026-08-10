# CloudPulse AI ☁️⚡

**Autonomous Cloud Infrastructure Cost & Resource Monitoring Dashboard**

An enterprise-grade, SaaS-style dashboard that tracks real-time server utilization, flags budget anomalies, detects idle or over-provisioned infrastructure, and logs telemetry data to Supabase.

---

## Architecture

```
┌─────────────────┐   POST /api/metrics         ┌──────────────┐
│  Telemetry Agent │   Bearer <ingestion_token>  │  FastAPI     │
│  (psutil /host)  │ ───────────────────────────▶│  Backend     │
└─────────────────┘    (rate-limited)            │ (service key)│
                                                └──────┬───────┘
                                                       │
                                                       ▼
                                               ┌──────────────┐
                                               │  Supabase    │
                                               │  Postgres    │
                                               │  (RLS scoped │
                                               │  to auth.uid)│
                                               └──────┬───────┘
                                                      ▲
                                              anon key │ auth.uid() RLS
                                                      │
                                              ┌──────────────┐
                                              │  Next.js      │
                                              │  Dashboard    │
                                              │ (Supabase Auth)│
                                              └──────────────┘
```

## Quick Start

### 1. Supabase Setup

1. Create a Supabase project at [supabase.com](https://supabase.com)
2. **Enable Auth → Providers → Email**: turn on the **Email** provider (with
   "Confirm email" on for sign-up) — this powers both password sign-in and the
   "Email me a sign-in link" magic-link flow.
3. Open the **SQL Editor** and paste the contents of `supabase-schema.sql`
   (creates the tables, `ingestion_token` defaults, and `auth.uid()`-scoped RLS
   policies).
4. Copy your project URL, anon key, and **service-role key** from
   **Settings → API**.

### 2. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, CORS_ORIGINS, RATE_LIMIT_PER_MINUTE
uvicorn main:app --reload --port 8000
```

> The backend stores everything in **Supabase Postgres** — there is no local
> database. It reads `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` from `.env` and will
> refuse to start if Supabase is unreachable or `supabase-schema.sql` hasn't been
> applied.
>
> The **service-role key bypasses RLS** and must live only in `backend/.env` —
> never expose it to the frontend. `CORS_ORIGINS` is a comma-separated list of
> allowed browser origins (default `http://localhost:3000`), and
> `RATE_LIMIT_PER_MINUTE` caps ingestion on `POST /api/metrics` (default `30`).
>
> All AWS variables are **optional** — see the
> [AWS Cost Explorer](#optional-aws-cost-explorer-integration) section. If they're
> left unset, the dashboard runs in **simulated cost mode** (all cost figures show
> `$0` with a connect prompt — never a fabricated estimate).

### 3. Telemetry Agent (separate terminal)

```bash
cd backend
source .venv/bin/activate
python telemetry_agent.py --token <INGESTION_TOKEN> --interval 5
```

> `--token` is the per-node ingestion token shown in the dashboard when you
> provision a node (Fleet Management → Provision New Node → node details). The
> agent authenticates with `Authorization: Bearer <token>`; unknown or missing
> tokens are **rejected with HTTP 401** — servers are never auto-registered.
>
> The agent reports **only real host metrics** (`cpu_usage`, `ram_usage`,
> `network_traffic`). It does not compute or send any cost — spend comes from AWS
> Cost Explorer on the backend when a cloud account is connected.

### 4. Frontend

```bash
cd frontend
cp .env.local.example .env.local   # fill in Supabase URL, anon key, and NEXT_PUBLIC_API_URL
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) — you'll be asked to sign in.
Create an account (or use a magic link), then provision a node from
**Fleet Management** to get its ingestion token.

> The frontend now requires Supabase Auth to be enabled and real
> `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` values. Magic-link
> sign-in redirects through `/auth/callback` to exchange the one-time code.

---

## Optional: AWS Cost Explorer integration

By default the dashboard shows **real** month-to-date spend pulled from
**AWS Cost Explorer** (the `ce:GetCostAndUsage` API) — **if** a read-only AWS
account is configured. Without one it runs in **simulated cost mode** (see
below). Cost figures are never estimated; they're either real Cost Explorer data
or `$0`.

### 1. Create a read-only IAM role

Create an IAM user (or role) with a **read-only** policy — either the AWS managed
policy `AWSBillingReadOnlyAccess`, or the minimal inline policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": "ce:GetCostAndUsage", "Resource": "*" }
  ]
}
```

This works on a free-tier account; billing data access requires no paid Cost
Explorer tier.

### 2. Tag your cost-bearing resources

Cost Explorer reports cost per resource **tag**. Tag the EC2/RDS/Lambda resources
that belong to each monitored node with the key `server` (configurable via
`AWS_COST_TAG_KEY`) and a **value matching the node's cost tag** — CloudPulse
matches tag value → `cost_tag` first, then `server_name`, then `ip_address`.

### 3. Set credentials in `backend/.env`

```bash
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
AWS_COST_TAG_KEY=server
```

Credentials stay in `backend/.env` — they never enter the database or frontend.
On startup (and via **Sync now** in the UI) the backend pulls the last 14 days of
daily cost, upserts them into the `daily_costs` table, and derives:

- **MTD spend** — sum of daily actuals for the current month
- **Projected monthly run rate** — MTD ÷ elapsed days × days in month
- **Hourly burn** — latest available day ÷ 24 (labeled **derived**)

### ⚠️ Cost Explorer is daily and lags 24–48h

There is no real per-hour cost. "Hourly burn" is derived from the latest daily
total and labeled as such; today's spend appears tomorrow. On connection, a sync
also flags **budget spikes** — a node whose latest daily cost exceeds 2× its
14-day mean raises a `BUDGET_SPIKE` alert.

### Simulated vs. real mode

| State | Cost source | What the UI shows |
|---|---|---|
| AWS connected & synced | `daily_costs` from Cost Explorer | Real numbers + green **AWS · Real data** badge |
| No cloud account | none | **$0** / `—` figures, amber **Simulated mode** badge, connect prompt with setup steps |

---

## Features

| Feature | Description |
|---|---|
| **Supabase Auth** | Email/password sign-in and magic-link sign-in gating the dashboard |
| **Per-node provisioning** | Provision a node from the UI; each server gets a unique 256-bit ingestion token |
| **Token-based ingestion** | Telemetry agent authenticates with `Authorization: Bearer <token>`; unknown tokens → 401 |
| **RLS-scoped data** | Postgres RLS policies restrict servers/metrics/alerts to the owning `auth.uid()` |
| **Rate-limited ingestion** | `POST /api/metrics` throttled via slowapi (`RATE_LIMIT_PER_MINUTE`) |
| **Restricted CORS** | Backend only accepts browser origins listed in `CORS_ORIGINS` |
| **Real-time KPI cards** | Active nodes, avg CPU, monthly spend, alert count |
| **Interactive charts** | CPU & RAM area chart with per-server filtering |
| **Live alert feed** | HIGH_CPU, IDLE_RESOURCE, BUDGET_SPIKE alerts with dismiss |
| **AWS Cost Explorer** | Read-only integration pulls real daily spend per resource tag |
| **Honest cost modes** | Real data with a green badge, or simulated mode showing `$0` + connect prompt — never fabricated numbers |
| **Budget spike detection** | Real daily-cost spikes (>2× 14-day mean) raise BUDGET_SPIKE alerts |
| **Cost optimization table** | Per-node breakdown with projected savings from real spend |
| **5s auto-refresh** | Dashboard polls for updates every 5 seconds |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/metrics` | Ingest telemetry payload (`Bearer <ingestion_token>`, rate-limited) |
| `GET` | `/api/servers/status` | Aggregated server view (incl. real daily costs & cloud status) |
| `GET` | `/api/servers/{id}/metrics` | Historical metrics for one server |
| `GET` | `/api/cloud/status` | AWS Cost Explorer connection status |
| `POST` | `/api/cloud/sync` | Pull daily cost from Cost Explorer & flag budget spikes |
| `GET` | `/health` | Health check |

> Backend dashboard endpoints (`GET /api/servers/*`) are intentionally left open
> — access is gated at the UI layer. Direct data access for the signed-in
> frontend (e.g. provisioning servers) is protected by RLS via the anon key.
