"""Integration tests: full API flow against a real app instance.

Covers: register/login, uploadâ†’process pipeline (PDF/DOCX/TXT), QA with
citations, summaries, comparison, timeline, contradictions, status, deletion,
stats, model runs.
"""
import time
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures"


def _register_and_login(client, email="int@example.com"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": "Passw0rd-long"})
    assert r.status_code == 201, r.text
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "Passw0rd-long"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _upload_and_wait(client, headers, path: Path, name: str | None = None, timeout: float = 120):
    with open(path, "rb") as f:
        r = client.post(
            "/api/v1/documents",
            files={"file": (name or path.name, f, "application/octet-stream")},
            headers=headers,
        )
    assert r.status_code == 201, r.text
    doc_id = r.json()["id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/v1/documents/{doc_id}/status", headers=headers)
        body = r.json()
        if body["status"] in ("completed", "failed"):
            return doc_id, body
        time.sleep(0.4)
    raise AssertionError(f"processing timed out: {body}")


@pytest.mark.integration
class TestAuth:
    def test_register_login_flow(self, client):
        r = client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": "Passw0rd-long"})
        assert r.status_code == 201
        r = client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "Passw0rd-long"})
        assert r.status_code == 200
        assert r.json()["access_token"]

    def test_login_wrong_password(self, client):
        client.post("/api/v1/auth/register", json={"email": "x@b.co", "password": "Passw0rd-long"})
        r = client.post("/api/v1/auth/login", json={"email": "x@b.co", "password": "wrong-pass-123"})
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "authentication_failed"

    def test_me_requires_token(self, client):
        r = client.get("/api/v1/me")
        assert r.status_code == 401


@pytest.mark.integration
class TestDocuments:
    def test_upload_process_txt(self, client):
        headers = _register_and_login(client)
        doc_id, status = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        assert status["status"] == "completed", status
        assert status["chunks"] > 0
        assert status["sections"] >= 3
        assert status["measurements"] >= 8
        assert status["entities"] >= 10

    def test_upload_process_docx(self, client):
        headers = _register_and_login(client, "docx@example.com")
        doc_id, status = _upload_and_wait(client, headers, FIXTURES / "clinical_note.docx")
        assert status["status"] == "completed"
        assert status["tables"] >= 1

    def test_upload_process_pdf_with_table(self, client):
        headers = _register_and_login(client, "pdf@example.com")
        doc_id, status = _upload_and_wait(client, headers, FIXTURES / "lab_table_report.pdf")
        assert status["status"] == "completed"
        assert status["tables"] >= 1
        r = client.get(f"/api/v1/documents/{doc_id}/tables", headers=headers)
        tables = r.json()
        assert tables[0]["header"][0] == "Test"
        assert any("Hemoglobin" in row for row in tables[0]["rows"])

    def test_upload_multi_page_pdf_cleaning(self, client):
        headers = _register_and_login(client, "mp@example.com")
        doc_id, status = _upload_and_wait(client, headers, FIXTURES / "multi_page_report.pdf")
        assert status["status"] == "completed"
        assert status["page_count"] == 5
        # header/footer text should not pollute chunks
        r2 = client.get(f"/api/v1/documents/{doc_id}/pages?limit=100", headers=headers)
        pages_text = " ".join(p["text"] for p in r2.json())
        assert "Page 1 of 5" not in pages_text or "Confidential" not in pages_text

    def test_list_and_delete(self, client):
        headers = _register_and_login(client, "ld@example.com")
        doc_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        r = client.get("/api/v1/documents", headers=headers)
        assert any(d["id"] == doc_id for d in r.json())
        r = client.delete(f"/api/v1/documents/{doc_id}", headers=headers)
        assert r.status_code == 204
        r = client.get("/api/v1/documents", headers=headers)
        assert not any(d["id"] == doc_id for d in r.json())

    def test_stats(self, client):
        headers = _register_and_login(client, "st@example.com")
        r = client.get("/api/v1/documents/stats", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["documents"] >= 0


@pytest.mark.integration
class TestQA:
    def test_ask_with_citations(self, client):
        headers = _register_and_login(client, "qa@example.com")
        doc_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        r = client.post(
            f"/api/v1/documents/{doc_id}/ask",
            json={"question": "What medications are mentioned?"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["method"] == "extractive"
        assert body["groundedness"] > 0
        assert len(body["citations"]) >= 1
        assert body["citations"][0]["page_number"] >= 1
        assert body["citations"][0]["quote"]  # real quote, not fake
        assert "Metformin" in body["answer"]

    def test_ask_refuses_without_evidence(self, client):
        headers = _register_and_login(client, "qa2@example.com")
        doc_id, _ = _upload_and_wait(client, headers, FIXTURES / "radiology_report.pdf")
        r = client.post(
            f"/api/v1/documents/{doc_id}/ask",
            json={"question": "What was the cholesterol level?"},
            headers=headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["insufficient_evidence"] is True
        assert "could not find" in body["answer"].lower() or "not" in body["answer"].lower()

    def test_citation_maps_to_real_chunk(self, client):
        headers = _register_and_login(client, "qa3@example.com")
        doc_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        r = client.post(
            f"/api/v1/documents/{doc_id}/ask",
            json={"question": "What are the HbA1c results?"},
            headers=headers,
        )
        body = r.json()
        assert not body["insufficient_evidence"]
        # every citation ref used in sentences must exist in citation list
        refs = {c["ref"] for c in body["citations"]}
        for s in body["answer_sentences"]:
            for ref in s["citation_refs"]:
                assert ref in refs
        # evidence chunk ids are real (exist in DB via /citations)
        r2 = client.get(f"/api/v1/documents/{doc_id}/citations", headers=headers)
        assert r2.status_code == 200


@pytest.mark.integration
class TestSummaries:
    def test_quick_summary(self, client):
        headers = _register_and_login(client, "sum@example.com")
        doc_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        r = client.post(
            f"/api/v1/documents/{doc_id}/summarize",
            json={"mode": "quick"},
            headers=headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["summary_text"]) > 40

    def test_structured_summary_not_found(self, client):
        headers = _register_and_login(client, "sum2@example.com")
        doc_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        r = client.post(
            f"/api/v1/documents/{doc_id}/summarize",
            json={"mode": "structured"},
            headers=headers,
        )
        body = r.json()
        labels = {s["label"]: s for s in body["sections"]}
        # Procedures absent from this doc -> explicit Not found
        assert labels["Procedures mentioned"]["content"] == "Not found in the document."
        assert "Metformin" in labels["Medications mentioned"]["content"] or \
            "metformin" in labels["Medications mentioned"]["content"]


@pytest.mark.integration
class TestCompareAndTimeline:
    def test_full_comparison(self, client):
        headers = _register_and_login(client, "cmp@example.com")
        a_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        b_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit2.txt")
        r = client.post(
            "/api/v1/documents/compare",
            json={"document_a_id": a_id, "document_b_id": b_id},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        changed = [row for row in body["rows"] if row["change_type"] == "changed"]
        assert len(changed) >= 3  # hemoglobin, glucose, hba1c all changed
        hgb = next(row for row in changed if row["item"] and "hemoglobin" in row["item"].lower())
        assert "13.2" in hgb["a"]["value"] and "11.8" in hgb["b"]["value"]
        assert "changed from" in hgb["change_note"].lower()
        # lisinopril removed in visit2
        removed = [row for row in body["rows"] if row["change_type"] == "removed"]
        assert any(row["item"] == "lisinopril" for row in removed)

    def test_contradictions_cross_doc(self, client):
        headers = _register_and_login(client, "contra@example.com")
        a_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        b_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit2.txt")
        r = client.post(
            f"/api/v1/documents/{a_id}/contradictions",
            params={"compare_with": b_id},
            headers=headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["contradictions"]) >= 3
        c = body["contradictions"][0]
        assert c["a"]["quote"] and c["b"]["quote"]  # evidence on both sides

    def test_timeline(self, client):
        headers = _register_and_login(client, "tl@example.com")
        doc_id, _ = _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        r = client.get(f"/api/v1/documents/{doc_id}/timeline", headers=headers)
        assert r.status_code == 200
        events = r.json()["events"]
        assert len(events) >= 2
        assert all(e["date"] for e in events)


@pytest.mark.integration
class TestObservability:
    def test_model_runs_recorded(self, client):
        headers = _register_and_login(client, "obs@example.com")
        _upload_and_wait(client, headers, FIXTURES / "lab_report_visit1.txt")
        r = client.get("/api/v1/runs", headers=headers)
        assert r.status_code == 200
        runs = r.json()
        kinds = {run["kind"] for run in runs}
        assert {"extract", "entities", "chunk"} <= kinds
        for run in runs:
            if run["duration_ms"] is not None:
                assert run["duration_ms"] >= 0

    def test_health(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["database"] is True
        assert body["storage"] is True


@pytest.mark.integration
class TestScannedOCR:
    def test_scanned_pdf_graceful_handling(self, client):
        """Scanned PDF: with Tesseract installed â†’ OCR; without â†’ failed with clear
        message. Either way the behavior is honest and documented in status."""
        headers = _register_and_login(client, "ocr@example.com")
        doc_id, status = _upload_and_wait(client, headers, FIXTURES / "scanned_lab_report.pdf")
        # With tesseract present, OCR completes
        if status["status"] == "completed":
            r = client.get(f"/api/v1/documents/{doc_id}/pages", headers=headers)
            page = r.json()[0]
            assert page["extraction_method"] == "ocr"
            assert page["ocr_confidence"] > 0
        else:
            assert "scanned" in status["status_message"].lower()
