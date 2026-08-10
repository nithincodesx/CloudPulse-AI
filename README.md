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
| **Cost optimization table** | Per-node breakdown with projected savings |
| **5s auto-refresh** | Dashboard polls for updates every 5 seconds |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/metrics` | Ingest telemetry payload (`Bearer <ingestion_token>`, rate-limited) |
| `GET` | `/api/servers/status` | Aggregated server view |
| `GET` | `/api/servers/{id}/metrics` | Historical metrics for one server |
| `GET` | `/health` | Health check |

> Backend dashboard endpoints (`GET /api/servers/*`) are intentionally left open
> — access is gated at the UI layer. Direct data access for the signed-in
> frontend (e.g. provisioning servers) is protected by RLS via the anon key.
