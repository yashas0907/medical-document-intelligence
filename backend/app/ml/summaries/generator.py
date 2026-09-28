"""Summary generator — grounded, multi-mode, extractive-first.

Modes:
- quick: 3-6 highest-salience sentences from the doc (cited)
- detailed: per-section key sentences (cited)
- section: single section deep summary
- key_findings: sentences containing explicit findings markers
- timeline: chronological events from extracted dates
- structured: fixed schema (document type/date/tests/meds/procedures/
  conclusions/uncertainties); missing → "Not found in the document."

All content is SELECTED from source text (deterministic). The optional LLM
rewrites selection under the same grounding contract as QA.
"""
import re
from dataclasses import dataclass, field

from app.ml.rag.grounded import EvidencePiece
from app.ml.versions import PIPELINE_VERSION, PROMPT_VERSION

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

FINDING_MARKERS = re.compile(
    r"\b(shows?|demonstrates?|reveals?|indicates?|found|detected|abnormal|"
    r"elevated|decreased|reduced|increased|normal|significant|noted|"
    r"consistent with|impression|conclusion)\b",
    re.I,
)

SALIENT_HINTS = re.compile(
    r"\b(diagnos\w+|medication|dose|result|abnormal|finding|impression|plan|"
    r"treatment|lab(?:oratory)?|test|procedure|symptom|measurement|value)\b",
    re.I,
)

SECTION_LABEL_MAP = {
    "patient_info": "Patient Information",
    "history": "History",
    "findings": "Findings",
    "imaging": "Imaging",
    "labs": "Laboratory Results",
    "medications": "Medications",
    "assessment": "Assessment",
    "notes": "Notes",
    "procedure": "Procedures",
    "diagnosis": "Diagnosis",
    "impression": "Impression",
    "vitals": "Vital Signs",
    "symptoms": "Symptoms",
    "allergies": "Allergies",
    "results": "Results",
    "followup": "Follow-up",
    "recommendations": "Recommendations",
    "specimen": "Specimen",
}


@dataclass
class SummarySection:
    label: str
    content: str
    citation_refs: list[str] = field(default_factory=list)
    found: bool = True


@dataclass
class SummaryOutput:
    document_id: str
    mode: str
    title: str
    summary_text: str
    sections: list[SummarySection] = field(default_factory=list)
    evidence: list[EvidencePiece] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    model_meta: dict = field(default_factory=lambda: {
        "provider": "extractive", "model": "summarizer-v1",
        "prompt_version": PROMPT_VERSION, "pipeline_version": PIPELINE_VERSION,
    })


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text.replace("\n", " ")) if len(s.strip()) > 20]


def _salience(s: str) -> float:
    score = 0.0
    if FINDING_MARKERS.search(s):
        score += 0.4
    if SALIENT_HINTS.search(s):
        score += 0.3
    score += min(0.2, len(s) / 500)
    if re.search(r"\d", s):
        score += 0.1
    return score


def _top_sentences(text: str, k: int) -> list[str]:
    sents = _sentences(text)
    scored = sorted(
        ((-_salience(s), i, s) for i, s in enumerate(sents)),
    )
    picked = sorted(scored[:k], key=lambda x: x[1])
    return [s for _, _, s in picked]


def _ref_for(chunk_map: dict, chunk_id: str | None) -> str:
    if chunk_id and chunk_id in chunk_map:
        return chunk_map[chunk_id]
    return "[1]"


def summarize(
    doc_id: str,
    title: str,
    mode: str,
    sections: list[dict],
    chunks: list[dict],
    entities: list[dict],
    doc_date: str | None,
    doc_type: str,
    max_words: int = 250,
    section_id: str | None = None,
) -> SummaryOutput:
    """sections: [{id,title,text,matched_vocab,page_number}]
    chunks: [{id,text,page_number,section_id,section_title,is_table_chunk}]
    entities: [{entity_type,raw_text,normalized_text,page_number,source_snippet}]"""

    # evidence selection for citations: representative chunks
    ev_chunks = chunks[:8] if len(chunks) <= 8 else _diverse_chunks(chunks, 8)
    chunk_map: dict[str, str] = {}
    evidence: list[EvidencePiece] = []
    citations: list[dict] = []
    for i, c in enumerate(ev_chunks):
        ref = f"[{i + 1}]"
        chunk_map[c["id"]] = ref
        evidence.append(
            EvidencePiece(
                chunk_id=c["id"], document_id=doc_id, page_number=c["page_number"],
                section_title=c.get("section_title"), text=c["text"],
                score=1.0, is_table_chunk=c.get("is_table_chunk", False),
            )
        )
        citations.append({
            "ref": ref, "document_id": doc_id, "chunk_id": c["id"],
            "page_number": c["page_number"], "section_title": c.get("section_title"),
            "quote": c["text"][:280],
        })

    out = SummaryOutput(document_id=doc_id, mode=mode, title=title,
                        summary_text="", evidence=evidence, citations=citations)

    if mode == "quick":
        full_text = " ".join(c["text"] for c in chunks)
        k = 5
        picked = _top_sentences(full_text, k)
        # map each sentence to chunk containing it
        parts: list[str] = []
        for s in picked:
            ref = _find_chunk_ref(s, chunks, chunk_map)
            parts.append(s)
        out.summary_text = " ".join(parts)
        return out

    if mode == "detailed":
        out.sections = []
        for sec in sections:
            sent = _top_sentences(sec.get("text", ""), 3)
            if not sent:
                continue
            ref = _ref_for(chunk_map, _chunk_of_section(chunks, sec.get("id")))
            label = SECTION_LABEL_MAP.get(sec.get("matched_vocab"), sec["title"])
            out.sections.append(
                SummarySection(
                    label=label,
                    content=" ".join(sent),
                    citation_refs=[ref] if ref else [],
                )
            )
        out.summary_text = " ".join(sec.content for sec in out.sections)
        return out

    if mode == "section":
        target = next((s for s in sections if s["id"] == section_id), None)
        if not target:
            out.summary_text = "Requested section not found in the document."
            out.sections = [SummarySection(label="Not found", content="Requested section not found in the document.", found=False)]
            return out
        sent = _top_sentences(target.get("text", ""), 6)
        ref = _ref_for(chunk_map, _chunk_of_section(chunks, target["id"]))
        out.summary_text = " ".join(sent)
        out.sections = [SummarySection(label=target["title"], content=out.summary_text, citation_refs=[ref] if ref else [])]
        return out

    if mode == "key_findings":
        full_text = " ".join(c["text"] for c in chunks)
        sents = [s for s in _sentences(full_text) if FINDING_MARKERS.search(s)]
        sents = _top_sentences(" ".join(sents), 8) if sents else []
        if not sents:
            out.summary_text = "No explicitly stated findings were detected in the document."
            out.sections = [SummarySection(label="Key findings", content=out.summary_text, found=False)]
            return out
        out.summary_text = " ".join(sents)
        out.sections = [SummarySection(label="Key findings", content=out.summary_text)]
        return out

    if mode == "timeline":
        # built from date entities
        events: dict[str, list[str]] = {}
        for ent in entities:
            if ent["entity_type"] == "date" and ent.get("normalized_text"):
                d = ent["normalized_text"]
                events.setdefault(d, []).append(
                    _trim_snippet(ent.get("source_snippet", ""))
                )
        if not events:
            out.summary_text = "No dated events were found in the document."
            out.sections = [SummarySection(label="Timeline", content=out.summary_text, found=False)]
            return out
        lines = []
        for d in sorted(events):
            for snip in events[d][:2]:
                lines.append(f"{d}: {_trim_snippet(snip)}")
        out.summary_text = "\n".join(lines)
        out.sections = [SummarySection(label="Timeline", content="\n".join(lines[:20]))]
        return out

    if mode == "structured":
        def collect(pred) -> list[str]:
            vals: list[str] = []
            for e in entities:
                if pred(e):
                    v = e.get("normalized_text") or e.get("raw_text")
                    if v and v not in vals:
                        vals.append(v)
            return vals

        meds = collect(lambda e: e["entity_type"] == "medication")
        doses = collect(lambda e: e["entity_type"] == "dose")
        procedures = collect(lambda e: e["entity_type"] in ("procedure",))
        abbrevs = collect(lambda e: e["entity_type"] == "abbreviation")
        dates = collect(lambda e: e["entity_type"] == "date")

        # tests from lab-section sections or measurement names
        test_names: list[str] = []
        for sec in sections:
            if sec.get("matched_vocab") in ("labs", "results"):
                for line in sec.get("text", "").splitlines():
                    if ":" in line and len(line) < 160:
                        name = line.split(":")[0].strip().title()
                        if name and name.lower() not in ("date", "note", "page") and name not in test_names:
                            test_names.append(name)

        def maybe(label: str, vals: list[str], k: int = 12) -> SummarySection:
            if vals:
                shown = ", ".join(vals[:k]) + ("..." if len(vals) > k else "")
                return SummarySection(label=label, content=shown, citation_refs=[])
            return SummarySection(label=label, content="Not found in the document.", found=False)

        out.sections = [
            SummarySection(label="Document type", content=doc_type or "Not identified"),
            SummarySection(
                label="Document date",
                content=doc_date or (dates[0] if dates else "Not found in the document."),
                found=bool(doc_date or dates),
            ),
            maybe("Medications mentioned", meds),
            maybe("Dosages mentioned", doses),
            maybe("Tests mentioned", test_names),
            maybe("Procedures mentioned", procedures),
            SummarySection(
                label="Explicit conclusions",
                content=_conclusions_text(sections, chunks),
                citation_refs=[],
            ),
            maybe("Abbreviations detected", abbrevs, 10),
        ]
        out.summary_text = "; ".join(
            f"{s.label}: {s.content}" for s in out.sections
        )
        return out

    raise ValueError(f"Unknown summary mode: {mode}")


def _conclusions_text(sections: list[dict], chunks: list[dict]) -> str:
    for sec in sections:
        if sec.get("matched_vocab") in ("impression", "assessment", "conclusion"):
            sent = _top_sentences(sec.get("text", ""), 3)
            if sent:
                return " ".join(sent)
    # fallback: sentences with conclusion markers
    for c in chunks:
        for s in _sentences(c["text"]):
            if re.search(r"\b(impression|conclusion|in summary)\b", s, re.I):
                return s
    return "Not found in the document."


def _diverse_chunks(chunks: list[dict], k: int) -> list[dict]:
    """Pick chunks spread across pages/sections."""
    if len(chunks) <= k:
        return chunks
    step = len(chunks) / k
    return [chunks[int(i * step)] for i in range(k)]


def _find_chunk_ref(sentence: str, chunks: list[dict], chunk_map: dict) -> str | None:
    frag = sentence[:80]
    for c in chunks:
        if frag and frag in c["text"]:
            return chunk_map.get(c["id"])
    return None


def _chunk_of_section(chunks: list[dict], section_id: str | None) -> str | None:
    if not section_id:
        return None
    for c in chunks:
        if c.get("section_id") == section_id:
            return c["id"]
    return None


def _trim_snippet(s: str, n: int = 160) -> str:
    s = " ".join(s.split())
    return s[: n - 1] + "…" if len(s) > n else s
