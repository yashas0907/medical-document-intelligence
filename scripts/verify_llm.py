"""Post-setup verification for LLM mode (run with backend live + LLM configured).

Checks: health shows LLM enabled -> ask returns an llm-grounded answer with
valid citations -> refusal still refuses (the LLM never overrides the
evidence gate) -> model_runs recorded for observability.

Usage:  python scripts/verify_llm.py   (backend must be running on :8000)
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"

c = httpx.Client(timeout=120)
r = c.get(f"{BASE}/health").json()
print("health | llm enabled:", r["llm"]["enabled"], "| provider:", r["llm"]["provider"],
      "| model:", r["llm"]["model"])

r = c.post(f"{BASE}/auth/login", json={"email": "demo@medintel.local", "password": "demo-password"})
h = {"Authorization": "Bearer " + r.json()["access_token"]}
docs = c.get(f"{BASE}/documents", headers=h).json()
doc = next(d for d in docs if "City General" in d["title"])
print("doc:", doc["title"], "|", doc["id"][:8])

# --- LLM-grounded answer ---
t0 = time.perf_counter()
r = c.post(f"{BASE}/documents/{doc['id']}/ask",
           json={"question": "What medications are mentioned and at what doses?"}, headers=h)
ms = (time.perf_counter() - t0) * 1000
body = r.json()
print(f"\nASK ({body['method']}, {ms:.0f}ms)")
print("answer:", body["answer"][:400])
print("groundedness:", body["groundedness"], "| citations:", len(body["citations"]))
refs = {cit["ref"] for cit in body["citations"]}
used = {ref for s in body["answer_sentences"] for ref in s["citation_refs"]}
print("citation refs valid:", used <= refs)
for cit in body["citations"][:2]:
    print(f"   {cit['ref']} p.{cit['page_number']} | {cit['quote'][:80]}...")

# --- refusal must still refuse (LLM never overrides the validator) ---
r = c.post(f"{BASE}/documents/{doc['id']}/ask",
           json={"question": "What is the patient's cholesterol ratio?"}, headers=h)
body = r.json()
print(f"\nREFUSAL | insufficient_evidence={body['insufficient_evidence']}")
print("answer:", body["answer"][:150])

# --- model run recorded ---
runs = c.get(f"{BASE}/runs?kind=ask", headers=h).json()
kinds = [(x["provider"], x["model"], x["success"]) for x in runs[:4]]
print("\nmodel_runs:", kinds)
c.close()
