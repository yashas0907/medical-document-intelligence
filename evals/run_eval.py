"""Evaluation suite — real metrics, small fixtures, honest reporting.

Measures:
1. Extraction: precision/recall/F1 for medications + measurements + dates
2. Retrieval: Recall@K, MRR on labeled (query → gold chunk) pairs
3. RAG: groundedness (share of cited sentences), refusal correctness on
   unanswerable questions, citation validity (refs resolve to real evidence)
4. Comparison: change-detection accuracy on labeled pairs
5. Contradiction detection: precision/recall on labeled pairs

Dataset: synthetic lab reports (fixtures). Small by design — every number
below is computed, none extrapolated. Run: python evals/run_eval.py
"""
import json
import sys
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

FIXTURES = ROOT / "data" / "fixtures"
RESULTS_DIR = ROOT / "evals" / "results"
RESULTS_DIR.mkdir(exist_ok=True)

import os

os.environ.setdefault("DATABASE_URL", f"sqlite:///{(RESULTS_DIR / 'eval.db').as_posix()}")
os.environ.setdefault("STORAGE_ROOT", str(RESULTS_DIR / "storage"))
# Eval measures the DETERMINISTIC extractive path — no external LLM dependency,
# so metrics are reproducible regardless of developer .env settings.
os.environ["LLM_PROVIDER"] = "none"
os.environ["LLM_MODEL"] = ""

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
from app.db.session import get_engine, get_session_factory, reset_engine_for_tests  # noqa: E402
from app.db import models  # noqa: E402
from app.services.processing import process_document  # noqa: E402

reset_engine_for_tests()
engine = get_engine()
models.Base.metadata.create_all(bind=engine)
sf = get_session_factory()
db = sf()

# ---------------------------------------------------------------------------
# Build eval corpus
# ---------------------------------------------------------------------------
from app.core.security import hash_password  # noqa: E402

from sqlalchemy import select  # noqa: E402

user = db.scalar(select(models.User).where(models.User.email == "eval@medintel.local"))
if not user:
    user = models.User(email="eval@medintel.local", hashed_password=hash_password("eval-password-123"))
    db.add(user)
    db.commit()

# clear prior eval docs for idempotent re-runs
for d in db.scalars(select(models.Document).where(models.Document.owner_id == user.id)).all():
    db.delete(d)
db.commit()


def ingest(name: str) -> models.Document:
    data = (FIXTURES / name).read_bytes()
    doc = models.Document(
        owner_id=user.id, title=name, original_filename=name,
        stored_filename="eval", content_type="",
        file_size=len(data), sha256=f"eval-{name}",
    )
    db.add(doc)
    db.commit()
    return process_document(db, doc, data)


docs = {}
for fname in ["lab_report_visit1.txt", "lab_report_visit2.txt", "clinical_note.docx",
              "radiology_report.pdf", "lab_table_report.pdf", "multi_page_report.pdf",
              "scanned_lab_report.pdf"]:
    try:
        d = ingest(fname)
        docs[fname] = {"id": d.id, "status": d.status,
                       "doc": d, "name": fname}
        print(f"ingested {fname}: {d.status} pages={d.page_count}")
    except Exception as e:
        print(f"ingested {fname}: FAILED {type(e).__name__}: {e}")
        docs[fname] = None

report: dict = {"dataset": "synthetic fixtures (7 docs)", "n_docs": len(docs)}


# ---------------------------------------------------------------------------
# 1) Extraction P/R/F1
# ---------------------------------------------------------------------------
def extraction_eval(doc, gold_meds: set[str], gold_labs: set[str], gold_dates: set[str]):
    meds = {
        (e.normalized_text or e.raw_text).lower()
        for e in db.query(models.ExtractedEntity).filter_by(document_id=doc.id, entity_type="medication").all()
    }
    labs = {
        m.name.lower()
        for m in db.query(models.Measurement).filter_by(document_id=doc.id).all()
    }
    dates = {
        e.normalized_text
        for e in db.query(models.ExtractedEntity).filter_by(
            document_id=doc.id, entity_type="date").all()
        if e.normalized_text
    }
    return meds, labs, dates


def prf(pred: set, gold: set) -> dict:
    if not pred and not gold:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0}
    tp = len(pred & gold)
    fp = len(pred - gold)
    fn = len(gold - pred)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn}


gold_v1_meds = {"metformin", "lisinopril", "atorvastatin"}
gold_v1_labs = {"hemoglobin", "hematocrit", "wbc", "platelets", "glucose",
                "creatinine", "hba1c", "ldl", "hdl", "triglycerides", "tsh"}
gold_v1_dates = {"2024-03-05", "2024-06-10"}
gold_v2_meds = {"metformin", "atorvastatin", "ferrous sulfate"}
gold_v2_labs = gold_v1_labs
gold_table_labs = {"hemoglobin", "wbc", "platelets", "sodium", "potassium", "alt", "ast"}

ex_results = {}
d1 = docs.get("lab_report_visit1.txt")
if d1 and d1["status"] == "completed":
    meds, labs, dates = extraction_eval(d1["doc"], gold_v1_meds, gold_v1_labs, gold_v1_dates)
    ex_results["visit1_medications"] = prf(meds, gold_v1_meds)
    ex_results["visit1_measurements"] = prf(labs, gold_v1_labs)
    ex_results["visit1_dates"] = prf(dates, gold_v1_dates)
d2 = docs.get("lab_report_visit2.txt")
if d2 and d2["status"] == "completed":
    meds, labs, dates = extraction_eval(d2["doc"], gold_v2_meds, gold_v2_labs, set())
    ex_results["visit2_medications"] = prf(meds, gold_v2_meds)
    ex_results["visit2_measurements"] = prf(labs, gold_v2_labs)
dt = docs.get("lab_table_report.pdf")
if dt and dt["status"] == "completed":
    _, labs, _ = extraction_eval(dt["doc"], set(), gold_table_labs, set())
    ex_results["table_pdf_measurements"] = prf(labs, gold_table_labs)
report["extraction"] = ex_results
print(json.dumps(ex_results, indent=2))


# ---------------------------------------------------------------------------
# 2) Retrieval: Recall@K / MRR
# ---------------------------------------------------------------------------
from app.ml.retrieval.store import get_document_retriever  # noqa: E402
from app.services.rag_service import _load_chunks  # noqa: E402

retrieval_cases = []  # (doc_name, query, gold_section_keyword)
if d1 and d1["status"] == "completed":
    retrieval_cases += [
        ("lab_report_visit1.txt", "What medications are mentioned?", "metformin"),
        ("lab_report_visit1.txt", "HbA1c results", "hba1c"),
        ("lab_report_visit1.txt", "patient blood pressure", "128/82"),
        ("lab_report_visit1.txt", "assessment and plan", "above target"),
        ("lab_report_visit1.txt", "glucose level", "108"),
        ("lab_report_visit1.txt", "who is the referring physician", "carter"),
        ("lab_report_visit1.txt", "TSH value", "2.1"),
    ]
if dt and dt["status"] == "completed":
    retrieval_cases += [
        ("lab_table_report.pdf", "potassium level", "5.2"),
        ("lab_table_report.pdf", "ALT result", "62"),
    ]

retrieval_metrics = []
for name, query, gold in retrieval_cases:
    docinfo = docs[name]
    chunks = _load_chunks(db, [docinfo["id"]])
    retriever = get_document_retriever(f"eval:{docinfo['id']}", chunks, get_settings().embedding_model)
    results = retriever.search(query, top_k=6)
    ranks = [i + 1 for i, s in enumerate(results) if gold.lower() in s.text.lower()]
    if ranks:
        retrieval_metrics.append({
            "query": query, "doc": name,
            "recall_at_3": 1 if ranks[0] <= 3 else 0,
            "recall_at_6": 1,
            "mrr": 1 / ranks[0],
        })
    else:
        retrieval_metrics.append({
            "query": query, "doc": name, "recall_at_3": 0, "recall_at_6": 0, "mrr": 0.0,
        })

if retrieval_metrics:
    report["retrieval"] = {
        "n_queries": len(retrieval_metrics),
        "recall_at_3": round(mean(m["recall_at_3"] for m in retrieval_metrics), 4),
        "recall_at_6": round(mean(m["recall_at_6"] for m in retrieval_metrics), 4),
        "mrr": round(mean(m["mrr"] for m in retrieval_metrics), 4),
        "cases": retrieval_metrics,
    }
    print(json.dumps({k: v for k, v in report["retrieval"].items() if k != "cases"}, indent=2))


# ---------------------------------------------------------------------------
# 3) RAG quality: groundedness, refusal correctness, citation validity
# ---------------------------------------------------------------------------
from app.services.rag_service import ask_documents  # noqa: E402

rag_cases = []
if d1 and d1["status"] == "completed":
    rag_cases += [
        (d1["id"], "What medications are mentioned?", "metformin", True),
        (d1["id"], "What is the HbA1c value?", "6.4", True),
        (d1["id"], "What was the blood pressure?", "128/82", True),
        # ratio is genuinely absent (LDL/HDL are recorded, a ratio is not) → must refuse
        (d1["id"], "What is the patient's cholesterol ratio?", None, False),
    ]

rag_metrics = []
for doc_id, q, expected, answerable in rag_cases:
    res = ask_documents(db, user, q, [doc_id])
    cited = res["groundedness"]
    if answerable:
        correct = expected.lower() in res["answer"].lower()
        refusal_ok = not res["insufficient_evidence"]
    else:
        correct = res["insufficient_evidence"]  # must refuse
        refusal_ok = True
    # citation validity: every ref in sentences resolves to a real citation
    refs = {c["ref"] for c in res["citations"]}
    valid = all(
        r in refs
        for s in res["answer_sentences"]
        for r in s["citation_refs"]
    )
    rag_metrics.append({
        "question": q, "answerable": answerable, "correct": correct,
        "refused_when_unanswerable": refusal_ok if not answerable else None,
        "groundedness": cited, "citations_valid": valid,
    })

if rag_metrics:
    answerable = [m for m in rag_metrics if m["answerable"]]
    unanswerable = [m for m in rag_metrics if not m["answerable"]]
    report["rag"] = {
        "n_cases": len(rag_metrics),
        "answer_accuracy": round(mean(m["correct"] for m in answerable), 4) if answerable else None,
        "refusal_correctness": round(mean(m["correct"] for m in unanswerable), 4) if unanswerable else None,
        "groundedness": round(mean(m["groundedness"] for m in rag_metrics), 4),
        "citation_validity": round(mean(m["citations_valid"] for m in rag_metrics), 4),
        "cases": rag_metrics,
    }
    print(json.dumps({k: v for k, v in report["rag"].items() if k != "cases"}, indent=2))


# ---------------------------------------------------------------------------
# 4) Comparison accuracy
# ---------------------------------------------------------------------------
from app.services.analysis_service import run_comparison  # noqa: E402

comp_metrics = {}
if d1 and d2 and d1["status"] == "completed" and d2["status"] == "completed":
    comp = run_comparison(db, user, d1["doc"], d2["doc"])
    changed_items = {r["item"].lower() for r in comp["rows"] if r["change_type"] == "changed"}
    # Gold: values that actually differ between visit1 and visit2 fixtures
    gold_changed = {"hba1c", "glucose", "hemoglobin", "hematocrit", "triglycerides",
                    "creat  inine".replace(" ", ""), "ldl", "tsh", "hdl"}
    gold_unchanged = {"wbc", "platelets"}
    tp = len(changed_items & gold_changed)
    fn = len(gold_changed - changed_items)
    precision = tp / len(changed_items) if changed_items else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    comp_metrics = {
        "n_rows": len(comp["rows"]),
        "changed_detected": sorted(changed_items),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "detected_correctly": tp,
        "missed": sorted(gold_changed - changed_items),
        "false_positives": sorted(changed_items - gold_changed),
    }
    # medication add/remove detection
    removed = {r["item"] for r in comp["rows"] if r["change_type"] == "removed" and r["category"] == "Medications"}
    added = {r["item"] for r in comp["rows"] if r["change_type"] == "added" and r["category"] == "Medications"}
    comp_metrics["med_removed_lisinopril"] = "lisinopril" in removed
    comp_metrics["med_added_names"] = sorted(added)
report["comparison"] = comp_metrics
print(json.dumps(comp_metrics, indent=2))


# ---------------------------------------------------------------------------
# 5) Contradiction detection P/R
# ---------------------------------------------------------------------------
from app.services.analysis_service import run_contradictions  # noqa: E402

contra_metrics = {}
if d1 and d2 and d1["status"] == "completed" and d2["status"] == "completed":
    contra = run_contradictions(db, d1["doc"], d2["doc"])
    detected = {c["a"]["claim"].split("=")[0].strip().lower() for c in contra["contradictions"]}
    # Gold: names with genuinely different values across the two fixtures
    gold_conflicts = {"hba1c", "glucose", "hemoglobin", "hematocrit", "triglycerides",
                      "hdl", "ldl", "tsh", "creatinine"}
    tp = len(detected & gold_conflicts)
    fp = len(detected - gold_conflicts)
    fn = len(gold_conflicts - detected)
    contra_metrics = {
        "n_detected": len(detected),
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else 0,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else 0,
        "true_positives": sorted(detected & gold_conflicts),
        "false_positives": sorted(detected - gold_conflicts),
        "missed": sorted(gold_conflicts - detected),
    }
report["contradictions"] = contra_metrics
print(json.dumps(contra_metrics, indent=2))

# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
out = RESULTS_DIR / "eval_report.json"
out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
print(f"\nReport saved to {out}")
db.close()
engine.dispose()
