"""Pydantic schemas — API request/response contracts and structured AI outputs."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def email_shape(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@") or "." not in v.split("@")[-1]:
            raise ValueError("must be a valid email address")
        return v


class UserOut(BaseModel):
    id: str
    email: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class DocumentOut(BaseModel):
    id: str
    title: str
    original_filename: str
    doc_type: str
    status: Literal["uploaded", "processing", "completed", "failed"]
    status_message: str | None = None
    page_count: int
    word_count: int
    doc_date: str | None = None
    file_size: int
    created_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DocumentDetail(DocumentOut):
    sections: list["SectionOut"] = []
    entities_summary: "EntitySummary | None" = None
    storage: "StorageInfo | None" = None


class SectionOut(BaseModel):
    id: str
    title: str
    section_type: str
    page_number: int | None
    order_index: int
    char_count: int

    model_config = ConfigDict(from_attributes=True)


class PageOut(BaseModel):
    page_number: int
    extraction_method: str
    ocr_confidence: float | None = None
    text: str


class EntitySummary(BaseModel):
    total: int
    by_type: dict[str, int]


class StorageInfo(BaseModel):
    has_original: bool
    extracted_text_saved: bool


class ProcessingStatusOut(BaseModel):
    document_id: str
    status: str
    status_message: str | None = None
    page_count: int
    sections: int = 0
    chunks: int = 0
    entities: int = 0
    measurements: int = 0
    tables: int = 0
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Entities / measurements / tables
# ---------------------------------------------------------------------------


class EntityOut(BaseModel):
    id: str
    entity_type: str
    raw_text: str
    normalized_text: str | None = None
    normalized_confidence: float | None = None
    page_number: int | None = None
    section_id: str | None = None
    source_snippet: str
    extraction_method: str

    model_config = ConfigDict(from_attributes=True)


class MeasurementOut(BaseModel):
    id: str
    name: str
    value_raw: str
    value_num: float | None = None
    unit: str | None = None
    reference_range: str | None = None
    flag: str | None = None
    page_number: int | None = None
    source_snippet: str
    table_row: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class TableOut(BaseModel):
    id: str
    page_number: int
    table_index: int
    caption: str | None = None
    header: list[str]
    rows: list[list[str]]
    row_count: int

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Evidence / citations / Q&A
# ---------------------------------------------------------------------------


class EvidenceOut(BaseModel):
    chunk_id: str
    document_id: str
    page_number: int
    section_title: str | None = None
    text: str
    score: float
    is_table_chunk: bool = False


class CitationOut(BaseModel):
    ref: str  # [1]
    document_id: str
    document_title: str | None = None
    chunk_id: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    quote: str


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    conversation_id: str | None = None
    document_ids: list[str] | None = Field(
        None, max_length=10, description="Restrict to these docs; default = single doc context"
    )
    mode: Literal["grounded", "hybrid_search"] = "grounded"


class AnswerSentences(BaseModel):
    text: str
    citation_refs: list[str] = Field(default_factory=list)


class AskResult(BaseModel):
    question: str
    answer: str
    answer_sentences: list[AnswerSentences] = []
    citations: list[CitationOut] = []
    evidence: list[EvidenceOut] = []
    groundedness: float = Field(
        ..., description="share of answer sentences carrying at least one citation"
    )
    evidence_coverage: float = Field(..., description="share of used citations among retrieved")
    method: str = "extractive"
    insufficient_evidence: bool = False
    model_meta: "ModelMeta | None" = None


class ModelMeta(BaseModel):
    provider: str
    model: str
    prompt_version: str
    pipeline_version: str


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------

SummaryMode = Literal["quick", "detailed", "section", "key_findings", "timeline", "structured"]


class SummaryRequest(BaseModel):
    mode: SummaryMode = "quick"
    section_id: str | None = None
    max_words: int = Field(default=250, ge=50, le=1200)


class SummarySectionItem(BaseModel):
    label: str
    content: str
    citation_refs: list[str] = Field(default_factory=list)
    found: bool = True


class SummaryResult(BaseModel):
    document_id: str
    mode: str
    title: str
    summary_text: str
    sections: list[SummarySectionItem] = []
    citations: list[CitationOut] = []
    model_meta: ModelMeta | None = None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    document_a_id: str
    document_b_id: str


class ComparisonCell(BaseModel):
    doc_id: str
    doc_title: str
    value: str
    citation_ref: str | None = None


class ComparisonRow(BaseModel):
    category: str
    item: str | None = None
    a: ComparisonCell | None = None
    b: ComparisonCell | None = None
    change_type: Literal["added", "removed", "changed", "unchanged"]
    change_note: str | None = None


class ComparisonResultOut(BaseModel):
    doc_a_id: str
    doc_b_id: str
    doc_a_title: str
    doc_b_title: str
    doc_a_date: str | None = None
    doc_b_date: str | None = None
    rows: list[ComparisonRow]
    citations: list[CitationOut] = []
    summary: str


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class TimelineEventItem(BaseModel):
    date: str | None = None
    date_confidence: str = "high"  # high = explicit; low = inferred from section text
    source: str  # doc title / section
    document_id: str
    page_number: int | None = None
    items: list[str] = Field(default_factory=list)
    citation_refs: list[str] = Field(default_factory=list)


class TimelineOut(BaseModel):
    document_id: str
    events: list[TimelineEventItem]
    unpositioned: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Contradictions
# ---------------------------------------------------------------------------


class ContradictionSide(BaseModel):
    claim: str
    document_id: str
    document_title: str
    page_number: int | None = None
    section_title: str | None = None
    quote: str


class ContradictionOut(BaseModel):
    type: Literal["value_conflict", "date_conflict", "unit_conflict", "statement_conflict"]
    severity: Literal["high", "medium", "low"]
    confidence: float = Field(ge=0.0, le=1.0)
    explanation: str
    a: ContradictionSide
    b: ContradictionSide


class ContradictionsResult(BaseModel):
    document_id: str
    compared_with: str | None = None
    contradictions: list[ContradictionOut]
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------


class ConversationOut(BaseModel):
    id: str
    document_id: str | None
    title: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChatMessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime
    payload: dict | None = None

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    database: bool
    storage: bool
    llm: dict[str, bool | str]
    time: str


class StatsOut(BaseModel):
    documents: int
    completed: int
    processing: int
    failed: int
    pages: int
    chunks: int
    entities: int
    measurements: int
    qa_pairs: int
    comparisons: int
