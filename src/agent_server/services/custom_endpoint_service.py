"""Custom endpoint registration and handler dispatch service."""

import asyncio
import hashlib
import hmac
import importlib
import importlib.util
import json
import logging
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.routing import APIRouter
from pydantic import BaseModel, TypeAdapter, ValidationError

from ..core.auth_deps import get_current_user
from ..core.cache import cache_manager
from ..core.database import db_manager
from ..models.auth import User
from ..models.custom_endpoint import (
    CustomEndpointConfig,
    CustomEndpointWebhookSignatureConfig,
)
from .langgraph_service import get_langgraph_service

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CustomEndpointContext:
    """Runtime context passed to custom endpoint handlers."""

    request: Request
    user: User | None
    body: BaseModel | dict[str, Any] | bytes | None
    query: dict[str, Any]
    path_params: dict[str, Any]
    headers: dict[str, str]
    services: dict[str, Any]
    raw_body: bytes | None = None


class CustomEndpointService:
    """Service for loading, validating, and registering custom endpoints."""

    def __init__(
        self,
        config_getter: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self._config_getter = config_getter or self._default_config_getter
        self._endpoint_registry: list[CustomEndpointConfig] = []
        self._handler_cache: dict[str, Callable[..., Any]] = {}
        self._model_cache: dict[str, type[BaseModel]] = {}
        self._module_cache: dict[str, ModuleType] = {}
        self._router = APIRouter()
        self._registered_apps: set[int] = set()

    def initialize(self) -> None:
        """Load and validate custom endpoint definitions."""
        self._endpoint_registry = self._load_custom_endpoint_registry()

    def register_routes(self, app: FastAPI) -> None:
        """Register custom endpoints on the given FastAPI app."""
        app_id = id(app)
        if app_id in self._registered_apps:
            return

        if not self._endpoint_registry:
            self.initialize()

        for endpoint in self._endpoint_registry:
            self._register_endpoint(endpoint)

        if self._router.routes:
            app.include_router(self._router)

        self._registered_apps.add(app_id)

    def _default_config_getter(self) -> dict[str, Any] | None:
        return get_langgraph_service().get_config()

    def _load_custom_endpoint_registry(self) -> list[CustomEndpointConfig]:
        config = self._config_getter()
        if not config:
            return []

        raw_endpoints = config.get("custom_endpoints", [])
        if raw_endpoints in (None, []):
            return []

        try:
            adapter = TypeAdapter(list[CustomEndpointConfig])
            return adapter.validate_python(raw_endpoints)
        except ValidationError as exc:
            raise ValueError("Invalid custom_endpoints configuration") from exc

    def _register_endpoint(self, endpoint: CustomEndpointConfig) -> None:
        handler = self._load_handler(endpoint.handler)
        request_model = self._load_model(endpoint.request_model) if endpoint.request_model else None
        response_model = self._load_model(endpoint.response_model) if endpoint.response_model else None

        endpoint_handler = self._build_endpoint_handler(endpoint, handler, request_model)
        status_code = endpoint.status_code
        if endpoint.webhook and endpoint.webhook.enabled and status_code is None:
            status_code = endpoint.webhook.ack_status

        route_name = endpoint.id or endpoint.operation_id or f"custom_{len(self._router.routes)}"
        endpoint_handler.__name__ = route_name

        self._router.add_api_route(
            endpoint.path,
            endpoint_handler,
            methods=endpoint.methods,
            summary=endpoint.summary,
            description=endpoint.description,
            tags=endpoint.tags if endpoint.tags else None,  # type: ignore[arg-type]
            status_code=status_code,
            response_model=response_model,
            operation_id=endpoint.operation_id,
            name=endpoint.id,
        )

    def _build_endpoint_handler(
        self,
        endpoint: CustomEndpointConfig,
        handler: Callable[..., Any],
        request_model: type[BaseModel] | None,
    ) -> Callable[..., Any]:
        # Note: We need to use closures that capture the endpoint and handler
        # and dynamically handle the body parameter based on request_model

        async def endpoint_handler_with_body(
            request: Request,
            body: BaseModel,
            background_tasks: BackgroundTasks,
        ) -> Any:
            return await self._handle_request(
                request=request,
                body=body,
                background_tasks=background_tasks,
                endpoint=endpoint,
                handler=handler,
            )

        async def endpoint_handler_no_body(
            request: Request,
            background_tasks: BackgroundTasks,
        ) -> Any:
            return await self._handle_request(
                request=request,
                body=None,
                background_tasks=background_tasks,
                endpoint=endpoint,
                handler=handler,
            )

        if request_model:
            # Dynamically annotate the body parameter with the request model
            endpoint_handler_with_body.__annotations__["body"] = request_model
            return endpoint_handler_with_body

        return endpoint_handler_no_body

    async def _handle_request(
        self,
        request: Request,
        body: BaseModel | None,
        background_tasks: BackgroundTasks,
        endpoint: CustomEndpointConfig,
        handler: Callable[..., Any],
    ) -> Any:
        raw_body = await request.body()
        parsed_body: BaseModel | dict[str, Any] | bytes | None = body
        if body is None and raw_body:
            parsed_body = self._parse_request_body(raw_body, request)

        user = self._resolve_user(request, endpoint)

        ctx = CustomEndpointContext(
            request=request,
            user=user,
            body=parsed_body,
            query=dict(request.query_params),
            path_params=dict(request.path_params),
            headers=dict(request.headers),
            services={
                "langgraph_service": get_langgraph_service(),
                "db_manager": db_manager,
                "cache_manager": cache_manager,
            },
            raw_body=raw_body or None,
        )

        if endpoint.webhook and endpoint.webhook.enabled:
            self._verify_webhook_signature(endpoint.webhook.signature, raw_body, request)
            ack_status = endpoint.webhook.ack_status or endpoint.status_code or 200
            background_tasks.add_task(self._invoke_handler, handler, ctx)
            return Response(status_code=ack_status)

        return await self._invoke_handler(handler, ctx)

    def _parse_request_body(self, raw_body: bytes, request: Request) -> dict[str, Any] | bytes:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                result: dict[str, Any] = json.loads(raw_body)
                return result
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
        return raw_body

    def _resolve_user(self, request: Request, endpoint: CustomEndpointConfig) -> User | None:
        auth_config = endpoint.auth
        user: User | None
        if auth_config.mode == "required":
            user = get_current_user(request)
        elif auth_config.mode == "optional":
            user = self._try_get_user(request)
        else:
            user = None

        if auth_config.permissions:
            if user is None:
                raise HTTPException(status_code=401, detail="Authentication required for permissions")
            missing = [perm for perm in auth_config.permissions if perm not in user.permissions]
            if missing:
                raise HTTPException(
                    status_code=403,
                    detail=f"Missing permissions: {', '.join(missing)}",
                )

        return user

    def _try_get_user(self, request: Request) -> User | None:
        try:
            return get_current_user(request)
        except HTTPException:
            return None

    def _verify_webhook_signature(
        self,
        signature_config: CustomEndpointWebhookSignatureConfig | None,
        raw_body: bytes,
        request: Request,
    ) -> None:
        if signature_config is None:
            raise HTTPException(status_code=500, detail="Webhook signature configuration is missing")

        header_value = request.headers.get(signature_config.header)
        if not header_value:
            raise HTTPException(status_code=401, detail="Missing webhook signature header")

        secret = os.getenv(signature_config.secret_env)
        if not secret:
            raise HTTPException(
                status_code=500,
                detail=f"Webhook secret env '{signature_config.secret_env}' is not set",
            )

        timestamp, signature = self._parse_signature_header(header_value)
        if not signature:
            raise HTTPException(status_code=401, detail="Invalid webhook signature header")

        if signature_config.algorithm != "hmac-sha256":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported webhook signature algorithm '{signature_config.algorithm}'",
            )

        signed_payload = raw_body
        if timestamp:
            self._enforce_timestamp_tolerance(timestamp, signature_config.tolerance_seconds)
            signed_payload = f"{timestamp}.".encode() + raw_body

        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    def _parse_signature_header(self, header_value: str) -> tuple[str | None, str | None]:
        if "t=" in header_value or "v1=" in header_value:
            timestamp = None
            signature = None
            parts = [part.strip() for part in header_value.split(",")]
            for part in parts:
                if part.startswith("t="):
                    timestamp = part[2:]
                elif part.startswith("v1="):
                    signature = part[3:]
                elif part.startswith("sha256="):
                    signature = part[7:]
            return timestamp, signature

        if header_value.startswith("sha256="):
            return None, header_value[7:]

        return None, header_value.strip()

    def _enforce_timestamp_tolerance(self, timestamp: str, tolerance_seconds: int | None) -> None:
        if tolerance_seconds is None:
            return
        try:
            ts_value = int(timestamp)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid webhook timestamp") from exc

        now = int(time.time())
        if abs(now - ts_value) > tolerance_seconds:
            raise HTTPException(status_code=401, detail="Webhook signature timestamp outside tolerance")

    def _load_handler(self, handler_path: str) -> Callable[..., Any]:
        if handler_path in self._handler_cache:
            return self._handler_cache[handler_path]

        handler = self._load_symbol(handler_path)
        if not callable(handler):
            raise ValueError(f"Custom endpoint handler is not callable: {handler_path}")

        handler_callable: Callable[..., Any] = handler
        self._handler_cache[handler_path] = handler_callable
        return handler_callable

    def _load_model(self, model_path: str) -> type[BaseModel]:
        if model_path in self._model_cache:
            return self._model_cache[model_path]

        model = self._load_symbol(model_path)
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            raise ValueError(f"Custom endpoint model must be a Pydantic model: {model_path}")

        self._model_cache[model_path] = model
        return model

    def _load_symbol(self, import_path: str) -> Any:
        if ":" not in import_path:
            raise ValueError(f"Invalid import path: {import_path}")

        module_ref, export_name = import_path.split(":", 1)
        if module_ref.endswith(".py"):
            module = self._load_module_from_file(module_ref)
        else:
            module = importlib.import_module(module_ref)

        if not hasattr(module, export_name):
            raise ValueError(f"Export '{export_name}' not found in {module_ref}")

        return getattr(module, export_name)

    def _load_module_from_file(self, file_path: str) -> ModuleType:
        resolved_path = Path(file_path)
        if not resolved_path.exists():
            raise ValueError(f"Custom endpoint file not found: {resolved_path}")

        cache_key = str(resolved_path.resolve())
        if cache_key in self._module_cache:
            return self._module_cache[cache_key]

        module_hash = hashlib.md5(cache_key.encode("utf-8")).hexdigest()
        module_name = f"custom_endpoint_{module_hash}"
        spec = importlib.util.spec_from_file_location(module_name, cache_key)
        if spec is None or spec.loader is None:
            raise ValueError(f"Failed to load module from {resolved_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        self._module_cache[cache_key] = module
        return module

    async def _invoke_handler(self, handler: Callable[..., Any], ctx: CustomEndpointContext) -> Any:
        if asyncio.iscoroutinefunction(handler):
            return await handler(ctx)

        result = await run_in_threadpool(handler, ctx)
        if asyncio.iscoroutine(result):
            return await result
        return result


_custom_endpoint_service: CustomEndpointService | None = None


def get_custom_endpoint_service() -> CustomEndpointService:
    """Return the singleton CustomEndpointService instance."""
    global _custom_endpoint_service
    if _custom_endpoint_service is None:
        _custom_endpoint_service = CustomEndpointService()
    return _custom_endpoint_service
