"""SQLAlchemy ORM models. Full relational provenance chain:
User -> Document -> Page -> Section -> Chunk -> (Embedding, Citation)
                                   -> Entity, Measurement, TableExtraction
Answers/conversations/comparisons reference chunks via citations.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    role: Mapped[str] = mapped_column(String(20), default="user")  # user | admin

    documents: Mapped[list["Document"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), default="")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    doc_type: Mapped[str] = mapped_column(String(50), default="unknown")
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    # uploaded | processing | completed | failed
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    doc_date: Mapped[str | None] = mapped_column(String(30), nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pipeline_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    owner: Mapped[User] = relationship(back_populates="documents")
    pages: Mapped[list["Page"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    sections: Mapped[list["Section"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    entities: Mapped[list["ExtractedEntity"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    measurements: Mapped[list["Measurement"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    tables: Mapped[list["TableExtraction"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_owner_status", "owner_id", "status"),
        Index("ix_documents_owner_created", "owner_id", "created_at"),
    )


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(20), default="text")  # text|ocr|none
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text, default="")

    document: Mapped[Document] = relationship(back_populates="pages")

    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_doc_page"),)


class Section(Base):
    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    section_type: Mapped[str] = mapped_column(String(30), default="section")
    # section | header | title
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship(back_populates="sections")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="section")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), index=True, nullable=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    is_table_chunk: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # local index cache
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    document: Mapped[Document] = relationship(back_populates="chunks")
    section: Mapped[Section | None] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_doc_chunk"),
        Index("ix_chunks_doc_page", "document_id", "page_number"),
    )


class ExtractedEntity(Base):
    __tablename__ = "extracted_entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # date|person|organization|medication|dose|lab_test|procedure|symptom|finding|abbrev
    raw_text: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    normalized_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 1.0 = deterministic normalization; <1.0 = uncertain, original preserved
    source_snippet: Mapped[str] = mapped_column(Text, default="")
    extraction_method: Mapped[str] = mapped_column(String(20), default="rule")
    # rule | llm

    document: Mapped[Document] = relationship(back_populates="entities")

    __table_args__ = (Index("ix_ent_doc_type", "document_id", "entity_type"),)


class Measurement(Base):
    """Quantitative value with unit + reference range, extracted from text or tables."""

    __tablename__ = "measurements"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)  # e.g. "Hemoglobin"
    value_raw: Mapped[str] = mapped_column(String(100), nullable=False)  # "13.5"
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reference_range: Mapped[str | None] = mapped_column(String(100), nullable=True)
    flag: Mapped[str | None] = mapped_column(String(20), nullable=True)  # H|L|normal|unknown
    source_snippet: Mapped[str] = mapped_column(Text, default="")
    table_row: Mapped[int | None] = mapped_column(JSON, nullable=True)

    document: Mapped[Document] = relationship(back_populates="measurements")

    __table_args__ = (Index("ix_meas_doc_name", "document_id", "name"),)


class TableExtraction(Base):
    """Preserved table semantics with row/column/page provenance."""

    __tablename__ = "table_extractions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    table_index: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str | None] = mapped_column(String(300), nullable=True)
    header: Mapped[list] = mapped_column(JSON, default=list)
    rows: Mapped[list] = mapped_column(JSON, default=list)
    row_count: Mapped[int] = mapped_column(Integer, default=0)

    document: Mapped[Document] = relationship(back_populates="tables")


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), default="Conversation")

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Assistant payloads carry structured data: citations, evidence, metadata
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Citation(Base):
    """Every generated claim's link to real stored evidence. No fake citations."""

    __tablename__ = "citations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    message_id: Mapped[str | None] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True, nullable=True
    )
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    ref_label: Mapped[str] = mapped_column(String(10), default="")  # [1], [2], ...

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComparisonJob(Base, TimestampMixin):
    __tablename__ = "comparison_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    doc_a_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    doc_b_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|completed|failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class ModelRun(Base):
    """AI provenance: which model/prompt/pipeline produced a result."""

    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # ask | summarize | compare | embed | ocr
    provider: Mapped[str] = mapped_column(String(60), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(30), default="")
    pipeline_version: Mapped[str] = mapped_column(String(20), default="")
    document_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Security-relevant events. Stores IDs/metadata only — never document content."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    # login, login_failed, upload, delete, ask, summarize, compare, security_block
    resource_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
