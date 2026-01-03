"""Unit tests for URL validator (SSRF protection)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.agent_server.utils.url_validator import (
    BLOCKED_HOSTNAMES,
    BLOCKED_IP_RANGES,
    SSRFValidationError,
    is_safe_url,
    validate_url_for_ssrf,
)


class TestValidateUrlForSSRF:
    """Test SSRF URL validation."""

    # ==================== Valid URLs ====================

    def test_valid_https_url(self) -> None:
        """HTTPS URLs should pass validation."""
        url = "https://api.example.com/v1/agents"
        result = validate_url_for_ssrf(url)
        assert result == url

    def test_valid_https_with_port(self) -> None:
        """HTTPS URLs with standard ports should pass."""
        assert validate_url_for_ssrf("https://api.example.com:443/path")
        assert validate_url_for_ssrf("https://api.example.com:8443/path")

    def test_valid_http_when_allowed(self) -> None:
        """HTTP URLs should pass when require_https=False."""
        url = "http://api.example.com/v1/agents"
        result = validate_url_for_ssrf(url, require_https=False)
        assert result == url

    # ==================== Blocked Hostnames ====================

    def test_blocks_localhost(self) -> None:
        """Should block localhost."""
        with pytest.raises(SSRFValidationError) as exc_info:
            validate_url_for_ssrf("https://localhost:8080/api", require_https=False)
        assert "Blocked hostname" in str(exc_info.value)
        assert exc_info.value.reason == "blocked_hostname"

    def test_blocks_localhost_variants(self) -> None:
        """Should block localhost variants."""
        localhost_urls = [
            "http://localhost/api",
            "http://localhost.localdomain/api",
            "http://local/api",
        ]
        for url in localhost_urls:
            with pytest.raises(SSRFValidationError):
                validate_url_for_ssrf(url, require_https=False)

    def test_blocks_metadata_endpoint(self) -> None:
        """Should block cloud metadata endpoints."""
        metadata_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ]
        for url in metadata_urls:
            with pytest.raises(SSRFValidationError):
                validate_url_for_ssrf(url, require_https=False)

    # ==================== Blocked IP Ranges ====================

    def test_blocks_private_ip_10_range(self) -> None:
        """Should block 10.0.0.0/8 private IPs."""
        with pytest.raises(SSRFValidationError) as exc_info:
            validate_url_for_ssrf("http://10.0.0.1/api", require_https=False)
        assert "blocked range" in str(exc_info.value).lower()

    def test_blocks_private_ip_172_range(self) -> None:
        """Should block 172.16.0.0/12 private IPs."""
        with pytest.raises(SSRFValidationError):
            validate_url_for_ssrf("http://172.16.0.1/api", require_https=False)

    def test_blocks_private_ip_192_range(self) -> None:
        """Should block 192.168.0.0/16 private IPs."""
        with pytest.raises(SSRFValidationError):
            validate_url_for_ssrf("http://192.168.1.1/api", require_https=False)

    def test_blocks_loopback(self) -> None:
        """Should block 127.0.0.0/8 loopback IPs."""
        with pytest.raises(SSRFValidationError):
            validate_url_for_ssrf("http://127.0.0.1/api", require_https=False)
        with pytest.raises(SSRFValidationError):
            validate_url_for_ssrf("http://127.0.0.2/api", require_https=False)

    def test_blocks_link_local(self) -> None:
        """Should block 169.254.0.0/16 link-local IPs."""
        with pytest.raises(SSRFValidationError):
            validate_url_for_ssrf("http://169.254.1.1/api", require_https=False)

    # ==================== Scheme Validation ====================

    def test_blocks_non_http_schemes(self) -> None:
        """Should block non-HTTP schemes."""
        invalid_urls = [
            "ftp://example.com/file",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
        ]
        for url in invalid_urls:
            with pytest.raises(SSRFValidationError) as exc_info:
                validate_url_for_ssrf(url, require_https=False)
            assert "scheme" in str(exc_info.value).lower()

    def test_requires_https_by_default(self) -> None:
        """Should require HTTPS by default."""
        with pytest.raises(SSRFValidationError) as exc_info:
            validate_url_for_ssrf("http://api.example.com/v1")
        assert "HTTPS" in str(exc_info.value)
        assert exc_info.value.reason == "https_required"

    # ==================== URL Structure ====================

    def test_blocks_empty_url(self) -> None:
        """Should block empty URLs."""
        with pytest.raises(SSRFValidationError):
            validate_url_for_ssrf("")

    def test_blocks_url_without_hostname(self) -> None:
        """Should block URLs without hostname."""
        with pytest.raises(SSRFValidationError):
            validate_url_for_ssrf("https:///path")

    def test_blocks_very_long_url(self) -> None:
        """Should block excessively long URLs."""
        long_url = "https://example.com/" + "a" * 3000
        with pytest.raises(SSRFValidationError) as exc_info:
            validate_url_for_ssrf(long_url)
        assert exc_info.value.reason == "too_long"

    # ==================== Internal Hostname Patterns ====================

    def test_blocks_internal_domain_patterns(self) -> None:
        """Should block internal domain patterns."""
        internal_urls = [
            "http://api.internal/service",
            "http://app.local/api",
            "http://host.docker.internal:8080",
            "http://service.cluster.local/api",
        ]
        for url in internal_urls:
            with pytest.raises(SSRFValidationError):
                validate_url_for_ssrf(url, require_https=False)

    # ==================== Environment Variable ====================

    def test_respects_https_env_var_false(self) -> None:
        """Should respect FEDERATION_REQUIRE_HTTPS=false."""
        with patch.dict(os.environ, {"FEDERATION_REQUIRE_HTTPS": "false"}):
            # Need to reimport to pick up env var change
            from importlib import reload

            import src.agent_server.utils.url_validator as module

            reload(module)
            try:
                # Should now allow HTTP
                result = module.validate_url_for_ssrf("http://api.example.com")
                assert result == "http://api.example.com"
            finally:
                # Restore default
                reload(module)


class TestIsSafeUrl:
    """Test is_safe_url convenience function."""

    def test_returns_true_for_valid_url(self) -> None:
        """Should return True for valid URLs."""
        assert is_safe_url("https://api.example.com") is True

    def test_returns_false_for_blocked_url(self) -> None:
        """Should return False for blocked URLs."""
        assert is_safe_url("http://localhost") is False
        assert is_safe_url("http://192.168.1.1") is False
        assert is_safe_url("http://169.254.169.254") is False


class TestSSRFValidationError:
    """Test SSRFValidationError exception."""

    def test_truncates_url_in_exception(self) -> None:
        """Should truncate long URLs in exception."""
        long_url = "https://example.com/" + "a" * 200
        error = SSRFValidationError("Test error", url=long_url, reason="test")
        assert len(error.url or "") <= 100

    def test_stores_reason(self) -> None:
        """Should store reason in exception."""
        error = SSRFValidationError("Test error", reason="blocked_ip_range")
        assert error.reason == "blocked_ip_range"
