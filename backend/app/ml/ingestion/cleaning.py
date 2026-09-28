"""Document cleaning: repeated header/footer removal, control chars, spacing.

Deterministic — no LLM. operates on page text preserving offsets as much as
possible (citation quotes come from chunk text directly).
"""
import re
from collections import Counter
from dataclasses import dataclass


@dataclass
class CleaningReport:
    removed_header_footer_lines: int = 0
    normalized_whitespace_chars: int = 0
    pages_cleaned: int = 0


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_PAGE_NO_RE = re.compile(r"^\s*(?:page\s*)?[\divxlcm]+\s*(?:of|/)\s*[\d]+\s*$", re.IGNORECASE)
_BARE_PAGE_RE = re.compile(r"^\s*-?\s*\d{1,4}\s*-?\s*$")


def _line_fingerprint(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def find_repeated_lines(pages: list[str], min_docs: int = 3, max_len: int = 90) -> Counter:
    """Lines that appear (nearly) identically on most pages → headers/footers."""
    if len(pages) < 3:
        return Counter()
    counts: Counter[str] = Counter()
    for page in pages:
        seen_on_page: set[str] = set()
        for line in page.splitlines():
            s = line.strip()
            if not s or len(s) > max_len:
                continue
            if _PAGE_NO_RE.match(s) or _BARE_PAGE_RE.match(s):
                continue
            fp = _line_fingerprint(s)
            if fp not in seen_on_page:
                seen_on_page.add(fp)
                counts[fp] += 1
    threshold = max(min_docs, int(len(pages) * 0.7))
    return Counter({k: v for k, v in counts.items() if v >= threshold})


def clean_text(text: str) -> str:
    text = _CTRL_RE.sub(" ", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def clean_pages(pages: list[str]) -> tuple[list[str], CleaningReport]:
    """Remove repeated header/footer lines from multi-page docs; clean whitespace."""
    report = CleaningReport()
    if not pages:
        return pages, report

    hot = find_repeated_lines(pages)
    if hot:
        report.pages_cleaned = len(pages)

    cleaned: list[str] = []
    for page in pages:
        kept_lines = []
        for line in page.splitlines():
            s = line.strip()
            if not s:
                kept_lines.append("")
                continue
            if _PAGE_NO_RE.match(s) or _BARE_PAGE_RE.match(s):
                report.removed_header_footer_lines += 1
                continue
            if _line_fingerprint(s) in hot:
                report.removed_header_footer_lines += 1
                continue
            before = len(line)
            kept_lines.append(_MULTI_SPACE_RE.sub(" ", s))
            report.normalized_whitespace_chars += before - len(kept_lines[-1])
        cleaned.append(clean_text("\n".join(kept_lines)))
    return cleaned, report
