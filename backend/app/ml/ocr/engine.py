"""Pluggable OCR layer.

Primary: Tesseract via pytesseract (auto-detected on PATH or explicit cmd).
Fallback: explicit UnavailableOCR so the pipeline degrades gracefully â€” scanned
pages are marked method='ocr-failed' and excluded from answers rather than
producing garbage that could be cited.

No OCR engine is ever *required* to run the app; text PDFs/DOCX/TXT work fully.
"""
import shutil
import subprocess
from dataclasses import dataclass

from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass
class OCRPageResult:
    text: str
    confidence: float  # 0..100 average confidence
    engine: str


class BaseOCR:
    name = "base"

    def available(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def image_to_text(self, image_bytes: bytes, mime: str) -> OCRPageResult:  # pragma: no cover
        raise NotImplementedError


class UnavailableOCR(BaseOCR):
    """Null object: signals that no OCR engine is installed."""

    name = "unavailable"

    def available(self) -> bool:
        return False

    def image_to_text(self, image_bytes: bytes, mime: str) -> OCRPageResult:
        raise ServiceUnavailableError(
            "No OCR engine installed on this host",
            details={"hint": "Install Tesseract (see README OCR section) to process scanned pages"},
        )


class TesseractOCR(BaseOCR):
    name = "tesseract"

    def __init__(self, cmd: str | None = None):
        self._cmd = cmd

    def _tesseract_path(self) -> str | None:
        if self._cmd:
            return self._cmd
        found = shutil.which("tesseract")
        if found:
            return found
        # Common Windows install locations
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for c in candidates:
            if shutil.which(c):
                return c
        return None

    def available(self) -> bool:
        path = self._tesseract_path()
        if not path:
            return False
        try:
            out = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=10
            )
            return out.returncode == 0 and "tesseract" in (out.stdout or "").lower()
        except (subprocess.SubprocessError, OSError):
            return False

    def image_to_text(self, image_bytes: bytes, mime: str) -> OCRPageResult:
        import io

        import pytesseract
        from PIL import Image

        path = self._tesseract_path()
        if not path:
            raise ServiceUnavailableError("Tesseract not found")
        pytesseract.pytesseract.tesseract_cmd = path
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        texts = [t for t, c in zip(data["text"], data["conf"], strict=False) if str(t).strip() and c > 0]
        confs = [c for t, c in zip(data["text"], data["conf"], strict=False) if str(t).strip() and c > 0]
        text = " ".join(str(t) for t in texts)
        conf = sum(confs) / len(confs) if confs else 0.0
        return OCRPageResult(text=text.strip(), confidence=round(conf, 2), engine=self.name)


def get_ocr_provider(ocr_setting: str = "auto", tesseract_cmd: str | None = None) -> BaseOCR:
    """Resolve OCR provider. 'auto' tries tesseract, falls back to UnavailableOCR."""
    if ocr_setting == "none":
        return UnavailableOCR()
    tess = TesseractOCR(tesseract_cmd)
    if tess.available():
        return tess
    if ocr_setting == "tesseract":
        raise ServiceUnavailableError(
            "OCR_PROVIDER=tesseract configured but Tesseract is not installed"
        )
    log.info("OCR unavailable â€” scanned pages will be skipped and reported")
    return UnavailableOCR()

