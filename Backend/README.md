# Intelligent Scraper — Backend

FastAPI backend for the Intelligent Scraper SaaS.

## Stack

- **FastAPI** — async Python web framework
- **asyncpg** — Postgres driver (talks to Supabase Postgres directly)
- **PyJWT** — verifies Supabase JWTs locally (no extra round trip)
- **Pydantic v2** — request/response validation
- **uvicorn** — ASGI server

## Local setup

### 1. Prerequisites

- Python 3.12+
- Your Supabase project (already created)
- Your `.env` filled in (see below)

### 2. Clone & enter

```bash
cd backend
```

### 3. Create virtualenv & install

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Create `.env`

```bash
cp .env.example .env
```

Fill in the values from Supabase Dashboard:

| Variable | Where to find it |
|---|---|
| `SUPABASE_URL` | Project Settings → API → Project URL |
| `SUPABASE_ANON_KEY` | Project Settings → API → Project API keys → anon public |
| `SUPABASE_SERVICE_ROLE_KEY` | Project Settings → API → Project API keys → service_role |
| `SUPABASE_JWT_SECRET` | Project Settings → API → JWT Settings → JWT Secret |
| `DATABASE_URL` | Project Settings → Database → Connection string → URI (transaction pooler recommended) |

> **Database URL tip:** Supabase shows three connection strings — Direct, Transaction Pooler, Session Pooler. Use **Session Pooler** (port 5432) for FastAPI. Replace `[YOUR-PASSWORD]` with your real DB password.

### 5. Run

```bash
uvicorn app.main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

### 6. Test it

**Health check (no auth needed):**
```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

**List plans (no auth needed):**
```bash
curl http://localhost:8000/plans
# Returns Starter, Pro, Elite (Enterprise hidden)
```

**API docs in browser:**
Open http://localhost:8000/docs — interactive Swagger UI (only in debug mode).

## Testing authenticated endpoints

`/auth/me`, `/usage/today`, `/usage/plan` all require a valid Supabase JWT.

### Quick way: get a JWT from Supabase

1. Go to Supabase Dashboard → Authentication → Users → **Add user** (manual)
2. Email: `test@example.com`, Password: `testpassword123`
3. Then in SQL Editor, run:
   ```sql
   -- Give this test user the Pro plan
   INSERT INTO subscriptions (user_id, plan_id, status)
   SELECT id, 'pro', 'active' FROM users WHERE email = 'test@example.com';
   ```
4. To get a JWT, use this curl (replace `SUPABASE_URL` and `SUPABASE_ANON_KEY`):
   ```bash
   curl -X POST 'https://YOUR-PROJECT.supabase.co/auth/v1/token?grant_type=password' \
     -H "apikey: YOUR-ANON-KEY" \
     -H "Content-Type: application/json" \
     -d '{"email":"test@example.com","password":"testpassword123"}'
   ```
5. Copy the `access_token` from the response.
6. Test:
   ```bash
   TOKEN="paste-access-token-here"
   curl http://localhost:8000/auth/me -H "Authorization: Bearer $TOKEN"
   curl http://localhost:8000/usage/today -H "Authorization: Bearer $TOKEN"
   curl http://localhost:8000/usage/plan -H "Authorization: Bearer $TOKEN"
   ```

## Project structure

```
backend/
├── .env.example          # Template — copy to .env
├── .gitignore
├── Dockerfile            # For Railway deployment
├── README.md             # This file
├── requirements.txt
└── app/
    ├── main.py           # FastAPI app + lifespan
    ├── config.py         # Settings from .env
    ├── db.py             # asyncpg pool
    ├── auth.py           # JWT verification
    ├── deps.py           # CurrentUserDep, DBConn
    ├── schemas.py        # Pydantic models
    └── routers/
        ├── auth.py       # /auth/me
        ├── plans.py      # /plans
        └── usage.py      # /usage/today, /usage/plan
```

## What's NOT here yet (next phases)

- **Phase 2** — `/jobs` endpoints, Celery worker, scraper integration
- **Phase 3** — `/billing/*` endpoints, Stripe webhook handler, plan enforcement
- **Phase 4** — Frontend wired to these endpoints
