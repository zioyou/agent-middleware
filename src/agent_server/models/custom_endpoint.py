"""Custom HTTP endpoint configuration models.

These models define the config schema for custom endpoints in agents.json.
They are used by CustomEndpointService to validate and register routes dynamically.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}


class CustomEndpointAuthConfig(BaseModel):
    """Authentication configuration for a custom endpoint."""

    mode: Literal["required", "optional", "none"] = Field(
        default="required", description="Auth enforcement mode for the endpoint."
    )
    permissions: list[str] = Field(
        default_factory=list, description="Permissions required when auth is enabled."
    )

    model_config = ConfigDict(extra="forbid")


class CustomEndpointRateLimitConfig(BaseModel):
    """Rate limit configuration (reserved for future enforcement)."""

    key: Literal["user", "org", "ip"] = Field("user", description="Rate limit key strategy.")
    limit: int = Field(..., description="Maximum requests allowed per interval.")
    interval_seconds: int = Field(..., description="Interval window in seconds.")

    model_config = ConfigDict(extra="forbid")


class CustomEndpointWebhookSignatureConfig(BaseModel):
    """Webhook signature verification configuration."""

    header: str = Field(..., description="Header name containing the signature.")
    secret_env: str = Field(..., description="Environment variable containing the secret.")
    algorithm: str = Field("hmac-sha256", description="Signature algorithm identifier.")
    tolerance_seconds: int | None = Field(
        None, description="Optional timestamp tolerance for signed payloads."
    )

    model_config = ConfigDict(extra="forbid")


class CustomEndpointWebhookConfig(BaseModel):
    """Webhook handling configuration."""

    enabled: bool = Field(False, description="Enable webhook handling for this endpoint.")
    signature: CustomEndpointWebhookSignatureConfig | None = Field(
        None, description="Signature verification settings."
    )
    ack_status: int | None = Field(
        None, description="Status code to return for webhook acknowledgements."
    )

    model_config = ConfigDict(extra="forbid")


class CustomEndpointConfig(BaseModel):
    """Custom endpoint definition from configuration."""

    id: str | None = Field(None, description="Optional stable identifier for the endpoint.")
    path: str = Field(..., description="HTTP path for the endpoint (e.g., /custom/hello).")
    methods: list[str] = Field(..., description="Allowed HTTP methods.")
    handler: str = Field(..., description="Handler import path (module:callable or file.py:callable).")
    summary: str | None = Field(None, description="OpenAPI summary.")
    description: str | None = Field(None, description="OpenAPI description.")
    tags: list[str] = Field(default_factory=list, description="OpenAPI tags.")
    response_model: str | None = Field(None, description="Response model import path.")
    request_model: str | None = Field(None, description="Request model import path.")
    status_code: int | None = Field(None, description="Default HTTP status code.")
    operation_id: str | None = Field(None, description="Stable OpenAPI operation_id.")
    auth: CustomEndpointAuthConfig = Field(
        default_factory=lambda: CustomEndpointAuthConfig(), description="Auth configuration."
    )
    rate_limit: CustomEndpointRateLimitConfig | None = Field(
        None, description="Optional rate limit settings."
    )
    webhook: CustomEndpointWebhookConfig | None = Field(
        None, description="Optional webhook handling settings."
    )

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_endpoint(self) -> Self:
        if not self.path.startswith("/"):
            raise ValueError("Custom endpoint path must start with '/'")

        if not self.methods:
            raise ValueError("Custom endpoint methods must not be empty")

        normalized_methods = [method.upper() for method in self.methods]
        invalid = [method for method in normalized_methods if method not in _ALLOWED_METHODS]
        if invalid:
            raise ValueError(f"Unsupported HTTP methods: {', '.join(invalid)}")
        self.methods = normalized_methods

        if self.webhook and self.webhook.enabled and self.webhook.signature is None:
            raise ValueError("Webhook signature config is required when webhook is enabled")

        return self
