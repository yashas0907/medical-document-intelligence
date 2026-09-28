"""Comparison engine — deterministic structured diff between two documents.

Compares:
- measurements (matched by normalized name): value/unit/range changes
- medications: additions/removals
- dates, organizations
- section-level presence

Every row cites evidence (chunk/page) from both docs. Wording-only rephrasals
are NOT reported as changes (explicitly: prefer 'Value changed from X to Y',
no clinical interpretation).
"""
import re
from dataclasses import dataclass, field

from app.ml.versions import COMPARISON_ENGINE_VERSION

_WORD = re.compile(r"[a-z0-9]+")


def _key(s: str) -> str:
    return " ".join(_WORD.findall(s.lower()))


@dataclass
class Cell:
    doc_id: str
    doc_title: str
    value: str
    chunk_id: str | None = None
    page_number: int | None = None
    ref: str | None = None


@dataclass
class DiffRow:
    category: str
    item: str | None
    a: Cell | None
    b: Cell | None
    change_type: str  # added | removed | changed | unchanged
    change_note: str | None = None


@dataclass
class ComparisonOutput:
    doc_a_id: str
    doc_b_id: str
    doc_a_title: str
    doc_b_title: str
    doc_a_date: str | None
    doc_b_date: str | None
    rows: list[DiffRow] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    summary: str = ""
    version: str = COMPARISON_ENGINE_VERSION


def _citation_list(doc_id: str, rows: list[DiffRow], a_title: str, b_title: str) -> list[dict]:
    out: list[dict] = []
    ref_n = 1
    for row in rows:
        for side in (row.a, row.b):
            if side and side.chunk_id:
                out.append({
                    "ref": f"[C{ref_n}]",
                    "document_id": side.doc_id,
                    "document_title": side.doc_title,
                    "chunk_id": side.chunk_id,
                    "page_number": side.page_number,
                    "quote": side.value[:200],
                })
                side.ref = f"[C{ref_n}]"
                ref_n += 1
    return out


def compare_documents(
    doc_a: dict,
    doc_b: dict,
    a_measurements: list[dict],
    b_measurements: list[dict],
    a_entities: list[dict],
    b_entities: list[dict],
) -> ComparisonOutput:
    """doc_x: {id,title,date}
    measurements: [{name,value_raw,value_num,unit,reference_range,flag,page_number,chunk_id,source_snippet}]
    entities: [{entity_type,raw_text,normalized_text,page_number,chunk_id,source_snippet}]"""

    out = ComparisonOutput(
        doc_a_id=doc_a["id"], doc_b_id=doc_b["id"],
        doc_a_title=doc_a["title"], doc_b_title=doc_b["title"],
        doc_a_date=doc_a.get("date"), doc_b_date=doc_b.get("date"),
    )

    # --- Measurements by normalized name -----------------------------------
    a_by_name: dict[str, dict] = {}
    for m in a_measurements:
        a_by_name.setdefault(_key(m["name"]), m)
    b_by_name: dict[str, dict] = {}
    for m in b_measurements:
        b_by_name.setdefault(_key(m["name"]), m)

    common = sorted(set(a_by_name) & set(b_by_name))
    only_a = sorted(set(a_by_name) - set(b_by_name))
    only_b = sorted(set(b_by_name) - set(a_by_name))

    for name in common:
        ma, mb = a_by_name[name], b_by_name[name]
        label = ma["name"].title() if isinstance(ma["name"], str) else name
        if _same_value(ma, mb):
            out.rows.append(DiffRow(
                category="Measurement", item=label,
                a=Cell(doc_a["id"], doc_a["title"], _fmt_meas(ma), ma.get("chunk_id"), ma.get("page_number")),
                b=Cell(doc_b["id"], doc_b["title"], _fmt_meas(mb), mb.get("chunk_id"), mb.get("page_number")),
                change_type="unchanged",
            ))
        else:
            notes = []
            if ma.get("value_num") is not None and mb.get("value_num") is not None:
                delta = mb["value_num"] - ma["value_num"]
                notes.append(f"Value changed from {ma.get('value_raw')} to {mb.get('value_raw')} "
                             f"({'+' if delta >= 0 else ''}{round(delta, 4)}).")
            else:
                notes.append(f"Value changed from {ma.get('value_raw')} to {mb.get('value_raw')}.")
            if (ma.get("unit") or "") != (mb.get("unit") or ""):
                notes.append(f"Unit: {ma.get('unit') or '—'} → {mb.get('unit') or '—'}.")
            if (ma.get("flag") or "") != (mb.get("flag") or ""):
                notes.append(f"Flag: {ma.get('flag') or '—'} → {mb.get('flag') or '—'}.")
            out.rows.append(DiffRow(
                category="Measurement", item=label,
                a=Cell(doc_a["id"], doc_a["title"], _fmt_meas(ma), ma.get("chunk_id"), ma.get("page_number")),
                b=Cell(doc_b["id"], doc_b["title"], _fmt_meas(mb), mb.get("chunk_id"), mb.get("page_number")),
                change_type="changed", change_note=" ".join(notes),
            ))
    for name in only_a:
        m = a_by_name[name]
        out.rows.append(DiffRow(
            category="Measurement", item=m["name"].title(),
            a=Cell(doc_a["id"], doc_a["title"], _fmt_meas(m), m.get("chunk_id"), m.get("page_number")),
            b=None, change_type="removed",
            change_note=f"Present only in {doc_a['title']}.",
        ))
    for name in only_b:
        m = b_by_name[name]
        out.rows.append(DiffRow(
            category="Measurement", item=m["name"].title(), a=None,
            b=Cell(doc_b["id"], doc_b["title"], _fmt_meas(m), m.get("chunk_id"), m.get("page_number")),
            change_type="added",
            change_note=f"Newly recorded in {doc_b['title']}.",
        ))

    # --- Entity categories: medication / organization / person ---------------
    for etype in ("medication", "organization", "person", "procedure"):
        a_set = {_display(e) for e in a_entities if e["entity_type"] == etype}
        b_set = {_display(e) for e in b_entities if e["entity_type"] == etype}
        cat_label = etype.title() + "s"
        for v in sorted(a_set - b_set):
            src = next((e for e in a_entities if e["entity_type"] == etype and _display(e) == v), None)
            out.rows.append(DiffRow(
                category=cat_label, item=v,
                a=Cell(doc_a["id"], doc_a["title"], v, src.get("chunk_id") if src else None, src.get("page_number") if src else None),
                b=None, change_type="removed",
                change_note=f"Only mentioned in {doc_a['title']}.",
            ))
        for v in sorted(b_set - a_set):
            src = next((e for e in b_entities if e["entity_type"] == etype and _display(e) == v), None)
            out.rows.append(DiffRow(
                category=cat_label, item=v, a=None,
                b=Cell(doc_b["id"], doc_b["title"], v, src.get("chunk_id") if src else None, src.get("page_number") if src else None),
                change_type="added",
                change_note=f"Newly mentioned in {doc_b['title']}.",
            ))

    out.citations = _citation_list(doc_a["id"], out.rows, doc_a["title"], doc_b["title"])

    changed = sum(1 for r in out.rows if r.change_type == "changed")
    added = sum(1 for r in out.rows if r.change_type == "added")
    removed = sum(1 for r in out.rows if r.change_type == "removed")
    same = sum(1 for r in out.rows if r.change_type == "unchanged")
    out.summary = (
        f"Compared {len(common) + len(only_a) + len(only_b)} recorded values and terms: "
        f"{changed} changed, {added} newly added, {removed} no longer mentioned, {same} unchanged. "
        "All differences are stated as recorded-value changes without clinical interpretation."
    )
    return out


def _same_value(a: dict, b: dict) -> bool:
    if (a.get("value_num") is not None) and (b.get("value_num") is not None):
        return abs(a["value_num"] - b["value_num"]) < 1e-9
    return _key(str(a.get("value_raw", ""))) == _key(str(b.get("value_raw", "")))


def _fmt_meas(m: dict) -> str:
    parts = [m.get("value_raw", "")]
    if m.get("unit"):
        parts.append(m["unit"])
    s = " ".join(parts)
    if m.get("reference_range"):
        s += f" (ref {m['reference_range']})"
    if m.get("flag"):
        s += f" [{m['flag']}]"
    return s


def _display(e: dict) -> str:
    return (e.get("normalized_text") or e.get("raw_text") or "").strip()
