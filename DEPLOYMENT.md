# Deployment Guide

How to run the Mobile Money System in Docker, and what to do before exposing it
to real users.

## Quick start (Docker)

```bash
docker compose up --build
```

| Service | URL | Notes |
|---------|-----|-------|
| Web app (Streamlit) | http://localhost:8501 | The mobile-money UI |
| REST API (FastAPI) | http://localhost:8000 | Swagger docs at `/docs` |
| Health checks | `/_stcore/health`, `/health` | Wired into compose healthchecks |

Both services share one SQLite database in the `mms-data` named volume
(`MMS_DB_PATH=/app/data/mobile_money.db`).

Build the image alone:

```bash
docker build -t mobile-money-system .
docker run -p 8501:8501 -v mms-data:/app/data mobile-money-system
```

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MMS_DB_PATH` | `mobile_money.db` | SQLite file location. Point it at a mounted volume in production. |
| `MMS_API_KEY` | _(unset = API open)_ | When set, every API endpoint requires the `X-API-Key` header with this value. **Always set it in production.** |

## Production checklist

1. **Set a strong API key**: `export MMS_API_KEY=$(openssl rand -hex 32)` before
   `docker compose up`. Rotate it by restarting the `api` service with a new value.
2. **Put TLS in front**: do not expose ports 8501/8000 directly. Terminate TLS at
   a reverse proxy (nginx, Caddy, or a cloud load balancer) and proxy to the
   containers, e.g.:

   ```nginx
   # /etc/nginx/sites-available/mms
   server {
       listen 443 ssl;
       server_name money.example.com;
       # ssl_certificate / ssl_certificate_key ...

       location / {
           proxy_pass http://127.0.0.1:8501;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";   # Streamlit websockets
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }

       location /api/ {
           proxy_pass http://127.0.0.1:8000/;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```

   (With Caddy it is just `reverse_proxy` + automatic HTTPS.)
3. **Back up the database**: the whole state lives in one SQLite file.

   ```bash
   docker compose exec web sh -c 'cp /app/data/mobile_money.db /app/data/backup-$(date +%F).db'
   ```

   Schedule this (cron/systemd timer) and copy the file off-host. Test a restore
   before you need it.
4. **Resource limits** (compose or your orchestrator):

   ```yaml
   deploy:
     resources:
       limits:
         cpus: "1.0"
         memory: 1G
   ```
5. **Run as non-root** (hardening, optional): add a `useradd` + `USER` to the
   Dockerfile and `chown` the data dir.
6. **Observability**: `docker compose logs -f web api`. The app also writes an
   `audit_log` table (admin dashboard → Audit tab) for every sensitive action.

## Local development (no Docker)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/streamlit run mobile_money_system/app.py          # web app on :8501
MMS_API_KEY=change-me .venv/bin/uvicorn mobile_money_system.api:app --reload   # API on :8000
.venv/bin/pytest -q                                          # test suite
.venv/bin/ruff check mobile_money_system/ tests/            # lint
.venv/bin/mypy                                               # typecheck
```

## CI

`.github/workflows/tests.yml` runs the pytest suite on every push.
`.github/workflows/lint.yml` runs ruff + mypy.
