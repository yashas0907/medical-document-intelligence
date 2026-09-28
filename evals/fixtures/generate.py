"""Generate synthetic demo/evaluation fixtures.

All content is fully fictional (no real patient data). Documents generated:
- lab_report_visit1.txt / lab_report_visit2.txt (plain text with lab lines)
- clinical_note.docx (DOCX with headings + table)
- radiology_report.pdf (text PDF with a findings section)
- lab_table_report.pdf (text PDF containing a real table)
- multi_page_report.pdf (5 pages, headers/footers to exercise cleaning)
- scanned_lab.txt.pdf is intentionally NOT created here; a scanned-style PDF
  (image-only) is generated for OCR tests when PIL is available.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "data" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

LAB_VISIT1 = """City General Hospital - Laboratory Report

Patient Information
Patient: J. Doe (fictional)
DOB: 12 March 1985
Referring Physician: Dr. Emily Carter
MRN: 000-0000

Specimen
Type: Venous blood
Collected: 2024-03-05 at 08:30
Received: 2024-03-05

Laboratory Results
Hemoglobin: 13.2 g/dL [12.0-16.0]
Hematocrit: 39.1 % [36.0-46.0]
WBC: 6.7 x10^9/L [4.0-11.0]
Platelets: 245 x10^9/L [150-400]
Glucose: 108 mg/dL [70-100] (H)
Creatinine: 0.9 mg/dL [0.6-1.2]
HbA1c: 6.4 % [4.0-5.6] (H)
LDL: 118 mg/dL [0-100] (H)
HDL: 44 mg/dL [40-60]
Triglycerides: 152 mg/dL [0-150] (H)
TSH: 2.1 mIU/L [0.4-4.0]

Medications
Metformin 500 mg twice daily.
Lisinopril 10 mg once daily.
Atorvastatin 20 mg at bedtime.

Assessment and Plan
Type 2 diabetes mellitus with HbA1c above target. Continue current medications.
Repeat HbA1c in 3 months. Patient counseled on diet and exercise.
Monitor renal function annually.

Notes
Patient reports occasional headaches. No chest pain. No shortness of breath.
BP 128/82 mmHg. Temperature 36.8 C. Follow-up scheduled 2024-06-10.
"""

LAB_VISIT2 = """City General Hospital - Laboratory Report

Patient Information
Patient: J. Doe (fictional)
DOB: 12 March 1985
Referring Physician: Dr. Emily Carter
MRN: 000-0000

Specimen
Type: Venous blood
Collected: 2024-06-10 at 08:15
Received: 2024-06-10

Laboratory Results
Hemoglobin: 11.8 g/dL [12.0-16.0] (L)
Hematocrit: 35.4 % [36.0-46.0] (L)
WBC: 7.2 x10^9/L [4.0-11.0]
Platelets: 238 x10^9/L [150-400]
Glucose: 132 mg/dL [70-100] (H)
Creatinine: 1.0 mg/dL [0.6-1.2]
HbA1c: 7.1 % [4.0-5.6] (H)
LDL: 112 mg/dL [0-100] (H)
HDL: 46 mg/dL [40-60]
Triglycerides: 140 mg/dL [0-150]
TSH: 2.4 mIU/L [0.4-4.0]

Medications
Metformin 1000 mg twice daily.
Atorvastatin 20 mg at bedtime.
Ferrous sulfate 325 mg once daily.

Assessment and Plan
Type 2 diabetes mellitus with worsening HbA1c. Metformin dose increased.
Anemia workup initiated; iron studies ordered.
Repeat labs in 3 months.

Notes
Patient reports fatigue. No chest pain. No shortness of breath.
BP 134/86 mmHg. Temperature 36.9 C. Follow-up scheduled 2024-09-15.
"""

CLINICAL_NOTE = """CLINICAL NOTE - Internal Medicine
Northside Clinic (fictional)

Patient Information
Name: A. Smith (fictional)
Age: 54
Provider: Dr. R. Patel

History
Patient presents with persistent knee pain for 3 months. No trauma history.
Type 2 diabetes mellitus, diagnosed 2015. Hypertension since 2018.

Medications
Metformin 1000 mg twice daily.
Lisinopril 20 mg once daily.
Ibuprofen 400 mg as needed for pain.

Vital Signs
BP 142/88 mmHg. Pulse 76 bpm. Temperature 37.0 C.

Assessment and Plan
Osteoarthritis of the right knee suspected. X-ray ordered.
Continue current diabetes medications. NSAIDs with caution given renal history.
Follow-up in 6 weeks.
"""


def build_all() -> None:
    # TXT fixtures
    (OUT / "lab_report_visit1.txt").write_text(LAB_VISIT1, encoding="utf-8")
    (OUT / "lab_report_visit2.txt").write_text(LAB_VISIT2, encoding="utf-8")

    # DOCX fixture
    from docx import Document

    doc = Document()
    doc.add_heading("Clinical Note - Internal Medicine", 0)
    p = doc.add_paragraph("Northside Clinic (fictional)")
    for section in CLINICAL_NOTE.split("\n\n"):
        lines = [l for l in section.splitlines() if l.strip()]
        if not lines:
            continue
        title = lines[0]
        if title.strip().startswith("CLINICAL"):
            continue
        doc.add_heading(title, level=1)
        body = "\n".join(lines[1:])
        if body.strip():
            doc.add_paragraph(body)
    # Vitals table
    table = doc.add_table(rows=4, cols=2)
    table.style = "Table Grid"
    cells = [
        ("Vital Sign", "Value"),
        ("Blood Pressure", "142/88 mmHg"),
        ("Pulse", "76 bpm"),
        ("Temperature", "37.0 C"),
    ]
    for i, (k, v) in enumerate(cells):
        table.rows[i].cells[0].text = k
        table.rows[i].cells[1].text = v
    doc.save(OUT / "clinical_note.docx")

    # PDF fixtures via pymupdf
    import fitz

    def text_pdf(path: str, title: str, sections: list[tuple[str, str]],
                 header: str | None = None, footer_start_page: int = 1):
        pdf = fitz.open()
        page = pdf.new_page(width=612, height=792)
        y = 72

        def write(text, size=11, bold=False, y=y):
            font = "helv" if not bold else "hebo"
            rc = page.insert_text((72, y), text, fontname=font, fontsize=size)
            return y + size + 6

        y = write(title, 16, True)
        for heading, body in sections:
            if y > 640:
                page = pdf.new_page(width=612, height=792)
                y = 72
            y = write(heading, 12, True)
            for line in body.splitlines():
                if not line.strip():
                    y += 6
                    continue
                if y > 720:
                    page = pdf.new_page(width=612, height=792)
                    y = 72
                y = write(line)
        pdf.save(path)
        pdf.close()

    text_pdf(
        str(OUT / "radiology_report.pdf"),
        "RADIOLOGY REPORT - Chest X-Ray",
        [
            ("Patient Information", "Patient: K. Lee (fictional)\nDOB: 2 July 1978\nExam date: 2024-05-12"),
            (
                "Findings",
                "PA and lateral views of the chest were obtained. The lungs are clear "
                "bilaterally. No focal consolidation, effusion, or pneumothorax is seen. "
                "Cardiomediastinal silhouette is within normal limits. No acute bony findings.",
            ),
            (
                "Impression",
                "No acute cardiopulmonary abnormality. Clinical correlation recommended.",
            ),
        ],
    )

    # Lab table PDF (manual grid: rects + text rows)
    pdf = fitz.open()
    page = pdf.new_page(width=612, height=792)
    page.insert_text((72, 72), "Metropolitan Lab - Complete Blood Panel", fontname="hebo", fontsize=14)
    page.insert_text((72, 100), "Patient: T. Nguyen (fictional)   Collected: 2024-01-20", fontsize=10)
    rows = [
        ("Test", "Value", "Unit", "Reference Range", "Flag"),
        ("Hemoglobin", "14.1", "g/dL", "12.0-16.0", ""),
        ("WBC", "5.9", "x10^9/L", "4.0-11.0", ""),
        ("Platelets", "310", "x10^9/L", "150-400", ""),
        ("Sodium", "138", "mmol/L", "135-145", ""),
        ("Potassium", "5.2", "mmol/L", "3.5-5.1", "H"),
        ("ALT", "62", "U/L", "7-56", "H"),
        ("AST", "58", "U/L", "10-40", "H"),
    ]
    x0, y0, x1 = 72, 140, 540
    col_w = (x1 - x0) / len(rows[0])
    row_h = 22
    for r_i, row in enumerate(rows):
        y = y0 + r_i * row_h
        page.draw_rect(fitz.Rect(x0, y, x1, y + row_h), color=(0, 0, 0), width=0.7)
        for c_i, cell in enumerate(row):
            cx = x0 + c_i * col_w
            if c_i > 0:
                page.draw_line(fitz.Point(cx, y), fitz.Point(cx, y + row_h), color=(0, 0, 0), width=0.5)
            page.insert_text((cx + 4, y + 15), str(cell), fontsize=9,
                             fontname="hebo" if r_i == 0 else "helv")
    page.insert_text((72, y0 + len(rows) * row_h + 30), "Impression: Mild transaminitis noted. Repeat in 4 weeks.", fontsize=10)
    pdf.save(str(OUT / "lab_table_report.pdf"))
    pdf.close()

    # Multi-page PDF with repeated header/footer (tests cleaning)
    pdf = fitz.open()
    for i in range(5):
        page = pdf.new_page(width=612, height=792)
        page.insert_text((72, 40), f"Confidential - Riverside Health System   Page {i+1} of 5", fontsize=8)
        page.insert_text((72, 70), f"Progress Note - Day {i+1}", fontname="hebo", fontsize=12)
        body = (
            f"Day {i+1}: Patient stable. Pain controlled with oral analgesia. "
            f"Wound clean and dry. Vitals recorded: BP 126/80 mmHg, pulse 74 bpm. "
            f"Labs pending. Physical therapy consultation requested for {['mobility', 'strength training', 'gait', 'balance', 'endurance'][i]}. "
            f"Plan: continue current management. Attending: Dr. S. Omar."
        )
        page.insert_text((72, 100), body, fontsize=10)
    pdf.save(str(OUT / "multi_page_report.pdf"))
    pdf.close()

    # Scanned-style (image-only) PDF for OCR path — render text to pixmap
    try:
        src = fitz.open()
        page = src.new_page(width=612, height=792)
        page.insert_text((72, 72), "SCANNED LAB REPORT", fontname="hebo", fontsize=14)
        page.insert_text(
            (72, 110),
            "Glucose: 99 mg/dL [70-100]\nCreatinine: 1.1 mg/dL [0.6-1.2]\nPotassium: 4.2 mmol/L [3.5-5.1]",
            fontsize=12,
        )
        pix = page.get_pixmap(dpi=150)
        img_pdf = fitz.open()
        img_page = img_pdf.new_page(width=612, height=792)
        img_page.insert_image(fitz.Rect(0, 0, 612, 792), stream=pix.tobytes("png"))
        img_pdf.save(str(OUT / "scanned_lab_report.pdf"))
        img_pdf.close()
        src.close()
    except Exception as e:  # PIL may be absent in some envs
        print(f"skipped scanned fixture: {e}")

    print("fixtures written to", OUT)
    for f in sorted(OUT.iterdir()):
        print(" -", f.name, f"{f.stat().st_size} bytes")


if __name__ == "__main__":
    build_all()
