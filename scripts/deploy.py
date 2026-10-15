r"""One-command cloud deployment for MedIntel (free tiers, API-driven).

Orchestrates the full live-app pipeline:
  1. Neon      -> create/reuse free PostgreSQL project, print connection string
  2. Migrate   -> run Alembic locally against Neon (verifies the Postgres path)
  3. Render    -> create/reuse Docker web service (auto-deploy from GitHub),
                  poll the build until live, health-check it
  4. Vercel    -> create/reuse the Next.js project (rootDirectory: frontend),
                  set NEXT_PUBLIC_API_URL, trigger + poll production deploy
  5. Wire CORS -> add the Vercel domain to the backend CORS_ORIGINS env,
                  wait for the automatic Render redeploy
  6. Summary   -> print all live URLs and demo credentials

Idempotent: re-running reuses existing resources instead of duplicating them.

Usage (from repo root, with the backend venv python):
    set NEON_API_KEY=...
    set RENDER_API_KEY=...
    set VERCEL_TOKEN=...
    backend\.venv\Scripts\python scripts\deploy.py

LLM settings (optional) are read from backend/.env if present, so the deployed
app serves LLM-grounded answers; without them it runs in extractive mode.
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

REPO = "yashas0907/medical-document-intelligence"
REPO_URL = f"https://github.com/{REPO}"
BRANCH = "master"

NEON_PROJECT = "medintel"
RENDER_SERVICE = "medintel-yashas-api"
VERCEL_PROJECT = "medintel-yashas"
FRONTEND_ROOT = "frontend"

NEON_KEY = os.environ.get("NEON_API_KEY", "")
RENDER_KEY = os.environ.get("RENDER_API_KEY", "")
VERCEL_KEY = os.environ.get("VERCEL_TOKEN", "")


def log(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def die(msg: str, resp: httpx.Response | None = None) -> None:
    if resp is not None:
        print(f"HTTP {resp.status_code}: {resp.text[:600]}", flush=True)
    raise SystemExit(f"FATAL: {msg}")


def req(method: str, url: str, key: str, json_body=None, params=None,
        timeout: float = 60) -> httpx.Response:
    r = httpx.request(method, url, headers={"Authorization": f"Bearer {key}"}, timeout=timeout,
                      json=json_body, params=params)
    return r


def parse_local_llm_env() -> dict[str, str]:
    """Read LLM_* settings from backend/.env (git-ignored) so the deployed
    app gets LLM-grounded answers without secrets in the repo."""
    out: dict[str, str] = {}
    env_file = BACKEND / ".env"
    if not env_file.exists():
        return out
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip().startswith("LLM_") and v.strip():
            out[k.strip()] = v.strip()
    return out


# ---------------------------------------------------------------------------
# Step 1: Neon PostgreSQL
# ---------------------------------------------------------------------------
def neon_connect_string() -> str:
    log("Step 1: Neon PostgreSQL")
    if not NEON_KEY:
        die("NEON_API_KEY not set (create at neon.com -> Account settings -> API keys)")
    r = req("GET", "https://api.neon.tech/v2/projects", NEON_KEY)
    if r.status_code != 200:
        die("Neon auth/list failed", r)
    for p in r.json().get("projects", []):
        if p["name"] == NEON_PROJECT:
            print(f"  reusing existing project: {p['id']}")
            project_id = p["id"]
            break
    else:
        r = req("POST", "https://api.neon.tech/v2/projects", NEON_KEY,
                json_body={"project": {"name": NEON_PROJECT}}, timeout=120)
        if r.status_code != 201:
            die("Neon project creation failed", r)
        project_id = r.json()["project"]["id"]
        print(f"  project created: {project_id}")

    r = req("GET", f"https://api.neon.tech/v2/projects/{project_id}/connection_uris", NEON_KEY)
    if r.status_code != 200:
        die("Neon connection string fetch failed", r)
    uris = r.json().get("connection_uris") or r.json().get("connection_uri") or []
    if isinstance(uris, str):
        uris = [{"connection_uri": uris}]
    if not uris:
        die("Neon returned no connection URI", r)
    uri = uris[0]["connection_uri"]
    # -> SQLAlchemy dialect; force SSL (Neon requirement)
    uri = re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", uri)
    sep = "&" if "?" in uri else "?"
    if "sslmode=" not in uri:
        uri += f"{sep}sslmode=require"
    print(f"  connection string: {uri[:60]}...")
    return uri


# ---------------------------------------------------------------------------
# Step 2: migrations against Neon (from this machine)
# ---------------------------------------------------------------------------
def migrate(db_url: str) -> None:
    log("Step 2: Alembic migrations on Postgres (run locally)")
    env = {**os.environ, "DATABASE_URL": db_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=600,
    )
    print(result.stdout[-400:] or result.stderr[-400:])
    if result.returncode != 0:
        die(f"alembic failed (exit {result.returncode}) — see output above")
    print("  migrations applied OK")


# ---------------------------------------------------------------------------
# Step 3: Render backend service
# ---------------------------------------------------------------------------
def render_env_vars(db_url: str) -> list[dict[str, str]]:
    llm = parse_local_llm_env()
    envs = {
        "DATABASE_URL": db_url,
        "SECRET_KEY": secrets.token_urlsafe(48),
        "APP_ENV": "prod",
        "STORAGE_ROOT": "/tmp/medintel-storage",
        "OCR_PROVIDER": "auto",
        "EMBEDDING_PROVIDER": "local",
        "CORS_ORIGINS": "http://localhost:3000",  # updated after Vercel is live
        **llm,
    }
    return [{"key": k, "value": v} for k, v in envs.items()]


def render_create_or_reuse(db_url: str) -> tuple[str, str]:
    log("Step 3: Render backend (Docker, free instance)")
    if not RENDER_KEY:
        die("RENDER_API_KEY not set (create at render.com -> Account Settings -> API Keys)")
    r = req("GET", "https://api.render.com/v1/services", RENDER_KEY)
    if r.status_code != 200:
        die("Render auth failed", r)
    for s in (r.json() or []):
        if s.get("name") == RENDER_SERVICE:
            sid = s["id"]
            url = (s.get("serviceDetails") or {}).get("url") or f"https://{RENDER_SERVICE}.onrender.com"
            print(f"  reusing existing service: {sid}")
            return sid, url

    r = req("POST", "https://api.render.com/v1/services", RENDER_KEY, json_body={
        "type": "web",
        "name": RENDER_SERVICE,
        "repo": REPO_URL,
        "branch": BRANCH,
        "autoDeploy": "yes",
        "dockerfilePath": "./backend/Dockerfile",
        "dockerContext": ".",
        "healthCheckPath": "/api/v1/health",
        "instanceType": "free",
        "envVars": render_env_vars(db_url),
    }, timeout=120)
    if r.status_code != 201:
        die("Render service creation failed", r)
    body = r.json()
    sid = body["id"]
    url = (body.get("serviceDetails") or {}).get("url") or f"https://{RENDER_SERVICE}.onrender.com"
    print(f"  service created: {sid}")
    return sid, url


def render_wait_live(sid: str, url: str, timeout_s: int = 900) -> None:
    print("  waiting for build + deploy (first build takes ~5 min)…", flush=True)
    start = time.time()
    last = ""
    while time.time() - start < timeout_s:
        r = req("GET", f"https://api.render.com/v1/services/{sid}/deploys?limit=1", RENDER_KEY)
        if r.status_code == 200:
            deploys = r.json() or []
            if deploys:
                status = deploys[0]["status"]
                if status != last:
                    print(f"    deploy status: {status}", flush=True)
                    last = status
                if status == "live":
                    break
                if status in ("build_failed", "update_failed", "deactivated", "canceled"):
                    die(f"Render deploy ended in '{status}' — check build logs in the dashboard")
        time.sleep(15)
    else:
        die(f"Render deploy did not go live within {timeout_s}s")
    # health check
    for attempt in range(10):
        try:
            h = httpx.get(f"{url}/api/v1/health", timeout=30)
            if h.status_code == 200:
                print(f"  HEALTH OK: {h.json()['status']} (db={h.json()['database']})")
                return
        except Exception:
            pass
        time.sleep(10)
    die("Service live but /api/v1/health never returned 200")


def render_set_cors(sid: str, origins: str) -> None:
    log("Step 5: CORS wiring (backend <- frontend domain)")
    r = req("GET", f"https://api.render.com/v1/services/{sid}/env-vars", RENDER_KEY)
    if r.status_code != 200:
        die("Render env fetch failed", r)
    envs = [{"key": e["key"], "value": e["value"]} for e in r.json()]
    for e in envs:
        if e["key"] == "CORS_ORIGINS":
            e["value"] = origins
    r = req("PUT", f"https://api.render.com/v1/services/{sid}/env-vars", RENDER_KEY,
            json_body=envs, timeout=60)
    if r.status_code not in (200, 201, 204):
        die("Render env update failed", r)
    print(f"  CORS_ORIGINS={origins} — Render redeploying automatically")


# ---------------------------------------------------------------------------
# Step 4: Vercel frontend
# ---------------------------------------------------------------------------
def vercel_deploy(backend_url: str) -> str:
    log("Step 4: Vercel frontend")
    if not VERCEL_KEY:
        die("VERCEL_TOKEN not set (create at vercel.com/account/tokens)")
    H = {"Authorization": f"Bearer {VERCEL_KEY}"}

    # create or reuse project
    r = httpx.get("https://api.vercel.com/v9/projects/medintel-yashas".replace("medintel-yashas", VERCEL_PROJECT),
                  headers=H, timeout=60)
    if r.status_code == 200:
        print(f"  reusing existing project: {VERCEL_PROJECT}")
    else:
        r = httpx.post("https://api.vercel.com/v9/projects", headers=H, timeout=60, json={
            "name": VERCEL_PROJECT,
            "gitRepository": {"type": "github", "repo": REPO},
            "rootDirectory": FRONTEND_ROOT,
        })
        if r.status_code in (200, 201):
            print(f"  project created: {VERCEL_PROJECT}")
        elif "already" in r.text.lower() or r.status_code == 409:
            print(f"  project exists: {VERCEL_PROJECT}")
        else:
            die("Vercel project creation failed", r)

    # NEXT_PUBLIC_API_URL (build-time env for the frontend)
    api_url = f"{backend_url}/api/v1"
    r = httpx.get(f"https://api.vercel.com/v9/projects/{VERCEL_PROJECT}/env", headers=H, timeout=60)
    envs = r.json().get("envs", []) if r.status_code == 200 else []
    existing = next((e for e in envs if e["key"] == "NEXT_PUBLIC_API_URL"), None)
    if existing:
        r = httpx.request("PATCH",
                          f"https://api.vercel.com/v10/projects/{VERCEL_PROJECT}/env/{existing['id']}",
                          headers=H, timeout=60,
                          json={"value": api_url, "target": ["production", "preview"]})
    else:
        r = httpx.post(f"https://api.vercel.com/v10/projects/{VERCEL_PROJECT}/env", headers=H, timeout=60,
                       json={"key": "NEXT_PUBLIC_API_URL", "value": api_url,
                             "target": ["production", "preview"]})
    if r.status_code not in (200, 201):
        die("Vercel env set failed", r)
    print(f"  NEXT_PUBLIC_API_URL={api_url}")

    # trigger production deploy
    r = httpx.post("https://api.vercel.com/v13/deployments", headers=H, timeout=120, json={
        "name": VERCEL_PROJECT,
        "target": "production",
        "gitSource": {"type": "github", "repo": REPO, "ref": BRANCH},
    })
    if r.status_code not in (200, 201):
        die("Vercel deploy trigger failed", r)
    dep = r.json()
    dep_id = dep["id"]
    print(f"  deployment {dep_id} building…", flush=True)

    start = time.time()
    while time.time() - start < 600:
        r = httpx.get(f"https://api.vercel.com/v13/deployments/{dep_id}", headers=H, timeout=60)
        state = r.json().get("readyState") or r.json().get("state")
        if state in ("READY",):
            break
        if state in ("ERROR", "CANCELED"):
            die("Vercel build failed — check vercel.com dashboard")
        time.sleep(10)
    else:
        die("Vercel deploy did not become READY in 10 min")

    r = httpx.get(f"https://api.vercel.com/v9/projects/{VERCEL_PROJECT}/domains", headers=H, timeout=60)
    domains = [d["name"] for d in r.json().get("domains", [])] if r.status_code == 200 else []
    vercel_url = f"https://{domains[0]}" if domains else f"https://{VERCEL_PROJECT}.vercel.app"
    print(f"  frontend live: {vercel_url}")
    return vercel_url


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    log("MedIntel live deployment (free tiers)")
    db_url = neon_connect_string()
    migrate(db_url)
    sid, backend_url = render_create_or_reuse(db_url)
    render_wait_live(sid, backend_url)

    vercel_url = vercel_deploy(backend_url)
    render_set_cors(sid, f"{vercel_url},http://localhost:3000")

    # wait for the CORS redeploy to finish
    log("Step 6: final verification")
    time.sleep(20)
    render_wait_live(sid, backend_url)

    print("\n" + "=" * 60)
    print("DEPLOYED:")
    print(f"  Frontend : {vercel_url}")
    print(f"  Backend  : {backend_url}/api/v1  (docs: {backend_url}/api/docs)")
    print(f"  Database : Neon PostgreSQL ({NEON_PROJECT})")
    print(f"  Demo login: demo@medintel.local / demo-password")
    print("  Note: free-tier backend sleeps after 15 min idle;")
    print("        the first request takes ~1 min to wake it.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
