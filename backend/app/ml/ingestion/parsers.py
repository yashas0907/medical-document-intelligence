"""Text extraction with page-level provenance.

Every extracted page keeps: page_number, text, extraction_method ('text' | 'ocr'
| 'ocr-failed' | 'empty'), char_count, ocr_confidence. This metadata flows into
chunks and citations â€” the foundation of the provenance chain.
"""
import io
from collections.abc import Callable
from dataclasses import dataclass, field

from app.core.errors import IngestionError
from app.core.logging import get_logger

log = get_logger(__name__)

MAX_PDF_OBJECTS = 500  # pymupdf safety cap for malformed files


@dataclass
class ExtractedTable:
    page_number: int
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    caption: str | None = None


@dataclass
class ExtractedPage:
    page_number: int  # 1-based
    text: str
    extraction_method: str  # text | ocr | ocr-failed | empty
    ocr_confidence: float | None = None
    tables: list[ExtractedTable] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ExtractedDocument:
    pages: list[ExtractedPage]
    doc_type: str = "unknown"
    language: str | None = None

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def word_count(self) -> int:
        return sum(len(p.text.split()) for p in self.pages)


class PDFParser:
    name = "pdf"

    def extract(
        self, data: bytes, ocr_provider, max_pages: int, ocr_pages_cap: int
    ) -> ExtractedDocument:
        import fitz  # pymupdf

        try:
            pdf = fitz.open(stream=data, filetype="pdf")
        except Exception as e:
            raise IngestionError(f"Invalid or corrupted PDF: {type(e).__name__}") from e

        pages: list[ExtractedPage] = []
        ocr_used = 0
        try:
            count = min(len(pdf), max_pages)
            for i in range(count):
                page = pdf[i]
                text = page.get_text("text") or ""
                tables = self._extract_tables_fitz(page, i)
                if len(text.strip()) >= 20:
                    pages.append(
                        ExtractedPage(
                            page_number=i + 1, text=text.strip(), extraction_method="text",
                            tables=tables,
                        )
                    )
                    continue

                # Scanned page -> OCR if possible
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                if ocr_provider.available() and ocr_used < ocr_pages_cap:
                    try:
                        res = ocr_provider.image_to_text(img_bytes, "image/png")
                        if res.confidence >= 40 and len(res.text) >= 10:
                            pages.append(
                                ExtractedPage(
                                    page_number=i + 1,
                                    text=res.text,
                                    extraction_method="ocr",
                                    ocr_confidence=res.confidence,
                                    tables=tables,
                                )
                            )
                            ocr_used += 1
                            continue
                    except Exception as e:  # OCR engine failure on one page
                        log.warning(
                            "OCR page failure doc_page=%s err=%s", i + 1, type(e).__name__
                        )
                pages.append(
                    ExtractedPage(
                        page_number=i + 1,
                        text="",
                        extraction_method="ocr-failed" if text.strip() == "" else "empty",
                        tables=tables,
                    )
                )
            return ExtractedDocument(pages=pages, doc_type="pdf")
        finally:
            pdf.close()

    def _extract_tables_fitz(self, page, page_index: int) -> list[ExtractedTable]:
        """Extract tables via page.find_tables() (pymupdf's built-in detector)."""
        out: list[ExtractedTable] = []
        try:
            tabs = page.find_tables()
            for t in tabs.tables:
                raw = t.extract()
                if not raw or not raw[0]:
                    continue
                cleaned = [[(c or "").strip() for c in row] for row in raw if row]
                if len(cleaned) < 2:
                    continue
                out.append(
                    ExtractedTable(
                        page_number=page_index + 1,
                        header=cleaned[0],
                        rows=cleaned[1:],
                    )
                )
        except Exception as e:
            log.warning("table extraction failed page=%s err=%s", page_index + 1, type(e).__name__)
        return out


class DOCXParser:
    name = "docx"

    def extract(
        self, data: bytes, ocr_provider=None, max_pages: int = 0, ocr_pages_cap: int = 0
    ) -> ExtractedDocument:
        from docx import Document as DocxDocument

        try:
            doc = DocxDocument(io.BytesIO(data))
        except Exception as e:
            raise IngestionError(f"Invalid DOCX: {type(e).__name__}") from e

        lines: list[str] = []
        # Iterate body elements in order to preserve structure (paragraphs + tables)
        from docx.document import Document as _Doc
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        def iter_block_items(parent: _Doc):
            from docx.oxml.ns import qn

            body = parent.element.body
            for child in body.iterchildren():
                if child.tag == qn("w:p"):
                    yield Paragraph(child, parent)
                elif child.tag == qn("w:tbl"):
                    yield Table(child, parent)

        tables: list[ExtractedTable] = []
        table_idx = 0
        approx_page = 1
        char_budget = 0
        for block in iter_block_items(doc):
            if isinstance(block, Paragraph):
                t = block.text.strip()
                if t:
                    lines.append(t)
                    char_budget += len(t)
                    if char_budget > 3000:  # ~page boundary heuristic
                        approx_page += 1
                        char_budget = 0
            elif isinstance(block, Table):
                table_idx += 1
                rows = []
                for row in block.rows:
                    cells = [c.text.strip() for c in row.cells]
                    rows.append(cells)
                if rows:
                    tables.append(
                        ExtractedTable(
                            page_number=approx_page,
                            header=rows[0],
                            rows=rows[1:],
                        )
                    )
                    lines.append(f"[Table {table_idx}]")
        text = "\n".join(lines)
        pages = [ExtractedPage(page_number=1, text=text, extraction_method="text", tables=tables)]
        if len(text) > 6000:  # split long DOCX into virtual pages of ~6000 chars
            pages = []
            chunk_start = 0
            pn = 1
            while chunk_start < len(text):
                part = text[chunk_start : chunk_start + 6000]
                pages.append(
                    ExtractedPage(page_number=pn, text=part, extraction_method="text")
                )
                chunk_start += 6000
                pn += 1
            pages[0].tables = tables
        return ExtractedDocument(pages=pages, doc_type="docx")


class TXTParser:
    name = "txt"

    def extract(
        self, data: bytes, ocr_provider=None, max_pages: int = 0, ocr_pages_cap: int = 0
    ) -> ExtractedDocument:
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            try:
                text = data.decode("latin-1")
            except Exception as e:
                raise IngestionError("Unreadable text file encoding") from e
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            raise IngestionError("Text file is empty")
        # Virtual pages of ~3000 chars at paragraph boundaries
        pages: list[ExtractedPage] = []
        paras = text.split("\n\n")
        buf: list[str] = []
        size = 0
        pn = 1
        for para in paras:
            if size + len(para) > 3000 and buf:
                pages.append(
                    ExtractedPage(page_number=pn, text="\n\n".join(buf), extraction_method="text")
                )
                pn += 1
                buf, size = [], 0
            buf.append(para)
            size += len(para)
        if buf:
            pages.append(
                ExtractedPage(page_number=pn, text="\n\n".join(buf), extraction_method="text")
            )
        return ExtractedDocument(pages=pages, doc_type="txt")


PARSERS: dict[str, Callable] = {
    "pdf": PDFParser,
    "docx": DOCXParser,
    "txt": TXTParser,
}


def get_parser_for_extension(ext: str):
    ext = ext.lower().lstrip(".")
    parser_cls = PARSERS.get(ext)
    if parser_cls is None:
        raise IngestionError(
            f"Unsupported file extension '{ext}'", details={"supported": list(PARSERS)}
        )
    return parser_cls()

