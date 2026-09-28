"""Document structure detection: title, sections, headings, lists.

Heuristic (deterministic):
- Title = first non-empty line if short & followed by content.
- Heading = short line (<= 90 chars), either ALL CAPS, Title Case, numbered
  ("1. History"), or ending with ':' and not a full sentence.
- Matches against known medical section vocabulary boosts confidence.
"""
import re
from dataclasses import dataclass, field

SECTION_VOCAB = {
    "patient information": "patient_info",
    "patient info": "patient_info",
    "history": "history",
    "past medical history": "history",
    "medical history": "history",
    "chief complaint": "history",
    "findings": "findings",
    "imaging": "imaging",
    "imaging findings": "imaging",
    "laboratory results": "labs",
    "lab results": "labs",
    "laboratory": "labs",
    "labs": "labs",
    "medications": "medications",
    "medication": "medications",
    "current medications": "medications",
    "assessment": "assessment",
    "assessment and plan": "assessment",
    "plan": "assessment",
    "notes": "notes",
    "clinical notes": "notes",
    "note": "notes",
    "procedure": "procedure",
    "procedures": "procedure",
    "diagnosis": "diagnosis",
    "diagnoses": "diagnosis",
    "impression": "impression",
    "vitals": "vitals",
    "vital signs": "vitals",
    "symptoms": "symptoms",
    "allergies": "allergies",
    "discharge summary": "notes",
    "follow-up": "followup",
    "follow up": "followup",
    "recommendations": "recommendations",
    "results": "results",
    "test results": "results",
    "specimen": "specimen",
}

_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*)[.)]\s+\S")
_SHORT_LINE = 90
_SENTENCE_ENDINGS = (".", "?", "!", ";", ",")


@dataclass
class DetectedSection:
    title: str
    section_type: str  # title | section
    page_number: int
    order_index: int
    text: str
    matched_vocab: str | None = None
    children: list = field(default_factory=list)


def _is_heading(line: str, next_line: str) -> tuple[bool, str | None]:
    s = line.strip()
    if not s or len(s) > _SHORT_LINE:
        return False, None
    if s.endswith(".") and len(s.split()) > 12:
        return False, None
    lower = s.lower().rstrip(":").strip()
    if lower in SECTION_VOCAB:
        return True, SECTION_VOCAB[lower]
    if _NUMBERED_RE.match(s) and len(s.split()) <= 10:
        base = re.sub(r"^\d+(?:\.\d+)*[.)]\s*", "", lower).rstrip(":").strip()
        if base in SECTION_VOCAB:
            return True, SECTION_VOCAB[base]
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False, None
    if len(letters) >= 2 and all(c.isupper() for c in letters) and len(s.split()) <= 12:
        base = lower.rstrip(":")
        if base in SECTION_VOCAB:
            return True, SECTION_VOCAB[base]
        return True, None
    # Title Case heading, short, no sentence ending
    words = s.split()
    if 1 <= len(words) <= 8 and not s.endswith(_SENTENCE_ENDINGS):
        caps = sum(1 for w in words if w[:1].isupper())
        if caps >= max(1, len(words) - 1):
            base = lower.rstrip(":")
            if base in SECTION_VOCAB:
                return True, SECTION_VOCAB[base]
    if s.endswith(":") and len(s.split()) <= 10 and not any(
        ch in s for ch in _SENTENCE_ENDINGS[:-1]
    ):
        return True, None
    return False, None


def detect_structure(pages: list[tuple[int, str]]) -> tuple[str | None, list[DetectedSection]]:
    """pages: list of (page_number, text). Returns (title, sections)."""
    sections: list[DetectedSection] = []
    title: str | None = None

    lines: list[tuple[int, str]] = []
    for pn, text in pages:
        for line in text.splitlines():
            lines.append((pn, line))

    # Title detection: first meaningful short line
    for _, line in lines:
        s = line.strip()
        if not s:
            continue
        if len(s) <= 100 and len(s.split()) <= 12 and not s.endswith(_SENTENCE_ENDINGS[:4]):
            # candidate; check it's not a known section header better treated as title
            if s.lower().rstrip(":") not in SECTION_VOCAB:
                title = s
            break
        break  # first meaningful line is too long -> no reliable title
    else:
        title = None

    current: DetectedSection | None = None
    order = 0
    body: list[str] = []
    for pn, line in lines:
        s = line.strip()
        if not s:
            if current:
                body.append("")
            continue
        nxt = ""
        is_head, vocab = _is_heading(s, nxt)
        if is_head and (current is None or vocab or s.isupper() or _NUMBERED_RE.match(s) or s.endswith(":")):
            if current:
                current.text = "\n".join(body).strip()
                sections.append(current)
            current = DetectedSection(
                title=s.rstrip(":").strip(),
                section_type="section",
                page_number=pn,
                order_index=order,
                text="",
                matched_vocab=vocab,
            )
            order += 1
            body = []
        else:
            if current is None:
                current = DetectedSection(
                    title="Document", section_type="section", page_number=pn,
                    order_index=0, text="", matched_vocab=None,
                )
                order += 1
            body.append(s)
    if current:
        current.text = "\n".join(body).strip()
        sections.append(current)

    # Preamble (text before first real heading) becomes "Header / Preamble" section
    if sections and sections[0].matched_vocab is None and sections[0].title == "Document":
        sections[0].title = "Preamble"

    return title, sections

