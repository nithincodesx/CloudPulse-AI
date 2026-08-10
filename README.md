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

## Statistical anomaly detection (rolling baseline, not ML)

The old hardcoded cutoffs (`CPU > 85`, `network > 500 MB`, …) are gone. The
backend now computes a **rolling baseline** per server per metric — the mean and
population stddev of the last `BASELINE_DAYS` (default 7) of `server_metrics` —
as a Postgres aggregate (`metrics_baseline` RPC), and flags the latest sample by
**z-score**:

- **HIGH_CPU** — cpu z-score `> ANOMALY_Z_SCORE` (default 3.0), or the metric is
  pegged at ~100% on a flat baseline → status `critical`
- **NETWORK_ANOMALY** — network z-score `> NETWORK_Z_SCORE` (default 4.0 — a
  separate, higher knob because network traffic is bursty) → status `warning`
- **IDLE_RESOURCE** — cpu `< IDLE_CPU_FLOOR` **and** ram `< IDLE_RAM_FLOOR`
  (defaults 5 / 10). Idle is an absolute low-utilization **floor**, not an
  anomaly: a chronically idle node has a flat, already-low baseline that
  z-scores can't see.

Honesty rules baked in:
- **Warmup**: a server needs ≥ `BASELINE_MIN_SAMPLES` (default 10) points in the
  window before any z-score claim is made. No baseline ⇒ no claim.
- **This is statistics, not ML.** There is no trained model; z-scores against a
  rolling mean/stddev are classic statistical process control. The only "AI" is
  the weekly summary (below), which *summarizes* these results and real cost
  data — it never produces numbers itself.
- Multiple anomalies on one ingest collapse to the most severe status
  (`critical > warning > idle`).

Config: `ANOMALY_Z_SCORE`, `NETWORK_Z_SCORE`, `BASELINE_DAYS`,
`BASELINE_MIN_SAMPLES`, `IDLE_CPU_FLOOR`, `IDLE_RAM_FLOOR` in `backend/.env`
(see `.env.example`).

## Weekly AI summary (free-tier LLM)

A scheduled job (APScheduler, weekly cron — default **Mon 09:00 UTC**, tunable
via `WEEKLY_INSIGHT_DOW/HOUR/MINUTE/TZ`) gathers a week of **real** data and asks
a free-tier LLM to write a plain-English recap:

- per-server utilization (idle % from `metrics_utilization`, avg CPU/RAM)
- real cost per server this week vs prior week (from `daily_costs`)
- the week's alerts (type, server, message)

…and stores the result in the `weekly_insights` table (idempotent on
`period_start + period_end`). Example output: *"db-primary-01 was idle 40% of the
time, costing ~$12 for nothing this week — consider downsizing."*

### Providers (pick one — both are free-tier)

| Provider | Env | Model |
|---|---|---|
| Groq | `GROQ_API_KEY` | `llama-3.1-8b-instant` (default) |
| Gemini | `GEMINI_API_KEY` | `gemini-2.5-flash` (default) |

`AI_PROVIDER` can be `groq`, `gemini`, or `auto` (default: Groq if its key is
set, else Gemini). Override the model with `AI_MODEL`. No extra SDKs — both
providers are called over HTTP with `httpx`.

### Honesty

- The LLM is a **summarizer, not a source of numbers** — every figure in its
  prompt comes from telemetry / Cost Explorer / alerts, and the prompt forbids
  inventing values.
- The prompt (and the UI panel) state that anomaly detection is **statistical
  z-scores, not ML**, and that Cost Explorer lags 24–48h.
- Without a key the job reports *"LLM not configured"* — it never fabricates a
  summary.

### Triggering

- **Scheduled**: weekly cron (see above).
- **On demand**: `POST /api/insights/generate` (rate-limited to 2/min) — returns
  a stored summary or a `503` with the real reason (unconfigured / bad key /
  rate-limited).
- **Read**: `GET /api/insights/latest` returns the most recent summary (404 when
  none exists yet).

---

## Deployment

### Local dev with Docker

```bash
# backend/.env and frontend/.env.local must exist (copy the *.example files)
docker compose up --build
# backend → http://localhost:8000   frontend → http://localhost:3000
```

`NEXT_PUBLIC_API_URL` is a **browser-side** variable, so in the compose file it
is `http://localhost:8000` (host-reachable), never a container hostname.

### Backend → Render (free tier)

The repo ships a [`render.yaml`](render.yaml) Blueprint: **New → Blueprint →
pick `nithincodesx/CloudPulse-AI`**. It builds `backend/Dockerfile` (non-root,
`python:3.13-slim`), sets `healthCheckPath: /health`, and auto-deploys on push
to `main`.

Set these in the Render dashboard (Service → Environment — they are **not** in
git):

| Variable | Notes |
|---|---|
| `SUPABASE_URL` | Required — your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Required — service-role key (never exposed to the frontend) |
| `CORS_ORIGINS` | Your deployed Vercel origin, e.g. `https://cloudpulse-ai.vercel.app` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Optional — real cost data |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `AI_PROVIDER` | Optional — weekly AI summary |

> **Free-tier caveat:** Render free services sleep after ~15 min idle. The first
> request after a gap triggers a cold start (a few seconds); Render's `/health`
> ping doubles as the wake check.

### Frontend → Vercel

Import the repo in Vercel (it auto-detects Next.js). Set the environment
variables (Production):

```
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
NEXT_PUBLIC_API_URL=https://<your-render-app>.onrender.com
```

`NEXT_PUBLIC_API_URL` is inlined at build time — set it before every deploy
(it's the Render URL, **not** `localhost:8000`). The frontend fails fast at
build/runtime if it's missing; there is no silent localhost fallback.

### Database → Supabase (free tier)

Already in place — `supabase-schema.sql` in the SQL Editor, RLS scoped to
`auth.uid()`, backend access via the service-role key. Nothing to migrate.

### CI (GitHub Actions)

`.github/workflows/ci.yml` runs on every push/PR to `main`:
- **Backend**: `pytest` (DB-free unit tests in `backend/tests/` — pure logic
  only; integration tests needing real Supabase/AWS/LLM secrets are documented
  as excluded).
- **Frontend**: `npm ci` → `npm run build` (dummy public env vars) → Playwright
  chromium smoke test (`/login` renders, `/` returns 200).

### Health & logs

- `GET /health` → `200 {"status":"ok","database":"connected"}` when Supabase is
  reachable, else `503`. Used by Render's health check.
- Logging is **structured** (structlog): JSON lines in production, colored
  console in local dev. `LOG_LEVEL` (default `INFO`) tunes verbosity.

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
| **Statistical anomaly detection** | Per-server rolling 7-day baseline, z-score flags — honest that it's not ML |
| **Weekly AI summary** | Scheduled job summarizes real alerts + cost deltas via free-tier Groq/Gemini |
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
| `GET` | `/api/insights/latest` | Most recent weekly AI summary (404 when none) |
| `POST` | `/api/insights/generate` | Generate the weekly AI summary on demand (rate-limited) |
| `GET` | `/health` | Health check |

> Backend dashboard endpoints (`GET /api/servers/*`) are intentionally left open
> — access is gated at the UI layer. Direct data access for the signed-in
> frontend (e.g. provisioning servers) is protected by RLS via the anon key.
