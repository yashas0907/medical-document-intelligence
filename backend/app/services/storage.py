"""Secure file storage: opaque stored filenames, owner-scoped subdirs, no public exposure."""
import hashlib
import re
import secrets
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationError

_SAFE_NAME = re.compile(r"^[\w\-.]+$")


def storage_root() -> Path:
    s = get_settings()
    root = Path(s.storage_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _doc_dir(doc_id: str) -> Path:
    if not re.match(r"^[a-f0-9]{32}$", doc_id):
        raise ValidationError("Invalid document id")
    d = storage_root() / "documents" / doc_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitize_filename(name: str) -> str:
    """Strip path traversal & dangerous chars; keep readable original."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = name.strip().strip(".")
    name = re.sub(r"[^\w\-. ()\[\]]", "_", name)
    if not name or name in {".", ".."}:
        raise ValidationError("Invalid filename")
    return name[:200]


def extension_of(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return ext


def validate_extension(ext: str) -> None:
    s = get_settings()
    if ext not in s.allowed_ext_list:
        raise ValidationError(
            f"File type '{ext or 'none'}' not allowed",
            details={"allowed": sorted(s.allowed_ext_list)},
        )


def save_original(doc_id: str, data: bytes, ext: str) -> str:
    """Store original under opaque name. Returns stored filename."""
    d = _doc_dir(doc_id)
    stored = f"original_{secrets.token_hex(8)}{ext}"
    (d / stored).write_bytes(data)
    return stored


def save_extracted_text(doc_id: str, text: str) -> str:
    d = _doc_dir(doc_id)
    p = d / "extracted.txt"
    p.write_text(text, encoding="utf-8")
    return p.name


def read_extracted_text(doc_id: str) -> str | None:
    p = _doc_dir(doc_id) / "extracted.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def original_path(doc_id: str, stored_filename: str) -> Path:
    if "/" in stored_filename or "\\" in stored_filename or ".." in stored_filename:
        raise ValidationError("Invalid stored filename")
    p = _doc_dir(doc_id) / stored_filename
    if not p.exists():
        raise NotFoundError("Original file missing from storage")
    return p


def delete_document_files(doc_id: str) -> None:
    d = storage_root() / "documents" / doc_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
