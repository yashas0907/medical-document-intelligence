"""Structure-aware chunking.

Rules:
- Chunks never cross section boundaries (keeps section_title provenance exact).
- Never cross page boundaries (keeps page_number provenance exact).
- Target 900 chars, max 1400, min 80 (smaller merged forward when possible).
- Sentences kept intact via boundary snapping (period/space) where feasible.
- Tables serialized as pipe-delimited rows with a header line, marked
  is_table_chunk=True; table rows never split across chunks.
"""
import re
from dataclasses import dataclass, field

from app.ml.versions import CHUNKER_VERSION

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
TARGET = 900
HARD_MAX = 1400
MIN_CHUNK = 80


@dataclass
class TextChunk:
    document_id: str
    chunk_index: int
    page_number: int
    section_id: str | None
    section_title: str | None
    text: str
    is_table_chunk: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def token_estimate(self) -> int:
        return max(1, len(self.text) // 4)


@dataclass
class ChunkingResult:
    chunks: list[TextChunk] = field(default_factory=list)
    version: str = CHUNKER_VERSION


def _split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_END.split(text)
    return [p.strip() for p in parts if p.strip()]


def _pack_sentences(sentences: list[str], page: int, section_id, section_title, start_idx: int) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    buf: list[str] = []
    size = 0
    idx = start_idx

    def flush():
        nonlocal buf, size, idx
        if not buf:
            return
        text = " ".join(buf).strip()
        if text:
            chunks.append(
                TextChunk(
                    document_id="",
                    chunk_index=idx,
                    page_number=page,
                    section_id=section_id,
                    section_title=section_title,
                    text=text,
                )
            )
            idx += 1
        buf, size = [], 0

    for s in sentences:
        if size + len(s) > HARD_MAX and buf:
            flush()
        buf.append(s)
        size += len(s) + 1
        if size >= TARGET:
            flush()
    flush()
    return chunks


def _merge_small(all_chunks: list[TextChunk]) -> list[TextChunk]:
    """Merge a too-small chunk into the previous one IF same page & section."""
    out: list[TextChunk] = []
    for c in all_chunks:
        if (
            out
            and c.char_count < MIN_CHUNK
            and not c.is_table_chunk
            and out[-1].page_number == c.page_number
            and out[-1].section_id == c.section_id
            and out[-1].char_count + c.char_count <= HARD_MAX
        ):
            out[-1] = TextChunk(
                document_id="",
                chunk_index=out[-1].chunk_index,
                page_number=out[-1].page_number,
                section_id=out[-1].section_id,
                section_title=out[-1].section_title,
                text=out[-1].text + " " + c.text,
                is_table_chunk=out[-1].is_table_chunk,
            )
        else:
            out.append(c)
    for i, c in enumerate(out):
        out[i] = TextChunk(
            document_id=c.document_id,
            chunk_index=i,
            page_number=c.page_number,
            section_id=c.section_id,
            section_title=c.section_title,
            text=c.text,
            is_table_chunk=c.is_table_chunk,
        )
    return out


def serialize_table(header: list[str], rows: list[list[str]], caption: str | None = None) -> str:
    lines = []
    if caption:
        lines.append(f"Table: {caption}")
    lines.append(" | ".join(header))
    for r in rows:
        lines.append(" | ".join(str(c or "") for c in r))
    return "\n".join(lines)


def chunk_document(
    sections: list[tuple[str | None, str | None, int, str, bool]]
) -> ChunkingResult:
    """sections: iterable of (section_id, section_title, page_number, text, is_table)."""
    all_chunks: list[TextChunk] = []
    idx = 0
    for section_id, section_title, page, text, is_table in sections:
        if not text or not text.strip():
            continue
        if is_table:
            all_chunks.append(
                TextChunk(
                    document_id="",
                    chunk_index=idx,
                    page_number=page,
                    section_id=section_id,
                    section_title=section_title,
                    text=text.strip(),
                    is_table_chunk=True,
                )
            )
            idx += 1
            continue
        for line_block in text.split("\n\n"):
            if not line_block.strip():
                continue
            sentences = _split_sentences(line_block)
            pieces = _pack_sentences(sentences, page, section_id, section_title, idx)
            all_chunks.extend(pieces)
            idx = len(all_chunks)
    return ChunkingResult(chunks=_merge_small(all_chunks))
