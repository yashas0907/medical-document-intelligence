"""Unit tests: cleaning, structure detection, entity extraction, normalization."""
from app.ml.extraction.entities import (
    extract_from_text,
    normalize_date,
    normalize_unit,
)
from app.ml.ingestion.cleaning import clean_pages
from app.ml.ingestion.structure import detect_structure


class TestCleaning:
    def test_repeated_headers_removed(self):
        pages = []
        for i in range(5):
            pages.append(f"Confidential - Riverside Health\nPage {i+1} of 5\nBody content {i} with real text here.")
        cleaned, report = clean_pages(pages)
        assert all("Confidential - Riverside Health" not in p for p in cleaned)
        assert report.removed_header_footer_lines >= 5

    def test_page_numbers_removed(self):
        cleaned, _ = clean_pages(["Page 1 of 3\nreal text", "Page 2 of 3\nmore text", "Page 3 of 3\nend"])
        assert all("Page" not in p or "real" in p for p in cleaned)

    def test_control_chars_stripped(self):
        cleaned, _ = clean_pages(["hello\x00world\x07end"])
        assert "\x00" not in cleaned[0]

    def test_short_docs_kept(self):
        pages = ["only one page here"]
        cleaned, _ = clean_pages(pages)
        assert cleaned[0] == "only one page here"


class TestStructure:
    def test_sections_detected(self):
        text = """Patient Information
Name: Test Patient
DOB: 1980-01-01

Laboratory Results
Hemoglobin: 13.2 g/dL
Glucose: 108 mg/dL

Medications
Metformin 500 mg.
"""
        title, sections = detect_structure([(1, text)])
        titles = [s.title for s in sections]
        assert "Patient Information" in titles
        assert "Laboratory Results" in titles
        assert "Medications" in titles
        lab = next(s for s in sections if s.title == "Laboratory Results")
        assert "Hemoglobin" in lab.text

    def test_title_detection(self):
        text = "City General Hospital Report\n\nBody content follows here with plenty of words to not be a heading."
        title, _ = detect_structure([(1, text)])
        assert title == "City General Hospital Report"

    def test_vocab_matched(self):
        text = "Assessment and Plan\nContinue current medications."
        _, sections = detect_structure([(1, text)])
        assert any(s.matched_vocab == "assessment" for s in sections)


class TestExtraction:
    def test_date_formats(self):
        assert normalize_date("2024-03-05", "iso") == ("2024-03-05", 1.0)
        assert normalize_date("March 5, 2024", "us_textual") == ("2024-03-05", 1.0)
        iso, conf = normalize_date("03/05/2024", "us_numeric")
        assert iso == "2024-03-05" and conf == 0.9
        assert normalize_date("99/99/9999", "us_numeric")[0] is None

    def test_units(self):
        assert normalize_unit("mg") == ("mg", 1.0)
        assert normalize_unit("ml") == ("mL", 1.0)
        assert normalize_unit("parsecs") == ("parsecs", 0.5)

    def test_entities_from_lab_text(self):
        text = (
            "Patient seen on 2024-03-05. Dr. Emily Carter prescribed Metformin 500 mg. "
            "Hemoglobin: 13.2 g/dL [12.0-16.0]. BP 128/82 mmHg. City General Hospital."
        )
        res = extract_from_text(text, page_number=1)
        types = {e.entity_type for e in res.entities}
        assert "date" in types
        assert "person" in types
        assert "medication" in types
        assert "dose" in types
        assert "vitals" in types
        assert "organization" in types
        date_e = next(e for e in res.entities if e.entity_type == "date")
        assert date_e.normalized_text == "2024-03-05"
        assert date_e.normalized_confidence == 1.0
        assert date_e.source_snippet  # provenance preserved

    def test_measurement_parsing(self):
        text = "Hemoglobin: 13.2 g/dL [12.0-16.0]\nGlucose: 108 mg/dL [70-100] (H)"
        res = extract_from_text(text, page_number=2)
        assert len(res.measurements) == 2
        hgb = next(m for m in res.measurements if m.name == "Hemoglobin")
        assert hgb.value_num == 13.2
        assert hgb.unit == "g/dL"
        assert hgb.reference_range == "12.0-16.0"
        glucose = next(m for m in res.measurements if m.name == "Glucose")
        assert glucose.flag == "H"
        assert glucose.page_number == 2

    def test_abbreviation_normalization(self):
        text = "WBC and HbA1c were measured. BP normal."
        res = extract_from_text(text, page_number=1)
        abbr = {e.raw_text: e.normalized_text for e in res.entities if e.entity_type == "abbreviation"}
        assert abbr.get("WBC") == "white blood cell count"
        assert abbr.get("BP") == "blood pressure"

    def test_uncertain_normalization_preserved(self):
        # unknown unit stays raw, marked uncertain
        text = "Special: 42 blobs [1-99]"
        res = extract_from_text(text, page_number=1)
        m = res.measurements[0]
        assert m.value_raw == "42"
        assert m.unit == "blobs"  # preserved original

    def test_no_false_medications(self):
        text = "The patient walked into the consultation room and sat down quietly."
        res = extract_from_text(text, page_number=1)
        assert not any(e.entity_type == "medication" for e in res.entities)
