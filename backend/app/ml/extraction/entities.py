"""Deterministic medical entity extraction (rules + curated vocabulary).

Design decision: extraction is RULE-BASED, not LLM. Why:
- reproducible & testable (precision/recall measurable on fixtures)
- auditable (every entity links to snippet + page)
- free (no API cost on every upload)
- honest: inference-free extraction of what is *explicitly written*

Normalization only where safe (verified abbreviation map, ISO dates, unit
canonicalization). Unknown → preserve original, mark confidence < 1.
"""
import re
from dataclasses import dataclass, field

# --- Verified abbreviation map (subset of clinical shorthand) ---------------
# Only high-confidence, unambiguous expansions. Anything not here stays raw.
ABBREVIATIONS = {
    "bp": "blood pressure",
    "bpm": "beats per minute",
    "mmhg": "mmHg",
    "hgb": "hemoglobin",
    "hgbn": "hemoglobin",
    "wbc": "white blood cell count",
    "rbc": "red blood cell count",
    "plt": "platelet count",
    "cr": "creatinine",
    "bun": "blood urea nitrogen",
    "alt": "alanine aminotransferase",
    "ast": "aspartate aminotransferase",
    "hba1c": "HbA1c",
    "hdl": "HDL cholesterol",
    "ldl": "LDL cholesterol",
    "tsh": "thyroid stimulating hormone",
    "ekg": "electrocardiogram",
    "ecg": "electrocardiogram",
    "er": "emergency room",
    "ed": "emergency department",
    "icu": "intensive care unit",
    "bid": "twice daily",
    "tid": "three times daily",
    "qid": "four times daily",
    "qd": "once daily",
    "prn": "as needed",
    "po": "by mouth",
    "iv": "intravenous",
    "im": "intramuscular",
    "sx": "symptoms",
    "dx": "diagnosis",
    "hx": "history",
    "fx": "fracture",
    "mi": "myocardial infarction",
    "chf": "congestive heart failure",
    "copd": "chronic obstructive pulmonary disease",
    "uti": "urinary tract infection",
    "dm": "diabetes mellitus",
    "htn": "hypertension",
    "cad": "coronary artery disease",
    "gerd": "gastroesophageal reflux disease",
    "oa": "osteoarthritis",
    "ra": "rheumatoid arthritis",
    "cef": "caffeine",
    "npo": "nothing by mouth",
    "sob": "shortness of breath",
    "cp": "chest pain",
}

# Common test names for lab measurement context
TEST_NAMES = [
    "hemoglobin", "hematocrit", "wbc", "rbc", "platelet", "platelets",
    "creatinine", "bun", "sodium", "potassium", "chloride", "bicarbonate",
    "glucose", "hba1c", "alt", "ast", "alp", "bilirubin", "albumin",
    "total protein", "calcium", "magnesium", "phosphorus", "tsh", "t4",
    "vitamin d", "vitamin b12", "ferritin", "iron", "ldl", "hdl",
    "triglycerides", "total cholesterol", "cholesterol", "uric acid",
    "esr", "crp", "inr", "ptt", "inr/pt", "d-dimer", "troponin",
    "hemoglobin a1c", "ferritin", "tsh", "flying pain",
]

MEDICATION_SUFFIXES = (
    "azole", "pril", "sartan", "olol", "statin", "mycin", "cillin",
    "floxacin", "dipine", "prazole", "profen", "codone", "tramadol",
    "metformin", "insulin", "warfarin", "heparin", "prednisone",
    "ibuprofen", "aspirin", "acetaminophen", "paracetamol", "lisinopril",
    "amlodipine", "atorvastatin", "simvastatin", "omeprazole", "pantoprazole",
    "gabapentin", "sertraline", "fluoxetine", "albuterol", "salbutamol",
)

# ---------------------------------------------------------------------------
# Regex bank
# ---------------------------------------------------------------------------
# Dates: ISO, US, European, textual
_DATE_PATTERNS = [
    (
        re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"),
        "iso",
    ),
    (
        re.compile(
            r"\b((?:January|February|March|April|May|June|July|August|September|October|"
            r"November|December)\s+\d{1,2},?\s+\d{4})\b",
            re.IGNORECASE,
        ),
        "us_textual",
    ),
    (
        re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"),
        "us_numeric",
    ),
    (
        re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b"),
        "dash",
    ),
]

_DOSE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|kg|ml|mmol|units?|iu)\b", re.IGNORECASE
)
_VITALS_BP_RE = re.compile(r"\b(\d{2,3})\s*/\s*(\d{2,3})\s*(?:mmhg|mm hg)?\b", re.IGNORECASE)
_TEMPERATURE_RE = re.compile(
    r"\b(\d{2,3}(?:\.\d+)?)\s*(?:°|deg(?:rees)?)?\s*(c|f|celsius|fahrenheit)\b", re.IGNORECASE
)
_ORG_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z&.]*\s){0,2}(?:Hospital|Clinic|Medical Center|Health System|"
    r"Laboratory|Lab(?:s|oratories)?|Institute|University)\b)"
)
_PERSON_DR_RE = re.compile(r"\b(Dr\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b")
_LAB_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9 ()/\-']{0,40}?)\s*[:|\t]\s*(?P<value>\d+(?:\.\d+)?)"
    r"\s*(?P<unit>[a-zA-Z%µ°][a-zA-Z0-9^/°%.\-]{0,10})?\s*(?:\[(?P<range>[^\]]+)\])?\s*(?P<flag>[HhLl]\b|\(H\)|\(L\))?"
    r"\s*$"
)


def _snippet(text: str, pos: int, span: int, width: int = 120) -> str:
    start = max(0, pos - width // 2)
    end = min(len(text), pos + span + width // 2)
    return text[start:end].replace("\n", " ").strip()


@dataclass
class EntityHit:
    entity_type: str
    raw_text: str
    normalized_text: str | None
    normalized_confidence: float | None
    source_snippet: str
    page_number: int
    section_id: str | None = None
    chunk_id: str | None = None


@dataclass
class MeasurementHit:
    name: str
    value_raw: str
    value_num: float | None
    unit: str | None
    reference_range: str | None
    flag: str | None
    source_snippet: str
    page_number: int
    chunk_id: str | None = None
    table_row: dict | None = None


@dataclass
class ExtractionResult:
    entities: list[EntityHit] = field(default_factory=list)
    measurements: list[MeasurementHit] = field(default_factory=list)


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def normalize_date(raw: str, fmt: str) -> tuple[str | None, float]:
    """Return (ISO date or None, confidence). Original preserved by caller."""
    raw = raw.strip()
    try:
        if fmt == "iso":
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return f"{y:04d}-{mo:02d}-{d:02d}", 1.0
        if fmt == "us_textual":
            m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
            mo = _MONTHS.get(m.group(1).lower())
            if mo:
                return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}", 1.0
            return None, 0.3
        if fmt == "us_numeric":
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
                return f"{y:04d}-{mo:02d}-{d:02d}", 0.9  # US assumption
            return None, 0.3
        if fmt == "dash":
            m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})", raw)
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
                return f"{y:04d}-{mo:02d}-{d:02d}", 0.9
            return None, 0.3
    except (ValueError, AttributeError):
        return None, 0.2
    return None, 0.2


UNIT_CANON = {
    "mg": "mg", "mcg": "mcg", "g": "g", "kg": "kg", "ml": "mL", "mmol": "mmol/L",
    "unit": "units", "units": "units", "iu": "IU", "mmhg": "mmHg",
    "g/dl": "g/dL", "g/l": "g/L", "mg/dl": "mg/dL", "mg/dl.": "mg/dL",
}


def normalize_unit(unit: str | None) -> tuple[str | None, float]:
    if not unit:
        return None, 1.0
    u = unit.strip().lower()
    if u in UNIT_CANON:
        return UNIT_CANON[u], 1.0
    return unit.strip(), 0.5  # unknown unit → preserve original, uncertain


def _norm_month_textdate(match: re.Match) -> str:
    return match.group(0)


def extract_from_text(
    text: str, page_number: int, section_id: str | None = None, chunk_id: str | None = None
) -> ExtractionResult:
    res = ExtractionResult()
    seen: set[tuple[str, str, int]] = set()

    def add(ent_type: str, raw: str, norm: str | None, conf: float | None, pos: int):
        key = (ent_type, raw.strip(), page_number)
        if key in seen:
            return
        seen.add(key)
        res.entities.append(
            EntityHit(
                entity_type=ent_type,
                raw_text=raw.strip(),
                normalized_text=norm,
                normalized_confidence=conf,
                source_snippet=_snippet(text, pos, len(raw)),
                page_number=page_number,
                section_id=section_id,
                chunk_id=chunk_id,
            )
        )

    # Dates
    for pat, fmt in _DATE_PATTERNS:
        for m in pat.finditer(text):
            iso, conf = normalize_date(m.group(1), fmt)
            add("date", m.group(1), iso, conf, m.start())

    # Medications (suffix + curated list)
    for m in re.finditer(r"\b([a-z][a-z\-]{4,}(?:" + "|".join(MEDICATION_SUFFIXES) + r"))\b", text, re.IGNORECASE):
        w = m.group(1)
        if len(w) > 4:
            add("medication", w, w.lower(), 0.9, m.start())
    for med in ("Metformin", "Lisinopril", "Aspirin", "Ibuprofen", "Omeprazole",
                "Warfarin", "Insulin", "Prednisone", "Atorvastatin", "Amlodipine",
                "Acetaminophen", "Paracetamol", "Sertraline", "Gabapentin", "Albuterol",
                "Ferrous Sulfate", "Furosemide", "Levothyroxine", "Losartan",
                "Hydrochlorothiazide", "Metoprolol", "Pantoprazole", "Salbutamol"):
        for m in re.finditer(re.escape(med), text, re.IGNORECASE):
            add("medication", m.group(0), med.lower(), 1.0, m.start())

    # Dosages
    for m in _DOSE_RE.finditer(text):
        unit_norm, uconf = normalize_unit(m.group(2))
        add(
            "dose",
            m.group(0).strip(),
            f"{m.group(1)} {unit_norm}" if unit_norm else m.group(0),
            uconf,
            m.start(),
        )

    # Blood pressure
    for m in _VITALS_BP_RE.finditer(text):
        add("vitals", m.group(0), f"{m.group(1)}/{m.group(2)} mmHg", 1.0, m.start())

    # Temperature
    for m in _TEMPERATURE_RE.finditer(text):
        scale = m.group(2).lower()[0]
        add("vitals", m.group(0), f"{m.group(1)}°{'C' if scale == 'c' else 'F'}", 1.0, m.start())

    # Organizations
    for m in _ORG_RE.finditer(text):
        add("organization", m.group(1), None, None, m.start())

    # People (doctors)
    for m in _PERSON_DR_RE.finditer(text):
        add("person", m.group(1), None, None, m.start())

    # Abbreviations (only those in verified map)
    for m in re.finditer(r"\b([a-zA-Z]{2,6})\b", text):
        ab = m.group(1)
        if ab.lower() in ABBREVIATIONS:
            add("abbreviation", ab, ABBREVIATIONS[ab.lower()], 1.0, m.start())

    # Measurements from "Name: value unit [range] flag" patterns
    for line in text.splitlines():
        lm = _LAB_LINE_RE.match(line.strip())
        if lm and lm.group("value"):
            name = lm.group("name").strip()
            if len(name) < 2 or name.lower() in {"note", "notes", "date", "page"}:
                continue
            unit_norm, uconf = normalize_unit(lm.group("unit"))
            try:
                vnum = float(lm.group("value"))
            except ValueError:
                vnum = None
            flag = None
            if lm.group("flag"):
                flag = lm.group("flag").strip("()").upper()
            res.measurements.append(
                MeasurementHit(
                    name=name.title(),
                    value_raw=lm.group("value"),
                    value_num=vnum,
                    unit=unit_norm or lm.group("unit"),
                    reference_range=lm.group("range"),
                    flag=flag,
                    source_snippet=line.strip()[:300],
                    page_number=page_number,
                    chunk_id=chunk_id,
                )
            )

    return res


def extract_from_table_row(row: dict, page_number: int) -> list[MeasurementHit]:
    """Build measurement hits from a parsed table row dict with standard keys."""
    out: list[MeasurementHit] = []
    name = str(row.get("test") or row.get("name") or row.get("parameter") or "").strip()
    value = str(row.get("value") or row.get("result") or "").strip()
    if not name or not value:
        return out
    m = re.match(r"(\d+(?:\.\d+)?)", value)
    vnum = float(m.group(1)) if m else None
    unit = str(row.get("unit") or "").strip() or None
    unit_norm, _ = normalize_unit(unit)
    ref = str(row.get("reference_range") or row.get("range") or "").strip() or None
    flag_raw = str(row.get("flag") or "").strip()
    flag = flag_raw.upper()[:1] if flag_raw.upper()[:1] in ("H", "L") else None
    out.append(
        MeasurementHit(
            name=name,
            value_raw=value,
            value_num=vnum,
            unit=unit_norm or unit,
            reference_range=ref,
            flag=flag,
            source_snippet=" | ".join(str(v) for v in row.values() if v),
            page_number=page_number,
            table_row={k: str(v) for k, v in row.items() if v},
        )
    )
    return out
