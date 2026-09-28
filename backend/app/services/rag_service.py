"""RAG service: retrieval → evidence → grounded answer → persistence → citations."""
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db import models
from app.ml.rag.grounded import (
    EvidencePiece,
    ExtractiveGroundedEngine,
    LLMGroundedRewriter,
)
from app.ml.retrieval.store import get_document_retriever
from app.ml.security.sanitization import scan_for_injection
from app.ml.versions import PIPELINE_VERSION, PROMPT_VERSION

log = get_logger(__name__)


def _load_chunks(db: Session, doc_ids: list[str]) -> list[dict]:
    rows = db.scalars(
        select(models.Chunk)
        .where(models.Chunk.document_id.in_(doc_ids))
        .order_by(models.Chunk.document_id, models.Chunk.chunk_index)
    ).all()
    out = []
    for r in rows:
        out.append({
            "chunk_id": r.id,
            "document_id": r.document_id,
            "page_number": r.page_number,
            "section_id": r.section_id,
            "section_title": None,
            "text": r.text,
            "is_table_chunk": r.is_table_chunk,
        })
    # enrich section titles
    section_ids = {c["section_id"] for c in out if c["section_id"]}
    if section_ids:
        secs = db.scalars(select(models.Section).where(models.Section.id.in_(section_ids))).all()
        title_map = {s.id: s.title for s in secs}
        for c in out:
            if c["section_id"]:
                c["section_title"] = title_map.get(c["section_id"])
    return out


def _doc_titles(db: Session, doc_ids: list[str]) -> dict[str, str]:
    docs = db.scalars(select(models.Document).where(models.Document.id.in_(doc_ids))).all()
    return {d.id: d.title for d in docs}


def ask_documents(
    db: Session,
    user,
    question: str,
    doc_ids: list[str],
    conversation_id: str | None = None,
    top_k: int = 6,
    use_llm: bool | None = None,
) -> dict:
    settings = get_settings()
    t0 = time.perf_counter()

    # conversation bootstrap
    conv = None
    if conversation_id:
        conv = db.get(models.Conversation, conversation_id)
        if conv and conv.user_id != user.id:
            conv = None

    chunks = _load_chunks(db, doc_ids)
    if not chunks:
        return {
            "question": question,
            "answer": "The selected documents have no processed text to search yet.",
            "answer_sentences": [],
            "citations": [],
            "evidence": [],
            "groundedness": 0.0,
            "evidence_coverage": 0.0,
            "method": "none",
            "insufficient_evidence": True,
            "model_meta": None,
        }

    # one retriever per document set (fingerprinted cache keeps identity)
    cache_key = "multi:" + "|".join(sorted(doc_ids))
    retriever = get_document_retriever(cache_key, chunks, settings.embedding_model)
    t_r = time.perf_counter()
    scored = retriever.search(question, top_k=top_k)
    retrieval_ms = (time.perf_counter() - t_r) * 1000

    titles = _doc_titles(db, doc_ids)
    evidence = [
        EvidencePiece(
            chunk_id=s.chunk_id,
            document_id=s.document_id,
            page_number=s.page_number,
            section_title=s.section_title,
            text=s.text,
            score=s.fused_score,
            is_table_chunk=s.is_table_chunk,
        )
        for s in scored
    ]

    # injection scan on evidence content (security telemetry, answer unaffected:
    # extraction never executes document text)
    inj_hits = sum(1 for e in evidence if scan_for_injection(e.text).is_suspicious)
    if inj_hits:
        log.warning("injection-like content in evidence hits=%s", inj_hits)

    engine = ExtractiveGroundedEngine()
    ga = engine.answer(question, evidence)

    method = "extractive"
    model_meta = ga.model_meta
    if (use_llm if use_llm is not None else settings.llm_enabled) and ga.sentences:
        try:
            rewriter = LLMGroundedRewriter(settings)
            t_llm = time.perf_counter()
            sentences, meta = rewriter.rewrite(question, ga.sentences, evidence)
            llm_ms = (time.perf_counter() - t_llm) * 1000
            db.add(models.ModelRun(
                kind="ask", provider="openai-compatible", model=settings.llm_model or "",
                prompt_version=PROMPT_VERSION, pipeline_version=PIPELINE_VERSION,
                duration_ms=int(llm_ms), success=True,
                meta={"question_chars": len(question), "evidence": len(evidence)},
            ))
            if sentences:
                ga.sentences = sentences
                ga.citations = [
                    {
                        "ref": f"[{i+1}]", "document_id": e.document_id,
                        "page_number": e.page_number, "section_title": e.section_title,
                        "chunk_id": e.chunk_id, "quote": e.text[:280],
                    }
                    for i, e in enumerate(evidence)
                ]
                method = "llm-grounded"
                model_meta = meta
        except Exception as e:
            log.warning("LLM rewrite failed, falling back to extractive err=%s", type(e).__name__)
            db.add(models.ModelRun(
                kind="ask", provider="openai-compatible", model=settings.llm_model or "",
                prompt_version=PROMPT_VERSION, pipeline_version=PIPELINE_VERSION,
                success=False, error_code=type(e).__name__,
            ))

    # metrics
    used_refs = {r for s in ga.sentences for r in s.citation_refs}
    groundedness = (
        len([s for s in ga.sentences if s.citation_refs]) / len(ga.sentences)
        if ga.sentences else 0.0
    )
    coverage = len(used_refs) / len(ga.citations) if ga.citations else 0.0

    # persist conversation
    if conv is None:
        conv = models.Conversation(
            user_id=user.id,
            document_id=doc_ids[0] if len(doc_ids) == 1 else None,
            title=question[:120],
        )
        db.add(conv)
        db.flush()
    db.add(models.ChatMessage(conversation_id=conv.id, role="user", content=question))
    db.flush()
    assistant = models.ChatMessage(
        conversation_id=conv.id,
        role="assistant",
        content=ga.answer_text,
        payload={
            "citations": ga.citations,
            "evidence": [
                {
                    "chunk_id": e.chunk_id, "document_id": e.document_id,
                    "page_number": e.page_number, "section_title": e.section_title,
                    "text": e.text, "score": e.score,
                } for e in evidence
            ],
            "groundedness": round(groundedness, 3),
            "insufficient_evidence": ga.insufficient_evidence,
            "method": method,
            "model_meta": model_meta,
            "retrieval_ms": int(retrieval_ms),
        },
    )
    db.add(assistant)
    db.flush()
    for cit in ga.citations:
        db.add(models.Citation(
            message_id=assistant.id,
            document_id=cit["document_id"],
            chunk_id=cit.get("chunk_id"),
            page_number=cit.get("page_number"),
            section_title=cit.get("section_title"),
            quote=cit.get("quote", ""),
            ref_label=cit["ref"],
        ))
    db.add(models.ModelRun(
        kind="ask", provider="extractive", model="extractive-v1",
        prompt_version=PROMPT_VERSION, pipeline_version=PIPELINE_VERSION,
        duration_ms=int((time.perf_counter() - t0) * 1000), success=True,
        meta={"groundedness": round(groundedness, 3), "coverage": round(coverage, 3)},
    ))
    db.commit()

    log.info(
        "ask answered user=%s docs=%s evidence=%s sentences=%s groundedness=%.2f ms=%d",
        user.id, len(doc_ids), len(evidence), len(ga.sentences), groundedness,
        int((time.perf_counter() - t0) * 1000),
    )

    return {
        "question": question,
        "answer": ga.answer_text,
        "answer_sentences": [
            {"text": s.text, "citation_refs": s.citation_refs} for s in ga.sentences
        ],
        "citations": [
            {
                **c,
                "document_title": titles.get(c["document_id"]),
            }
            for c in ga.citations
        ],
        "evidence": [
            {
                "chunk_id": e.chunk_id, "document_id": e.document_id,
                "page_number": e.page_number, "section_title": e.section_title,
                "text": e.text, "score": e.score, "is_table_chunk": e.is_table_chunk,
            }
            for e in evidence
        ],
        "groundedness": round(groundedness, 3),
        "evidence_coverage": round(coverage, 3),
        "method": method,
        "insufficient_evidence": ga.insufficient_evidence,
        "model_meta": model_meta,
        "conversation_id": conv.id,
    }
