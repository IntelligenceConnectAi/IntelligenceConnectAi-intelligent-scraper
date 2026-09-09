"""
Upload/file-safety helpers, originally for People Leads (Phase 4) — covers the
expansion doc's §32 requirements: validate uploads, limit size, validate extension,
escape uploaded text, scan for formula injection. Support ticket attachments (Phase 7)
reuse `safe_filename`/`sanitize_formula_injection` but get their own separate
extension/size/content-type constants (see below) rather than sharing the People-Leads
ones, which feed straight into a CSV/XLSX ingestion pipeline.
"""

import os
import re

ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".xlsx"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15MB

UPLOAD_CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

# Support ticket attachments (Phase 7) — deliberately separate from the People-Leads
# constants above, which feed straight into pd.read_csv/read_excel. Widening those
# to admit images/PDFs would let the wrong file types reach that ingestion pipeline.
TICKET_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".csv", ".xlsx", ".txt"}
TICKET_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # 10MB

TICKET_ATTACHMENT_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "pdf": "application/pdf",
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "txt": "text/plain",
}

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def sanitize_formula_injection(value: str) -> str:
    """Neutralize spreadsheet formula execution on any value that might later be
    re-exported to CSV or rendered in an admin UI — prefix with a literal quote."""
    if value and value[0] in _FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


def safe_filename(original: str) -> str:
    base = os.path.basename(original or "upload")
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    base = re.sub(r"_{2,}", "_", base)  # "Name — State (No Website)" shouldn't become "Name___State__No_Website_"
    return base[-200:] or "upload"


_PHONE_DIGITS_RE = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    return _PHONE_DIGITS_RE.sub("", raw or "")


def is_valid_phone(raw: str) -> bool:
    digits = normalize_phone(raw)
    return 10 <= len(digits) <= 11


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(raw: str) -> bool:
    return bool(_EMAIL_RE.match((raw or "").strip()))
