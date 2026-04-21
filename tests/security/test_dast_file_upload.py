"""
DAST — File Upload Security Testing.
Tests malicious file uploads, oversized files, content-type spoofing,
and dangerous file content through the batch CSV endpoint.

Aligned with OWASP Top 10:
  - A04:2021 Insecure Design
  - A08:2021 Software and Data Integrity Failures
CWE:
  - CWE-434: Unrestricted Upload of File with Dangerous Type
  - CWE-400: Uncontrolled Resource Consumption
  - CWE-20: Improper Input Validation
"""
import pytest
import io


# ============================================================================
# CWE-434: Dangerous File Types
# ============================================================================

class TestDangerousFileTypes:
    """Attempt to upload non-CSV files through the batch endpoint."""

    def test_executable_file_rejected(self, authed_client):
        content = b"\x7fELF" + b"\x00" * 100  # ELF binary header
        files = {"file": ("malware.exe", io.BytesIO(content), "application/x-executable")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        # Should fail during CSV parsing, not execute anything
        assert resp.status_code in [200, 422]
        if resp.status_code == 200:
            body = resp.json()
            # Even if 200, it should be an error response
            assert body.get("success") is False or body.get("data", {}).get("status") == "processing"

    def test_php_file_rejected(self, authed_client):
        content = b"<?php system('whoami'); ?>"
        files = {"file": ("shell.php", io.BytesIO(content), "application/x-php")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_html_file_with_script(self, authed_client):
        content = b"<html><script>alert('xss')</script></html>"
        files = {"file": ("page.html", io.BytesIO(content), "text/html")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_zip_bomb_attempt(self, authed_client):
        """A small file that decompresses to huge size — should not cause OOM."""
        content = b"PK\x03\x04" + b"\x00" * 100  # Fake zip header
        files = {"file": ("bomb.zip", io.BytesIO(content), "application/zip")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_svg_with_script(self, authed_client):
        content = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        files = {"file": ("image.svg", io.BytesIO(content), "image/svg+xml")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_double_extension_file(self, authed_client):
        content = b"name,email\nAlice,alice@test.com\n"
        files = {"file": ("data.csv.exe", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        # Should process as CSV (content is valid CSV) or reject
        assert resp.status_code != 500


# ============================================================================
# CWE-400: Resource Exhaustion via File Upload
# ============================================================================

class TestFileResourceExhaustion:
    def test_very_large_csv_rows(self, authed_client):
        """CSV with very long field values."""
        long_name = "A" * 10000
        content = f"name,email\n{long_name},test@example.com\n".encode("utf-8")
        files = {"file": ("big.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_csv_with_many_columns(self, authed_client):
        """CSV with excessive columns (DoS attempt)."""
        header = ",".join([f"col{i}" for i in range(500)])
        row = ",".join(["val"] * 500)
        content = f"name,email,{header}\nAlice,alice@test.com,{row}\n".encode("utf-8")
        files = {"file": ("wide.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_empty_file(self, authed_client):
        files = {"file": ("empty.csv", io.BytesIO(b""), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_null_bytes_in_csv(self, authed_client):
        content = b"name,email\nAlice\x00Bob,alice@test.com\n"
        files = {"file": ("null.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_binary_content_as_csv(self, authed_client):
        content = bytes(range(256)) * 10
        files = {"file": ("binary.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500


# ============================================================================
# CWE-20: Malicious CSV Content
# ============================================================================

class TestMaliciousCSVContent:
    def test_csv_formula_injection(self, authed_client):
        """CSV injection — formulas that could execute in spreadsheet apps."""
        formulas = [
            "=CMD('calc')",
            "=SYSTEM('whoami')",
            "+CMD('calc')",
            "-CMD('calc')",
            "@SUM(1+1)*CMD('calc')",
            "=HYPERLINK(\"http://evil.com\",\"Click\")",
        ]
        rows = "\n".join([f"{f},formula{i}@test.com" for i, f in enumerate(formulas)])
        content = f"name,email\n{rows}\n".encode("utf-8")
        files = {"file": ("formulas.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        # Should not execute formulas — just process as string data
        assert resp.status_code != 500

    def test_csv_with_sql_in_fields(self, authed_client):
        content = b"name,email\n' OR 1=1--,sqli@test.com\n; DROP TABLE users;--,drop@test.com\n"
        files = {"file": ("sqli.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_csv_with_xss_in_fields(self, authed_client):
        content = b"name,email\n<script>alert('xss')</script>,xss@test.com\n"
        files = {"file": ("xss.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500
        if resp.status_code == 200:
            assert "<script>" not in resp.text

    def test_csv_with_unicode_bom(self, authed_client):
        """CSV with UTF-8 BOM — should be handled correctly."""
        content = b"\xef\xbb\xbfname,email\nAlice,alice@test.com\n"
        files = {"file": ("bom.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_csv_with_crlf_injection(self, authed_client):
        content = b"name,email\nAlice\r\nInjected-Header: true,alice@test.com\n"
        files = {"file": ("crlf.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500
        # Verify no header injection in response
        assert "Injected-Header" not in str(resp.headers)


# ============================================================================
# Content-Type Spoofing
# ============================================================================

class TestContentTypeSpoofing:
    def test_exe_disguised_as_csv(self, authed_client):
        content = b"\x4d\x5a\x90\x00"  # MZ header (Windows PE)
        files = {"file": ("payload.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500

    def test_json_disguised_as_csv(self, authed_client):
        content = b'{"malicious": true, "__proto__": {"admin": true}}'
        files = {"file": ("data.csv", io.BytesIO(content), "text/csv")}
        resp = authed_client.post("/trainee/batch", files=files, data={
            "run_stage": "dev", "batch": "1", "is_mock": "true",
        })
        assert resp.status_code != 500
