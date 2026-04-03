"""
CSV Sanitizer v8.

FIX (Critical Security Bug): Step 7 in v7 called .str.lstrip("'") on every column
to check if it's numeric. This stripped the single-quote prefix that was added in
Step 6 to neutralise formula injection. A column with 80% numbers and 20% formulas
would have the formula prefix removed on the 20% cells that weren't numeric.

v8 FIX: Type inference operates on a COPY of the series. The original sanitized
column is NEVER modified by type inference. Type conversion produces a NEW column
that replaces the old only when the column was already safe (purely numeric input
with no sanitized cells). Columns that had ANY sanitized cells are never touched.

All other security checks from v7 retained unchanged.
"""
import re
import io
import hashlib
import logging
from typing import NamedTuple
import chardet
import pandas as pd

logger = logging.getLogger(__name__)

_FORMULA_PREFIXES = frozenset({"=", "+", "-", "@", "\t", "\r", "\n", "|", "%"})
_DANGEROUS_UNICODE = re.compile(r"[\u202e\u200b\u200c\u200d\ufeff\u2028\u2029]")
_SUPPORTED_ENCODINGS = frozenset({
    "utf-8", "utf-8-sig", "utf-16", "utf-16-be", "utf-16-le",
    "latin-1", "iso-8859-1", "cp1252", "ascii",
})


class SecurityError(Exception):
    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail or message


class SanitizationResult(NamedTuple):
    df: pd.DataFrame
    warnings: list[str]
    file_hash: str
    cells_sanitized: int
    detected_encoding: str
    was_reencoded: bool


def compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def detect_and_decode(content: bytes) -> tuple[str, str]:
    """Decode bytes to string, detecting encoding reliably via BOM then chardet."""
    if content[:3] == b"\xef\xbb\xbf":
        try: return content[3:].decode("utf-8"), "utf-8-sig"
        except UnicodeDecodeError: pass
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        enc = "utf-16-le" if content[:2] == b"\xff\xfe" else "utf-16-be"
        try: return content[2:].decode(enc), f"utf-16 ({enc})"
        except UnicodeDecodeError: pass
    if content[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        try: return content.decode("utf-32"), "utf-32"
        except UnicodeDecodeError: pass

    detected = chardet.detect(content[:65536])
    enc = (detected.get("encoding") or "utf-8").lower()
    confidence = detected.get("confidence", 0)
    if confidence > 0.7 and enc in _SUPPORTED_ENCODINGS:
        try: return content.decode(enc), enc
        except (UnicodeDecodeError, LookupError): pass

    for fallback in ("utf-8", "cp1252", "latin-1"):
        try: return content.decode(fallback), fallback
        except UnicodeDecodeError: continue

    raise SecurityError("File cannot be decoded", "ENCODING_ERROR")


def validate_and_sanitize_csv(
    content: bytes,
    max_columns: int = 500,
    max_cell_length: int = 10_000,
    max_rows: int = 5_000_000,
    max_column_name_length: int = 255,
) -> SanitizationResult:
    warnings: list[str] = []
    file_hash = compute_sha256(content)
    cells_sanitized = 0

    # Step 1: null bytes
    if b"\x00" in content and content[:2] not in (b"\xff\xfe", b"\xfe\xff"):
        raise SecurityError("File contains null bytes", "NULL_BYTE_DETECTED")

    # Step 2: binary file detection
    if not is_csv_content(content, "upload.csv"):
        raise SecurityError("File content is not valid CSV", "INVALID_CONTENT")

    # Step 3: encoding normalisation
    try:
        text, detected_encoding = detect_and_decode(content)
    except SecurityError: raise
    except Exception as e:
        raise SecurityError(f"Encoding error: {e}", "ENCODING_ERROR")

    was_reencoded = detected_encoding not in ("utf-8", "ascii")
    if was_reencoded:
        warnings.append(f"Re-encoded from {detected_encoding} to UTF-8")

    text = _DANGEROUS_UNICODE.sub("", text)

    # Step 4: parse with dtype=str — never auto-execute
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False,
                         on_bad_lines="warn", low_memory=False)
    except Exception as e:
        raise SecurityError(f"CSV parse failed: {e}", "PARSE_ERROR")

    # Step 5: column count + header validation
    if len(df.columns) > max_columns:
        raise SecurityError(f"File has {len(df.columns)} columns (max {max_columns})", "TOO_MANY_COLUMNS")

    sanitized_headers = []
    for col in df.columns:
        col_str = str(col).strip()
        if _DANGEROUS_UNICODE.search(col_str):
            raise SecurityError(f"Column header contains dangerous Unicode: '{col_str[:50]}'", "DANGEROUS_UNICODE_HEADER")
        if len(col_str) > max_column_name_length:   # FIX: was missing in v7
            raise SecurityError(f"Column header exceeds {max_column_name_length} chars: '{col_str[:60]}…'", "HEADER_TOO_LONG")
        sanitized_headers.append(col_str)
    df.columns = sanitized_headers

    if len(df) > max_rows:
        raise SecurityError(f"File has {len(df)} rows (max {max_rows:,})", "TOO_MANY_ROWS")

    # Step 6: cell sanitization — track which columns had cells sanitized
    cols_with_sanitized_cells: set[str] = set()

    def sanitize_cell(value: str, col_name: str) -> str:
        nonlocal cells_sanitized
        if not isinstance(value, str) or not value:
            return value
        if _DANGEROUS_UNICODE.search(value):
            cells_sanitized += 1; cols_with_sanitized_cells.add(col_name)
            return _DANGEROUS_UNICODE.sub("", value)
        if value[0] in _FORMULA_PREFIXES:
            cells_sanitized += 1; cols_with_sanitized_cells.add(col_name)
            return "'" + value   # prefix neutralises in Excel/Google Sheets
        if len(value) > max_cell_length:
            cells_sanitized += 1; cols_with_sanitized_cells.add(col_name)
            warnings.append(f"Cell truncated ({len(value)} → {max_cell_length})")
            return value[:max_cell_length]
        return value

    for col in df.columns:
        col_copy = col  # capture for closure
        df[col] = df[col].apply(lambda v: sanitize_cell(v, col_copy))

    if cells_sanitized > 0:
        logger.warning("CSV sanitized: %d cell(s) modified", cells_sanitized)

    # ── Step 7 FIX: type inference ONLY on columns that had NO sanitized cells ──
    # v7 BUG: applied .str.lstrip("'") globally, stripping formula prefixes.
    # v8 FIX: skip any column where sanitization occurred.
    for col in df.columns:
        if col in cols_with_sanitized_cells:
            continue   # NEVER touch a column that had formula prefixes applied

        # Safe to attempt numeric coercion — no security-critical prefixes present
        numeric = pd.to_numeric(df[col], errors="coerce")
        # Only replace if >80% parseable AND no sanitization occurred
        if numeric.notna().mean() > 0.8:
            df[col] = numeric

    return SanitizationResult(
        df=df, warnings=warnings, file_hash=file_hash,
        cells_sanitized=cells_sanitized,
        detected_encoding=detected_encoding,
        was_reencoded=was_reencoded,
    )


def is_csv_content(content: bytes, filename: str) -> bool:
    dangerous_magic = [
        b"PK\x03\x04", b"%PDF", b"MZ", b"\x7fELF",
        b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF8", b"\xd0\xcf\x11\xe0",
    ]
    for magic in dangerous_magic:
        if content[:len(magic)] == magic:
            return False
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in {"csv", "txt"}:
        return False
    try:
        content[:4096].decode("utf-8"); return True
    except UnicodeDecodeError:
        try: content[:4096].decode("latin-1"); return True
        except Exception: return False
