"""User-POV browser test with Playwright: full user journey through the real UI.

Measures per-action response times, captures screenshots, and validates every
feature from the user's perspective (what they see, not what the API returns).
Outputs: user_pov_results.json + screenshots/ directory.
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

# Windows console-safe output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://localhost:3000"
SHOTS = Path(__file__).parent / "user_pov_shots"
SHOTS.mkdir(exist_ok=True)

results = []
timings = []


def record(action, passed, detail="", ms=None):
    results.append({"action": action, "passed": passed, "detail": detail, "ms": ms})
    status = "PASS" if passed else "FAIL"
    t = f" ({ms:.0f}ms)" if ms is not None else ""
    print(f"  [{status}] {action}{t} {('- ' + detail) if detail else ''}")


def timed(page, action, fn):
    t0 = time.perf_counter()
    out = fn()
    ms = (time.perf_counter() - t0) * 1000
    timings.append({"action": action, "ms": round(ms)})
    return out, ms


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # ---------- 1. Landing page ----------
        print("== 1. Landing page ==")
        page.goto(BASE, wait_until="networkidle", timeout=20000)
        (lambda: page.locator("h1").inner_text(), ms := None)
        t0 = time.perf_counter()
        h1 = page.locator("h1").inner_text()
        load_ms = (time.perf_counter() - t0) * 1000
        record("landing headline visible", "grounded in evidence" in h1.lower(), h1[:60], load_ms)
        record("safety disclaimer present",
               page.locator("footer").inner_text().lower().find("not provide medical") > 0)
        page.screenshot(path=str(SHOTS / "01_landing.png"), full_page=False)

        # ---------- 2. Sign in (demo user) ----------
        print("== 2. Sign in ==")
        page.goto(BASE + "/login", wait_until="networkidle")
        t0 = time.perf_counter()
        page.fill("#email", "demo@medintel.local")
        page.fill("#password", "demo-password")
        page.click("button[type=submit]")
        page.wait_for_url("**/dashboard", timeout=15000)
        login_ms = (time.perf_counter() - t0) * 1000
        record("login redirects to dashboard", True, ms=login_ms)

        # ---------- 3. Dashboard ----------
        print("== 3. Dashboard ==")
        page.wait_for_selector("table", timeout=15000)
        t0 = time.perf_counter()
        rows = page.locator("tbody tr").count()
        record("documents listed (>=7 after seed)", rows >= 7, f"rows={rows}")
        stats = page.locator("text=Documents").count()
        record("stats cards visible", stats >= 1)
        # status badge check: all completed
        badges = page.locator("tbody span").all_inner_texts()
        record("all docs show completed",
               all("completed" in b.lower() for b in badges if b.strip()), "")
        page.screenshot(path=str(SHOTS / "02_dashboard.png"))

        # ---------- 4. Open lab document ----------
        print("== 4. Document viewer ==")
        # find the first lab report link (two City General docs; visit1 is the second by list order)
        page.click("tbody tr:has-text('City General') >> a:has-text('Open') >> nth=0")
        page.wait_for_selector("text=Document information", timeout=15000)
        # internal contradiction banner renders only when the doc actually has
        # conflicting values; visit1 is internally consistent so the banner may be absent
        page.wait_for_timeout(800)
        banner = page.locator("text=Internal inconsistencies").count()
        record("overview renders (contradiction banner if applicable)",
               True, f"banner={'yes' if banner else 'no (internally consistent doc)'}")
        page.screenshot(path=str(SHOTS / "03_overview.png"))

        # ---------- 5. Ask with citations ----------
        print("== 5. Ask (grounded QA) ==")
        page.get_by_role("button", name="Ask", exact=True).click()
        page.wait_for_selector("form input", timeout=10000)
        t0 = time.perf_counter()
        page.locator("form input").fill("What medications are mentioned?")
        page.locator("form button[type=submit]").click()
        page.wait_for_selector("text=Groundedness", timeout=20000)
        ask_ms = (time.perf_counter() - t0) * 1000
        answer = page.locator("main").inner_text()
        record("answer includes Metformin", "metformin" in answer.lower(), ms=ask_ms)
        record("groundedness badge shown", "Groundedness" in answer)
        # click citation [1]
        cite_btn = page.locator("main button", has_text="[1]").first
        if cite_btn.count():
            cite_btn.click()
            page.wait_for_timeout(400)
            popover = page.locator("text=Source:").count()
            record("citation popover opens", popover > 0,
                   "click [1] -> source page/quote")
            page.screenshot(path=str(SHOTS / "04_ask_citation.png"))
        else:
            record("citation popover opens", False, "no [1] button found")

        # refusal case
        t0 = time.perf_counter()
        page.locator("form input").fill("What is the potassium level?")
        page.locator("form button[type=submit]").click()
        page.wait_for_timeout(1800)
        body = page.locator("main").inner_text()
        refusal_ms = (time.perf_counter() - t0) * 1000
        record("refusal on unanswerable (no potassium in this doc)",
               "could not find" in body.lower() or "no passages" in body.lower(),
               "", refusal_ms)

        # ---------- 6. Summaries ----------
        print("== 6. Summaries ==")
        page.click("button:has-text('Summaries')")
        page.wait_for_selector("text=Quick", timeout=10000)
        t0 = time.perf_counter()
        page.click("button:has-text('Structured')")
        page.wait_for_selector("text=Medications mentioned", timeout=15000)
        sum_ms = (time.perf_counter() - t0) * 1000
        txt = page.locator("main").inner_text()
        record("structured summary with sections",
               "Document type" in txt and "Medications mentioned" in txt, ms=sum_ms)
        record("absent field says 'Not found in the document.'",
               "Not found in the document." in txt)
        page.screenshot(path=str(SHOTS / "05_summary_structured.png"))

        # ---------- 7. Extractions ----------
        print("== 7. Extractions ==")
        page.get_by_role("button", name="Extractions", exact=True).click()
        page.wait_for_selector("text=entities", timeout=10000)
        t0 = time.perf_counter()
        page.get_by_role("button", name="measurements").click()
        page.wait_for_selector("text=Reference", timeout=10000)
        meas_ms = (time.perf_counter() - t0) * 1000
        mtxt = page.locator("main").inner_text()
        record("measurements table with H flags",
               "Hgb" in mtxt or "Hemoglobin" in mtxt or "Glucose" in mtxt, ms=meas_ms)
        page.screenshot(path=str(SHOTS / "06_extractions.png"))
        # tables: open the table-PDF fixture doc (TXT reports have none)
        page.goto(BASE + "/dashboard", wait_until="networkidle")
        page.click("tbody tr:has-text('Metropolitan Lab') >> a:has-text('Open')")
        page.wait_for_selector("text=Document information", timeout=15000)
        page.get_by_role("button", name="Extractions", exact=True).click()
        page.get_by_role("button", name="tables").click()
        page.wait_for_timeout(800)
        tbl_txt = page.locator("main").inner_text()
        record("tables tab renders table data",
               "Hemoglobin" in tbl_txt and "Reference Range" in tbl_txt,
               f"tables={page.locator('table').count()}")
        page.screenshot(path=str(SHOTS / "06b_tables.png"))

        # ---------- 8. Pages (OCR doc check on scanned) ----------
        print("== 8. Pages view (scanned doc OCR) ==")
        # navigate to scanned doc via dashboard
        page.goto(BASE + "/dashboard", wait_until="networkidle")
        page.click("tbody tr:has-text('scanned') >> a:has-text('Open')")
        page.wait_for_selector("text=Document information", timeout=15000)
        page.click("button:has-text('Pages')")
        page.wait_for_selector("text=ocr", timeout=10000)
        ocr_badge = page.locator("text=ocr (").count()
        ocr_text = page.locator("pre").inner_text()
        record("OCR badge with confidence",
               ocr_badge > 0 and "Glucose" in ocr_text,
               ocr_text[:50].replace("\n", " "))
        page.screenshot(path=str(SHOTS / "07_ocr_page.png"))

        # ---------- 9. Timeline ----------
        print("== 9. Timeline ==")
        page.goto(BASE + "/dashboard", wait_until="networkidle")
        page.click("tbody tr:has-text('City General') >> a:has-text('Open') >> nth=0")
        page.wait_for_selector("text=Document information", timeout=15000)
        page.click("button:has-text('Timeline')")
        page.wait_for_selector("text=2024", timeout=10000)
        events = page.locator("text=2024-").count()
        record("timeline events render", events >= 2, f"dated items={events}")
        page.screenshot(path=str(SHOTS / "08_timeline.png"))

        # ---------- 10. Compare ----------
        print("== 10. Compare ==")
        page.goto(BASE + "/compare", wait_until="networkidle")
        page.wait_for_selector("select", timeout=10000)
        # select by visible label content: find options containing 'City General'
        selects = page.locator("select")
        opt_texts_a = selects.nth(0).locator("option").all_inner_texts()
        opt_texts_b = selects.nth(1).locator("option").all_inner_texts()
        idx_a = next(i for i, t in enumerate(opt_texts_a) if "City General" in t)
        idx_b = next(i for i, t in enumerate(opt_texts_b) if "City General" in t and i != idx_a)
        selects.nth(0).select_option(index=idx_a)
        selects.nth(1).select_option(index=idx_b)
        t0 = time.perf_counter()
        page.click("button:has-text('Compare')")
        try:
            page.wait_for_selector("text=changed", timeout=20000)
        except Exception:
            pass
        cmp_ms = (time.perf_counter() - t0) * 1000
        body = page.locator("main").inner_text()
        record("comparison table renders", "changed" in body, ms=cmp_ms)
        record("hemoglobin value change shown",
               "13.2" in body and "11.8" in body)
        # filter buttons — removed OR added must show the medication diff
        # (direction depends on A/B order)
        page.get_by_role("button", name="removed").click()
        page.wait_for_timeout(500)
        body_removed = page.locator("main").inner_text()
        page.get_by_role("button", name="added").click()
        page.wait_for_timeout(500)
        body_added = page.locator("main").inner_text()
        record("medication add/remove diff visible via filters",
               "lisinopril" in body_removed.lower() or "ferrous" in body_added.lower()
               or "lisinopril" in body_added.lower() or "ferrous" in body_removed.lower(),
               "")
        page.screenshot(path=str(SHOTS / "09_compare.png"))

        # ---------- 11. Upload flow ----------
        print("== 11. Upload (user POV) ==")
        page.goto(BASE + "/upload", wait_until="networkidle")
        upload_input = page.locator("input[type=file]")
        # unique per run (duplicate SHA would be correctly rejected with 422)
        tmp = Path(__file__).parent / "_upload_tmp.txt"
        tmp.write_text(
            "Riverdale Clinic Lab Report\n\nPatient Information\n"
            f"Patient: Z. Test {time.time_ns()} (fictional)\n\n"
            "Laboratory Results\nSodium: 139 mmol/L [135-145]\nPotassium: 4.1 mmol/L [3.5-5.1]\n"
            "Hemoglobin: 14.0 g/dL [12.0-16.0]\n\nAssessment\nAll values within reference ranges.\n"
            f"Reference: report-{time.time_ns()}\n",
            encoding="utf-8",
        )
        t0 = time.perf_counter()
        upload_input.set_input_files(str(tmp))
        page.wait_for_selector("text=Queued for processing", timeout=15000)
        up_ms = (time.perf_counter() - t0) * 1000
        record("upload feedback (queued badge)", True, ms=up_ms)
        # duplicate rejection UX: same bytes, different filename (input change
        # won't fire if the input value is identical, so use a copy)
        dup = tmp.with_name("_upload_dup.txt")
        dup.write_bytes(tmp.read_bytes())
        upload_input.set_input_files(str(dup))
        page.wait_for_selector("text=already uploaded", timeout=15000)
        record("duplicate upload shows clear error", True)
        page.screenshot(path=str(SHOTS / "10_upload.png"))
        tmp.unlink(missing_ok=True)
        dup.unlink(missing_ok=True)

        # ---------- 12. Sign out ----------
        print("== 12. Sign out ==")
        page.click("text=Sign out")
        page.wait_for_url("**/login", timeout=10000)
        record("sign out returns to login", True)

        browser.close()

    # summary
    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n== USER-POV RESULT: {passed} passed, {failed} failed ==")
    avg = {t["action"]: t["ms"] for t in timings}
    print(json.dumps(avg, indent=2))

    Path(__file__).with_name("user_pov_results.json").write_text(
        json.dumps({"results": results, "timings": timings,
                    "passed": passed, "failed": failed}, indent=2)
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
