"""Grounded answer generation â€” extractive engine + optional LLM post-edit.

Extractive engine (default, deterministic):
1. Retrieve evidence via hybrid search.
2. Evidence validator: score sufficiency (relevance threshold + coverage).
3. Rank sentences by query-term + lexical overlap with evidence.
4. Compose answer ONLY from source sentences, each carrying citations.
5. If no sentence clears the support threshold â†’ explicit "not found" â€”
   never a fabricated answer.

LLM layer (optional): when configured, the LLM rewrites the selected evidence
sentences under a strict contract (trusted system prompt + untrusted content
wrapping). Output is re-validated: any claim sentence without a mapped citation
is dropped by the validator.
"""
import re
from dataclasses import dataclass, field

from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger
from app.ml.retrieval.query_expand import expand_query
from app.ml.security.sanitization import neutralize_untrusted
from app.ml.versions import EXTRACTIVE_ENGINE, PIPELINE_VERSION, PROMPT_VERSION

log = get_logger(__name__)

WORD = re.compile(r"[a-z0-9]+")
STOP = {
    "the", "a", "an", "of", "in", "on", "for", "to", "and", "or", "is", "are",
    "was", "were", "be", "been", "what", "which", "who", "whom", "how", "when",
    "where", "why", "does", "do", "did", "with", "by", "at", "as", "that",
    "this", "these", "those", "it", "its", "from", "about", "mention", "mentions",
    "mentioned", "state", "states", "stated", "list", "all", "any", "find",
    "found", "say", "says", "said", "tell", "told", "me", "give", "given",
}


def _content_tokens(text: str) -> set[str]:
    toks = {t for t in WORD.findall(text.lower()) if t not in STOP}
    # expand medical abbreviations so 'bp' matches 'blood pressure' and vice versa
    from app.ml.extraction.entities import ABBREVIATIONS

    out = set(toks)
    for t in toks:
        if t in ABBREVIATIONS:
            expansion = ABBREVIATIONS[t]
            out.add(expansion)
            out.update(WORD.findall(expansion))  # also split: 'blood','pressure'
    return out


@dataclass
class EvidencePiece:
    chunk_id: str
    document_id: str
    page_number: int
    section_title: str | None
    text: str
    score: float
    is_table_chunk: bool = False


@dataclass
class AnswerSentence:
    text: str
    citation_refs: list[str] = field(default_factory=list)
    support_score: float = 0.0
    source_chunk_id: str | None = None


@dataclass
class GroundedAnswer:
    question: str
    sentences: list[AnswerSentence] = field(default_factory=list)
    evidence: list[EvidencePiece] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    insufficient_evidence: bool = False
    method: str = EXTRACTIVE_ENGINE
    refusal_reason: str | None = None
    model_meta: dict = field(default_factory=lambda: {
        "provider": "extractive", "model": EXTRACTIVE_ENGINE,
        "prompt_version": PROMPT_VERSION, "pipeline_version": PIPELINE_VERSION,
    })

    @property
    def answer_text(self) -> str:
        if self.insufficient_evidence:
            return self.refusal_reason or (
                "I could not find relevant information in the uploaded documents "
                "to answer this question."
            )
        return " ".join(s.text for s in self.sentences)


MIN_RELEVANCE = 0.03
MIN_SENTENCE_SUPPORT = 0.28


class EvidenceValidator:
    """Checks whether retrieved context actually supports an answer."""

    @staticmethod
    def sufficiency(evidence: list[EvidencePiece], query: str) -> tuple[bool, str | None]:
        if not evidence:
            return False, "No passages were retrieved for this question."
        qtok = _content_tokens(query)
        if not qtok:
            return True, None
        support = 0.0
        for e in evidence:
            etok = _content_tokens(e.text) | _content_tokens(e.section_title or "")
            if etok:
                support = max(support, len(qtok & etok) / max(1, min(len(qtok), 8)))
        if support < 0.15:
            # Category/list questions ("what medications...") legitimately retrieve
            # passages whose *content* answers the category without repeating the
            # category word. The retriever already discarded zero-relevance chunks,
            # so only refuse when NO retrieved evidence has substance.
            has_substance = any(len(e.text) > 20 for e in evidence)
            if not has_substance:
                return False, (
                    "I could not find passages relevant to this question in the uploaded "
                    "documents."
                )
            # Refusal only when the question is *specific* (2+ content tokens — a
            # named entity, a value question, etc.) and none of its rare-ish tokens
            # appear anywhere in the evidence. Single-token category questions
            # ("what medications...") are answered by the retrieved list itself.
            specific = [t for t in qtok if len(t) > 3]
            if len(specific) >= 2:
                all_ev_tokens: set[str] = set()
                for e in evidence:
                    all_ev_tokens |= _content_tokens(e.text) | _content_tokens(e.section_title or "")
                if not any(t in all_ev_tokens for t in specific):
                    return False, (
                        "I could not find passages relevant to this question in the "
                        "uploaded documents."
                    )
        return True, None

    @staticmethod
    def sentence_support(sentence: str, evidence: list[EvidencePiece]) -> float:
        stok = _content_tokens(sentence)
        if not stok:
            return 0.0
        best = 0.0
        for e in evidence:
            etok = _content_tokens(e.text)
            if not etok:
                continue
            overlap = len(stok & etok) / len(stok)
            query_coverage = len(stok & etok) / max(1, min(len(stok), 10))
            best = max(best, 0.6 * overlap + 0.4 * query_coverage)
        return best


class ExtractiveGroundedEngine:
    """Deterministic: select + order source sentences that answer the query."""

    def __init__(self, max_sentences: int = 6):
        self.max_sentences = max_sentences

    def answer(self, question: str, evidence: list[EvidencePiece]) -> GroundedAnswer:
        ga = GroundedAnswer(question=question, evidence=evidence)
        ok, reason = EvidenceValidator.sufficiency(evidence, question)
        if not ok:
            ga.insufficient_evidence = True
            ga.refusal_reason = reason
            return ga

        qtok = _content_tokens(expand_query(question))

        def query_relevance(sentence: str, section_title: str | None = None) -> float:
            stok = _content_tokens(sentence)
            if section_title:
                stok = stok | _content_tokens(section_title)
            if not stok or not qtok:
                return 0.0
            return len(stok & qtok) / len(qtok)

        # Table chunks are dense evidence â€” consider their lines as sentences
        candidates: list[tuple[float, AnswerSentence, EvidencePiece]] = []
        for rank, e in enumerate(evidence):
            lines = e.text.splitlines() if e.is_table_chunk else re.split(r"(?<=[.!?])\s+", e.text)
            for line in lines:
                line = " ".join(line.split()).strip()
                if len(line) < 8:
                    continue
                support = EvidenceValidator.sentence_support(line, [e])
                if support < MIN_SENTENCE_SUPPORT:
                    continue
                qrel = query_relevance(line, e.section_title)
                # Specific questions: sentence must share query terms. Single-token
                # category questions: retrieval already did the work.
                if qtok and len(qtok) > 1 and qrel <= 0.0:
                    continue
                ref = f"[{rank + 1}]"
                sent = AnswerSentence(
                    text=line if line.endswith((".", "?", "!", ":")) else line + ".",
                    citation_refs=[ref],
                    support_score=round(support, 4),
                    source_chunk_id=e.chunk_id,
                )
                # Rank primarily by question relevance, then evidence support
                candidates.append((qrel + 0.3 * support + 0.02 * (len(evidence) - rank), sent, e))

        # Dedup by near-identical text
        seen: set[str] = set()
        picked: list[tuple[float, AnswerSentence, EvidencePiece]] = []
        for item in sorted(candidates, key=lambda x: -x[0]):
            key = " ".join(item[1].text.lower().split())[:120]
            if key in seen:
                continue
            seen.add(key)
            picked.append(item)

        # Prefer diversity: cap 2 sentences per chunk
        per_chunk: dict[str, int] = {}
        final: list[tuple[float, AnswerSentence, EvidencePiece]] = []
        for item in picked:
            cid = item[2].chunk_id
            if per_chunk.get(cid, 0) >= 2:
                continue
            per_chunk[cid] = per_chunk.get(cid, 0) + 1
            final.append(item)
            if len(final) >= self.max_sentences:
                break

        if not final:
            ga.insufficient_evidence = True
            ga.refusal_reason = (
                "The retrieved passages do not clearly state information that answers "
                "this question."
            )
            return ga

        # order by query relevance desc (top answer first), tie-break by page
        final.sort(key=lambda x: (-x[0], x[2].page_number))
        ga.sentences = [s for _, s, _ in final]
        # Defense-in-depth: redact instruction-like payloads that may appear inside
        # quoted document content (defense for users reading answers verbatim).
        for s in ga.sentences:
            s.text = neutralize_untrusted(s.text)

        for rank, e in enumerate(evidence):
            ref = f"[{rank + 1}]"
            ga.citations.append(
                {
                    "ref": ref,
                    "document_id": e.document_id,
                    "page_number": e.page_number,
                    "section_title": e.section_title,
                    "chunk_id": e.chunk_id,
                    "quote": e.text[:280],
                }
            )
        return ga


class LLMGroundedRewriter:
    """Optional LLM layer: rewrite selected evidence into fluent prose under contract.

    The LLM only ever sees: (a) the trusted system prompt, (b) sanitized evidence
    text. It must preserve the numbered evidence refs. Post-validation drops any
    sentence lacking a citation.
    """

    def __init__(self, settings):
        if not settings.llm_enabled:
            raise ServiceUnavailableError("LLM not enabled")
        self._settings = settings
        self.model = settings.llm_model

    def rewrite(self, question: str, sentences: list[AnswerSentence], evidence: list[EvidencePiece]) -> tuple[list[AnswerSentence], dict]:
        import httpx

        # Build evidence block with refs â€” content clearly wrapped as untrusted data
        ref_map: dict[str, int] = {}
        ev_lines: list[str] = []
        for i, s in enumerate(sentences):
            ref_map[s.citation_refs[0]] = i
            ev_lines.append(f"({i + 1}) {neutralize_untrusted(s.text)}")
        system_prompt = (
            "You are a medical document analyst. You will receive numbered source "
            "sentences extracted from a user's document. Rewrite them into ONE concise "
            "answer paragraph (2-5 sentences) for the question. STRICT RULES: "
            "1) Use ONLY information present in the source sentences. Do not add facts, "
            "numbers, or medical advice. 2) Keep the (n) reference markers inline after "
            "each fact. 3) If the sources do not answer the question, reply exactly: "
            "INSUFFICIENT_EVIDENCE. 4) Do not give medical advice, diagnosis, or "
            "treatment suggestions. Output only the answer paragraph."
        )
        user_prompt = (
            f"Question: {neutralize_untrusted(question)}\n\nSource sentences:\n"
            + "\n".join(ev_lines)
        )
        resp = httpx.post(
            f"{self._settings.llm_api_base.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 400,
            },
            timeout=60,
        )
        meta = {"provider": "openai-compatible", "model": self.model,
                "prompt_version": PROMPT_VERSION, "pipeline_version": PIPELINE_VERSION}
        if resp.status_code != 200:
            raise ServiceUnavailableError(f"LLM API error {resp.status_code}",
                                          details={"body": resp.text[:300]})
        text = resp.json()["choices"][0]["message"]["content"].strip()
        if "INSUFFICIENT_EVIDENCE" in text:
            return [], meta
        # Validate: every output sentence must carry at least one (n) marker
        out: list[AnswerSentence] = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            sent = sent.strip()
            if not sent:
                continue
            refs = re.findall(r"\((\d+)\)", sent)
            if not refs:
                continue  # uncited claim â†’ dropped by validator
            valid_refs = []
            for r in refs:
                idx = int(r) - 1
                if 0 <= idx < len(sentences):
                    valid_refs.append(sentences[idx].citation_refs[0])
            if not valid_refs:
                continue
            # Verify overlap with the cited source sentence (grounding check)
            src = " ".join(
                sentences[int(r) - 1].text for r in refs if 0 <= int(r) - 1 < len(sentences)
            )
            if EvidenceValidator.sentence_support(sent, [EvidencePiece(
                chunk_id="src", document_id="", page_number=0,
                section_title=None, text=src, score=1.0
            )]) < 0.12:
                continue  # likely hallucinated relative to source
            out.append(AnswerSentence(
                text=re.sub(r"\s*\(\d+\)", "", sent).strip(),
                citation_refs=sorted(set(valid_refs)),
                support_score=1.0,
                source_chunk_id=None,
            ))
        return out, meta



