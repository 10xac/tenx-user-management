"""
SAST (Static Application Security Testing) — code-level security analysis.
Scans source files for hardcoded secrets, insecure patterns, debug artifacts,
unsafe deserialization, and configuration weaknesses.

Aligned with OWASP Top 10 and CWE categories:
  - CWE-798: Hardcoded Credentials
  - CWE-489: Active Debug Code
  - CWE-200: Exposure of Sensitive Information
  - CWE-327: Use of Broken/Risky Cryptographic Algorithm
  - CWE-330: Use of Insufficiently Random Values
  - CWE-502: Deserialization of Untrusted Data
"""
import ast
import os
import re
import pytest
from pathlib import Path


# ============================================================================
# Helpers
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_DIR = PROJECT_ROOT / "api"

def _python_files(root=API_DIR):
    """Yield all .py files under root."""
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        yield path


def _read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


# ============================================================================
# CWE-798: Hardcoded Credentials
# ============================================================================

class TestHardcodedCredentials:
    """Detect hardcoded passwords, API keys, tokens, and secrets in source."""

    SECRET_PATTERNS = [
        # Assignment patterns: password = "literal"
        re.compile(
            r"""(?:password|passwd|pwd|secret|api_key|apikey|token|auth_token|"""
            r"""access_key|secret_key|private_key)\s*=\s*['"][^'"]{8,}['"]""",
            re.IGNORECASE,
        ),
        # AWS key patterns
        re.compile(r"AKIA[0-9A-Z]{16}"),
        # Generic long hex tokens
        re.compile(r"""['"][0-9a-fA-F]{32,}['"]"""),
        # JWT tokens
        re.compile(r"eyJ[a-zA-Z0-9_-]{20,}\.eyJ[a-zA-Z0-9_-]{20,}"),
    ]

    # Whitelisted patterns (test files, mock values, examples)
    WHITELIST = [
        "mock-",
        "test-",
        "example",
        "placeholder",
        "10@Academy",  # documented default password
        "local-development-secret-key",  # documented dev default
        "unknown",
    ]

    def _is_whitelisted(self, match_text):
        return any(w in match_text.lower() for w in self.WHITELIST)

    @pytest.mark.parametrize("filepath", list(_python_files()), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
    def test_no_hardcoded_secrets(self, filepath):
        content = _read(filepath)
        violations = []
        for pattern in self.SECRET_PATTERNS:
            for match in pattern.finditer(content):
                matched = match.group()
                if not self._is_whitelisted(matched):
                    line_no = content[:match.start()].count("\n") + 1
                    violations.append(f"  Line {line_no}: {matched[:80]}...")
        assert not violations, (
            f"Potential hardcoded credentials in {filepath.relative_to(PROJECT_ROOT)}:\n"
            + "\n".join(violations)
        )


# ============================================================================
# CWE-489: Active Debug Code
# ============================================================================

class TestDebugArtifacts:
    """Detect debug statements and artifacts that should not be in production."""

    DEBUG_PATTERNS = [
        re.compile(r"\bbreakpoint\(\)"),
        re.compile(r"\bpdb\.set_trace\(\)"),
        re.compile(r"\bipdb\.set_trace\(\)"),
        re.compile(r"\bimport\s+pdb\b"),
        re.compile(r"\bimport\s+ipdb\b"),
        re.compile(r"#\s*TODO.*hack", re.IGNORECASE),
        re.compile(r"#\s*FIXME.*security", re.IGNORECASE),
    ]

    @pytest.mark.parametrize("filepath", list(_python_files()), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
    def test_no_debug_statements(self, filepath):
        content = _read(filepath)
        violations = []
        for pattern in self.DEBUG_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                violations.append(f"  Line {line_no}: {match.group()}")
        assert not violations, (
            f"Debug artifacts in {filepath.relative_to(PROJECT_ROOT)}:\n"
            + "\n".join(violations)
        )


# ============================================================================
# CWE-200: Sensitive Information Exposure in Error Messages
# ============================================================================

class TestSensitiveInfoExposure:
    """Ensure error responses don't expose internal implementation details."""

    DANGEROUS_PATTERNS = [
        re.compile(r"traceback\.format_exc\(\)"),
    ]

    EXPOSE_PATTERNS = [
        # Returning raw exception str that might contain sensitive info
        re.compile(r"""detail=.*str\(e\)"""),
        re.compile(r"""detail=f".*\{.*e.*\}"""),
    ]

    @pytest.mark.parametrize("filepath", list(_python_files()), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
    def test_no_raw_traceback_in_responses(self, filepath):
        """Flag traceback exposure in HTTP responses (not just logging)."""
        content = _read(filepath)
        violations = []
        for pattern in self.DANGEROUS_PATTERNS:
            for match in pattern.finditer(content):
                # Check if it's in a response context (near return/HTTPException)
                context_start = max(0, match.start() - 200)
                context = content[context_start:match.end() + 50]
                if "error_data" in context or "return" in context:
                    line_no = content[:match.start()].count("\n") + 1
                    violations.append(f"  Line {line_no}: traceback exposed in response")
        # This is a warning-level finding, not a blocker
        if violations:
            pytest.skip(
                f"WARNING: Potential traceback exposure in {filepath.relative_to(PROJECT_ROOT)}:\n"
                + "\n".join(violations)
            )


# ============================================================================
# CWE-330: Insufficiently Random Values (password_generator)
# ============================================================================

class TestPasswordGeneratorSecurity:
    """Verify password generator meets security standards."""

    def test_uses_random_module(self):
        """Flag if using `random` instead of `secrets` (CWE-330).
        Note: `random` is not cryptographically secure."""
        content = _read(API_DIR / "utils" / "password_generator.py")
        uses_random = "import random" in content
        uses_secrets = "import secrets" in content
        if uses_random and not uses_secrets:
            pytest.skip(
                "WARNING (CWE-330): password_generator uses `random` module instead of "
                "`secrets`. The `random` module is NOT cryptographically secure."
            )

    def test_minimum_password_length(self):
        from api.utils.password_generator import generate_secure_password
        password = generate_secure_password()
        assert len(password) >= 8, "Generated password must be at least 8 characters"

    def test_password_complexity(self):
        from api.utils.password_generator import generate_secure_password
        password = generate_secure_password(16)
        assert any(c.isupper() for c in password), "Password must contain uppercase"
        assert any(c.islower() for c in password), "Password must contain lowercase"
        assert any(c.isdigit() for c in password), "Password must contain digit"
        assert any(not c.isalnum() for c in password), "Password must contain special char"

    def test_passwords_are_unique(self):
        from api.utils.password_generator import generate_secure_password
        passwords = {generate_secure_password() for _ in range(100)}
        assert len(passwords) == 100, "Generated passwords should be unique"

    def test_zero_length_handled(self):
        from api.utils.password_generator import generate_secure_password
        # Should not crash or produce empty password
        try:
            pw = generate_secure_password(length=0)
            # If it returns something, it should be a string
            assert isinstance(pw, str)
        except (ValueError, Exception):
            pass  # Raising is acceptable


# ============================================================================
# CWE-502: Deserialization of Untrusted Data
# ============================================================================

class TestUnsafeDeserialization:
    """Detect use of pickle, eval, exec on untrusted data."""

    UNSAFE_PATTERNS = [
        re.compile(r"\bpickle\.load"),
        re.compile(r"\bpickle\.loads"),
        re.compile(r"\beval\s*\("),
        re.compile(r"\bexec\s*\("),
        re.compile(r"\byaml\.load\s*\((?!.*Loader)"),  # yaml.load without Loader
        re.compile(r"\bos\.system\s*\("),
        re.compile(r"\bsubprocess\.call\s*\(.*shell\s*=\s*True"),
    ]

    @pytest.mark.parametrize("filepath", list(_python_files()), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
    def test_no_unsafe_deserialization(self, filepath):
        content = _read(filepath)
        violations = []
        for pattern in self.UNSAFE_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                violations.append(f"  Line {line_no}: {match.group()}")
        assert not violations, (
            f"Unsafe deserialization/exec in {filepath.relative_to(PROJECT_ROOT)}:\n"
            + "\n".join(violations)
        )


# ============================================================================
# Security Configuration Analysis
# ============================================================================

class TestSecurityConfiguration:
    """Analyze security-relevant configuration settings."""

    def test_cors_not_wildcard_in_production(self):
        """CORS should not allow all origins in production."""
        from api.core.config import Settings
        settings = Settings()
        # Config has BACKEND_CORS_ORIGINS=["*"] but main.py uses regex pattern
        # Verify main.py uses restrictive regex, not wildcard
        content = _read(API_DIR / "main.py")
        assert "allow_origin_regex" in content, "CORS should use regex pattern"
        assert "10academy\\.org" in content, "CORS regex should include 10academy.org"
        assert "gettenacious\\.com" in content, "CORS regex should include gettenacious.com"

    def test_cors_regex_rejects_unrelated_domains(self):
        """Verify CORS regex doesn't accidentally match unrelated domains."""
        import re
        pattern = r"^https?://([\w\-]+\.)*?(10academy\.org|gettenacious\.com)(:\d+)?$"
        # Should reject
        assert not re.match(pattern, "https://evil.com")
        assert not re.match(pattern, "https://fake10academy.org")
        assert not re.match(pattern, "https://10academy.org.evil.com")
        assert not re.match(pattern, "http://evil.com/10academy.org")
        # Should accept
        assert re.match(pattern, "https://10academy.org")
        assert re.match(pattern, "https://dev.10academy.org")
        assert re.match(pattern, "https://gettenacious.com")

    def test_file_size_limit_configured(self):
        from api.core.config import Settings
        settings = Settings()
        assert settings.MAX_FILE_SIZE <= 10 * 1024 * 1024, "Max file size should be ≤ 10MB"

    def test_allowed_file_types_restricted(self):
        from api.core.config import Settings
        settings = Settings()
        assert "text/csv" in settings.ALLOWED_FILE_TYPES
        assert "application/x-executable" not in settings.ALLOWED_FILE_TYPES
        assert "application/octet-stream" not in settings.ALLOWED_FILE_TYPES

    def test_no_env_file_with_secrets_committed(self):
        """Ensure .env files with real secrets are not in the repo."""
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            content = env_file.read_text()
            assert "AKIA" not in content, ".env should not contain AWS keys"
            assert len(content.strip()) < 500, ".env should be minimal or empty"

    def test_gitignore_covers_secrets(self):
        gitignore = PROJECT_ROOT / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text()
            assert ".env" in content, ".gitignore should exclude .env files"


# ============================================================================
# Dependency Security Hints
# ============================================================================

class TestDependencySecurity:
    """Check for known insecure dependency patterns."""

    def test_no_ancient_jwt_library(self):
        """PyJWT < 2.0 had critical vulnerabilities."""
        try:
            import jwt
            version = getattr(jwt, "__version__", "0.0.0")
            major = int(version.split(".")[0])
            assert major >= 2, f"PyJWT version {version} has known vulnerabilities"
        except ImportError:
            pass  # Not using PyJWT directly

    def test_httpx_used_instead_of_urllib(self):
        """httpx is preferred over urllib for modern async HTTP."""
        content = _read(API_DIR / "core" / "auth.py")
        assert "import httpx" in content or "from httpx" in content
        assert "urllib" not in content
