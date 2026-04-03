"""
Unit tests for CSV sanitizer — covers every injection vector.
These tests are the proof that security claims are real.
"""
import pytest
from app.core.security.csv_sanitizer import (
    validate_and_sanitize_csv, is_csv_content, compute_sha256,
    SecurityError, SanitizationResult,
)


def make_csv(*rows: str) -> bytes:
    return "\n".join(rows).encode()


class TestFormulaInjection:
    def test_equals_prefix_neutralised(self):
        content = make_csv("name,value", "Alice,=SUM(A1:A10)", "Bob,normal")
        result = validate_and_sanitize_csv(content)
        dangerous_cell = result.df.loc[result.df["name"] == "Alice", "value"].iloc[0]
        assert not str(dangerous_cell).startswith("="), "Formula prefix not neutralised"
        assert result.cells_sanitized >= 1

    def test_plus_prefix_neutralised(self):
        content = make_csv("cmd", "+cmd|' /C calc'!A0")
        result = validate_and_sanitize_csv(content)
        assert not result.df["cmd"].iloc[0].startswith("+")

    def test_minus_prefix_neutralised(self):
        content = make_csv("x", "-2+3+cmd|' /C calc'!A0")
        result = validate_and_sanitize_csv(content)
        assert not result.df["x"].iloc[0].startswith("-")

    def test_at_prefix_neutralised(self):
        content = make_csv("col", "@SUM(1+1)*cmd|' /C calc'!A0")
        result = validate_and_sanitize_csv(content)
        assert not result.df["col"].iloc[0].startswith("@")

    def test_tab_prefix_neutralised(self):
        content = "col\n\t=dangerous_formula".encode()
        result = validate_and_sanitize_csv(content)
        assert result.cells_sanitized >= 1

    def test_normal_negative_number_allowed(self):
        """Negative numbers starting with - should be safely kept as numeric."""
        content = make_csv("value", "-42.5", "100")
        result = validate_and_sanitize_csv(content)
        # Should be parsed as numeric, not string prefix
        assert result.df["value"].dtype in ["float64", "int64"] or float(result.df["value"].iloc[0]) == -42.5

    def test_hyperlink_injection(self):
        """=HYPERLINK("http://evil.com","Click me") should be neutralised."""
        content = make_csv("link", '=HYPERLINK("http://evil.com","Click here")')
        result = validate_and_sanitize_csv(content)
        assert not result.df["link"].iloc[0].startswith("=")

    def test_multiple_injections_in_file(self):
        content = make_csv("a,b,c", "=SUM(A1),+malicious,-cmd", "ok,ok,ok")
        result = validate_and_sanitize_csv(content)
        assert result.cells_sanitized >= 3


class TestNullBytes:
    def test_null_byte_raises_security_error(self):
        content = b"col\nvalue\x00evil"
        with pytest.raises(SecurityError) as exc_info:
            validate_and_sanitize_csv(content)
        assert "null" in exc_info.value.detail.lower()

    def test_null_byte_in_header_raises(self):
        content = b"col\x00name\nvalue"
        with pytest.raises(SecurityError):
            validate_and_sanitize_csv(content)


class TestDangerousUnicode:
    def test_rtlo_in_cell_removed(self):
        """Right-to-Left Override (U+202E) used to disguise filenames/content."""
        content = f"col\n\u202Evil".encode()
        result = validate_and_sanitize_csv(content)
        assert "\u202E" not in str(result.df["col"].iloc[0])

    def test_zero_width_space_removed(self):
        content = f"col\nval\u200bue".encode()
        result = validate_and_sanitize_csv(content)
        assert "\u200b" not in str(result.df["col"].iloc[0])

    def test_bom_in_content_handled(self):
        """BOM (U+FEFF) is dangerous Unicode but common in Windows CSVs."""
        content = f"col\n\ufeffvalue".encode()
        result = validate_and_sanitize_csv(content)
        # Should not raise, but should handle gracefully


class TestStructuralLimits:
    def test_too_many_columns_rejected(self):
        headers = ",".join(f"col{i}" for i in range(10))
        row = ",".join("val" for _ in range(10))
        content = f"{headers}\n{row}".encode()
        with pytest.raises(SecurityError) as exc_info:
            validate_and_sanitize_csv(content, max_columns=5)
        assert "TOO_MANY_COLUMNS" in exc_info.value.detail

    def test_cell_too_long_truncated(self):
        content = make_csv("col", "x" * 20_000)
        result = validate_and_sanitize_csv(content, max_cell_length=1000)
        assert len(str(result.df["col"].iloc[0])) <= 1001  # +1 for formula prefix
        assert result.cells_sanitized >= 1


class TestFileTypeValidation:
    def test_valid_csv_accepted(self):
        content = b"a,b\n1,2\n3,4"
        assert is_csv_content(content, "data.csv") is True

    def test_zip_magic_bytes_rejected(self):
        content = b"PK\x03\x04" + b"fake zip content"
        assert is_csv_content(content, "data.csv") is False

    def test_pdf_rejected(self):
        content = b"%PDF-1.4 fake pdf"
        assert is_csv_content(content, "data.csv") is False

    def test_exe_rejected(self):
        content = b"MZ\x90\x00 fake exe"
        assert is_csv_content(content, "data.csv") is False

    def test_wrong_extension_rejected(self):
        content = b"a,b\n1,2"
        assert is_csv_content(content, "data.exe") is False

    def test_xlsx_extension_rejected(self):
        content = b"a,b\n1,2"
        assert is_csv_content(content, "data.xlsx") is False


class TestHashAndDeterminism:
    def test_same_content_same_hash(self):
        content = b"a,b\n1,2\n3,4"
        h1 = compute_sha256(content)
        h2 = compute_sha256(content)
        assert h1 == h2

    def test_different_content_different_hash(self):
        assert compute_sha256(b"abc") != compute_sha256(b"def")

    def test_hash_in_result(self):
        content = make_csv("col", "value")
        result = validate_and_sanitize_csv(content)
        assert len(result.file_hash) == 64   # SHA-256 hex
        assert result.file_hash == compute_sha256(content)


class TestValidInputPassthrough:
    def test_clean_csv_no_modifications(self):
        content = make_csv("name,age,score", "Alice,30,95.5", "Bob,25,87.3")
        result = validate_and_sanitize_csv(content)
        assert result.cells_sanitized == 0
        assert len(result.warnings) == 0
        assert len(result.df) == 2
        assert list(result.df.columns) == ["name", "age", "score"]

    def test_empty_cells_allowed(self):
        content = make_csv("a,b", "1,", ",2", ",")
        result = validate_and_sanitize_csv(content)
        assert len(result.df) == 3

    def test_quoted_strings_allowed(self):
        content = b'name,note\n"Alice","She said, ""hello"""\n'
        result = validate_and_sanitize_csv(content)
        assert len(result.df) == 1
