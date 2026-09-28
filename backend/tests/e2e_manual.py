"""Full-stack E2E verification over real HTTP.

Journey: register → login → upload fixture → poll status → ask (citations) →
summarize → compare two docs → timeline → OCR doc → health → runs.
Exit code 0 = all passed.
"""
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000/api/v1"
FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures"

ok = 0
fail = 0


def check(name: str, cond: bool, extra: str = ""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS {name} {extra}")
    else:
        fail += 1
        print(f"  FAIL {name} {extra}")


def wait_doc(c, headers, doc_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = c.get(f"{BASE}/documents/{doc_id}/status", headers=headers)
        s = r.json()
        if s["status"] in ("completed", "failed"):
            return s
        time.sleep(0.5)
    raise RuntimeError(f"timeout: {s}")


def main():
    c = httpx.Client(timeout=120)

    print("== register/login ==")
    r = c.post(f"{BASE}/auth/register", json={"email": "e2e@medintel.local", "password": "E2e-passw0rd!"})
    check("register", r.status_code == 201, f"({r.status_code})")
    r = c.post(f"{BASE}/auth/login", json={"email": "e2e@medintel.local", "password": "E2e-passw0rd!"})
    check("login", r.status_code == 200)
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    print("== health ==")
    r = c.get(f"{BASE}/health")
    body = r.json()
    check("health", r.status_code == 200 and body["database"] and body["storage"],
          f"llm={body['llm']['enabled']}")

    print("== upload lab visit 1 ==")
    with open(FIXTURES / "lab_report_visit1.txt", "rb") as f:
        r = c.post(f"{BASE}/documents", files={"file": ("v1.txt", f, "text/plain")}, headers=headers)
    check("upload", r.status_code == 201, f"({r.status_code})")
    a_id = r.json()["id"]
    s = wait_doc(c, headers, a_id)
    check("processed", s["status"] == "completed",
          f"chunks={s['chunks']} entities={s['entities']} meas={s['measurements']}")

    print("== upload lab visit 2 ==")
    with open(FIXTURES / "lab_report_visit2.txt", "rb") as f:
        r = c.post(f"{BASE}/documents", files={"file": ("v2.txt", f, "text/plain")}, headers=headers)
    b_id = r.json()["id"]
    s2 = wait_doc(c, headers, b_id)
    check("processed v2", s2["status"] == "completed")

    print("== upload scanned pdf (OCR path) ==")
    with open(FIXTURES / "scanned_lab_report.pdf", "rb") as f:
        r = c.post(f"{BASE}/documents", files={"file": ("scan.pdf", f, "application/pdf")}, headers=headers)
    scan_id = r.json()["id"]
    s3 = wait_doc(c, headers, scan_id)
    check("scanned processed", s3["status"] == "completed", f"pages={s3['page_count']}")
    if s3["status"] == "completed":
        r = c.get(f"{BASE}/documents/{scan_id}/pages", headers=headers)
        pg = r.json()[0]
        check("ocr page method", pg["extraction_method"] == "ocr", f"conf={pg['ocr_confidence']}")
        check("ocr text contains glucose", "Glucose" in pg["text"], pg["text"][:60])

    print("== ask with citations ==")
    r = c.post(f"{BASE}/documents/{a_id}/ask", json={"question": "What medications are mentioned?"}, headers=headers)
    body = r.json()
    check("ask 200", r.status_code == 200)
    check("answer has metformin", "metformin" in body["answer"].lower(), body["answer"][:80])
    check("cited", len(body["citations"]) >= 1 and body["groundedness"] >= 0.5,
          f"groundedness={body['groundedness']} cites={len(body['citations'])}")
    check("citation has quote+page", bool(body["citations"][0]["quote"]) and body["citations"][0]["page_number"])

    r = c.post(f"{BASE}/documents/{a_id}/ask", json={"question": "What was the potassium level?"}, headers=headers)
    body = r.json()
    check("refuses unanswerable", body["insufficient_evidence"] is True, body["answer"][:70])

    print("== summary ==")
    r = c.post(f"{BASE}/documents/{a_id}/summarize", json={"mode": "structured"}, headers=headers)
    body = r.json()
    labels = {sec["label"]: sec["content"] for sec in body["sections"]}
    check("structured summary", r.status_code == 200 and "Not found in the document." in labels.get("Procedures mentioned", ""),
          labels.get("Medications mentioned", "")[:60])

    print("== compare ==")
    r = c.post(f"{BASE}/documents/compare", json={"document_a_id": a_id, "document_b_id": b_id}, headers=headers)
    body = r.json()
    changed = [row for row in body["rows"] if row["change_type"] == "changed"]
    check("comparison", r.status_code == 200 and len(changed) >= 3, f"changed={len(changed)}")

    print("== contradictions ==")
    r = c.post(f"{BASE}/documents/{a_id}/contradictions?compare_with={b_id}", headers=headers)
    body = r.json()
    check("contradictions", r.status_code == 200 and len(body["contradictions"]) >= 3,
          f"n={len(body['contradictions'])}")

    print("== timeline ==")
    r = c.get(f"{BASE}/documents/{a_id}/timeline", headers=headers)
    check("timeline", r.status_code == 200 and len(r.json()["events"]) >= 2)

    print("== observability ==")
    r = c.get(f"{BASE}/runs", headers=headers)
    runs = r.json()
    kinds = {run["kind"] for run in runs}
    check("model runs recorded", {"extract", "entities", "chunk", "ask"} <= kinds, str(sorted(kinds)))

    print("== unauthorized access ==")
    r = c.post(f"{BASE}/auth/register", json={"email": "e2e2@medintel.local", "password": "E2e-passw0rd!"})
    r = c.post(f"{BASE}/auth/login", json={"email": "e2e2@medintel.local", "password": "E2e-passw0rd!"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = c.get(f"{BASE}/documents/{a_id}", headers=other)
    check("isolation enforced", r.status_code in (403, 404), f"({r.status_code})")

    print(f"\n== E2E RESULT: {ok} passed, {fail} failed ==")
    c.close()
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
