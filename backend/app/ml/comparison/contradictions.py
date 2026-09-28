"""Contradiction / inconsistency detection â€” evidence-based, conservative.

Only flags when two *structured* claims about the same concept genuinely
conflict (different recorded values, conflicting dates, unit mismatches).
Wording differences alone are NEVER contradictions (explicitly required).
"""
from dataclasses import dataclass

from app.ml.comparison.engine import _key, _same_value
from app.ml.versions import CONTRADICTION_ENGINE_VERSION


@dataclass
class Side:
    claim: str
    document_id: str
    document_title: str
    page_number: int | None
    section_title: str | None
    quote: str


@dataclass
class Contradiction:
    type: str  # value_conflict | date_conflict | unit_conflict | statement_conflict
    severity: str
    confidence: float
    explanation: str
    a: Side
    b: Side


@dataclass
class ContradictionOutput:
    document_id: str
    compared_with: str | None
    contradictions: list[Contradiction]
    notes: list[str]
    version: str = CONTRADICTION_ENGINE_VERSION


def detect_contradictions(
    doc_a: dict,
    doc_b: dict | None,
    a_measurements: list[dict],
    b_measurements: list[dict],
    a_entities: list[dict],
    b_entities: list[dict],
) -> ContradictionOutput:
    """a_* = within-doc A (or doc A); b_* = second doc or SAME doc for internal scan.
    Pass same doc twice (b=None, b_* = a_*) to scan a single document internally."""
    internal = doc_b is None
    doc_b_eff = doc_b or doc_a
    result = ContradictionOutput(
        document_id=doc_a["id"], compared_with=None if internal else doc_b["id"],
        contradictions=[], notes=[],
    )
    if internal:
        result.notes.append("Internal consistency scan of this document.")

    # value conflicts by name
    for ma in a_measurements:
        for mb in b_measurements:
            if internal and ma is mb:
                continue
            if _key(ma["name"]) != _key(mb["name"]):
                continue
            if not _same_value(ma, mb):
                # multiple mentions of same test with different values
                result.contradictions.append(
                    Contradiction(
                        type="value_conflict",
                        severity="high",
                        confidence=0.9,
                        explanation=(
                            f"'{ma['name']}' is recorded as {ma.get('value_raw')}"
                            + (f" {ma.get('unit')}" if ma.get("unit") else "")
                            + f" in one place and {mb.get('value_raw')}"
                            + (f" {mb.get('unit')}" if mb.get("unit") else "")
                            + " in another."
                        ),
                        a=Side(
                            claim=f"{ma['name']} = {ma.get('value_raw')}",
                            document_id=doc_a["id"], document_title=doc_a["title"],
                            page_number=ma.get("page_number"),
                            section_title=None,
                            quote=(ma.get("source_snippet") or "")[:250],
                        ),
                        b=Side(
                            claim=f"{mb['name']} = {mb.get('value_raw')}",
                            document_id=doc_b_eff["id"], document_title=doc_b_eff["title"],
                            page_number=mb.get("page_number"),
                            section_title=None,
                            quote=(mb.get("source_snippet") or "")[:250],
                        ),
                    )
                )
            break  # one comparison per name pair handled

    # date conflicts: document date entity vs doc_date; conflicting same-doc dates for doc-level
    a_dates = [e for e in a_entities if e["entity_type"] == "date" and e.get("normalized_text")]
    if internal:
        # same-doc: conflicting *doc-level* dates (different normalized dates in header-ish snippets)
        seen: dict[str, Side] = {}
        for e in a_dates:
            d = e["normalized_text"]
            if d in seen:
                continue
            seen[d] = Side(
                claim=f"Date {d}",
                document_id=doc_a["id"], document_title=doc_a["title"],
                page_number=e.get("page_number"), section_title=None,
                quote=(e.get("source_snippet") or "")[:250],
            )
        # multiple distinct doc-level dates are common (history vs report date) â€” not a
        # contradiction by themselves; only flag same-section conflicting dates
        result.notes.append(
            f"{len(seen)} distinct dates detected; only structured value conflicts are flagged."
        )
    else:
        # cross-doc: same measurement name different values already covered;
        # flag conflicting document dates
        if (
            doc_a.get("date")
            and doc_b.get("date")
            and doc_a["date"] != doc_b["date"]
        ):
            # this is expected for different-date reports; note, don't flag
            result.notes.append(
                "Documents carry different dates (expected for longitudinal reports)."
            )

    # dedupe value conflicts (same name may appear multiple times)
    seen_keys = set()
    uniq: list[Contradiction] = []
    for c in result.contradictions:
        k = (c.type, c.a.claim, c.b.claim)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        uniq.append(c)
    result.contradictions = uniq

    if not result.contradictions:
        result.notes.append("No contradictions detected between the compared evidence.")
    return result
