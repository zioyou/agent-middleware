"""Unit tests for CustomEndpointService."""

import hashlib
import hmac

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_server.services.custom_endpoint_service import CustomEndpointService


class TestCustomEndpointService:
    """Custom endpoint service tests."""

    def test_initialize_parses_custom_endpoints(self):
        config = {
            "custom_endpoints": [
                {
                    "path": "/custom/hello",
                    "methods": ["get"],
                    "handler": "json:loads",
                    "auth": {"mode": "none"},
                }
            ]
        }
        service = CustomEndpointService(config_getter=lambda: config)
        service.initialize()

        assert len(service._endpoint_registry) == 1
        endpoint = service._endpoint_registry[0]
        assert endpoint.path == "/custom/hello"
        assert endpoint.methods == ["GET"]

    def test_load_handler_from_file(self, tmp_path):
        handler_file = tmp_path / "handler.py"
        handler_file.write_text(
            "def handle(ctx):\n    return {'ok': True}\n",
            encoding="utf-8",
        )

        service = CustomEndpointService(config_getter=lambda: {})
        handler = service._load_handler(f"{handler_file}:handle")

        assert callable(handler)

    def test_register_routes_with_request_model(self, tmp_path):
        handler_file = tmp_path / "handler.py"
        handler_file.write_text(
            "async def handle(ctx):\n    return {'identity': ctx.body.identity}\n",
            encoding="utf-8",
        )

        config = {
            "custom_endpoints": [
                {
                    "path": "/custom/echo",
                    "methods": ["POST"],
                    "handler": f"{handler_file}:handle",
                    "request_model": "agent_server.models.auth:User",
                    "response_model": "agent_server.models.auth:User",
                    "auth": {"mode": "none"},
                }
            ]
        }

        service = CustomEndpointService(config_getter=lambda: config)
        service.initialize()
        app = FastAPI()
        service.register_routes(app)

        client = TestClient(app)
        response = client.post("/custom/echo", json={"identity": "user-1"})

        assert response.status_code == 200
        assert response.json()["identity"] == "user-1"

    def test_webhook_signature_verification(self, tmp_path, monkeypatch):
        secret = "test-secret"
        monkeypatch.setenv("TEST_WEBHOOK_SECRET", secret)

        marker_file = tmp_path / "marker.txt"
        handler_file = tmp_path / "webhook.py"
        handler_file.write_text(
            "from pathlib import Path\n\n"
            f"def handle(ctx):\n    Path({repr(str(marker_file))}).write_text('ok')\n",
            encoding="utf-8",
        )

        config = {
            "custom_endpoints": [
                {
                    "path": "/webhooks/test",
                    "methods": ["POST"],
                    "handler": f"{handler_file}:handle",
                    "auth": {"mode": "none"},
                    "webhook": {
                        "enabled": True,
                        "signature": {
                            "header": "X-Signature",
                            "secret_env": "TEST_WEBHOOK_SECRET",
                            "algorithm": "hmac-sha256",
                        },
                        "ack_status": 202,
                    },
                }
            ]
        }

        service = CustomEndpointService(config_getter=lambda: config)
        service.initialize()
        app = FastAPI()
        service.register_routes(app)

        client = TestClient(app)
        payload = b'{"event":"ping"}'

        bad_response = client.post(
            "/webhooks/test",
            data=payload,
            headers={"X-Signature": "bad", "content-type": "application/json"},
        )
        assert bad_response.status_code == 401
        assert not marker_file.exists()

        signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        good_response = client.post(
            "/webhooks/test",
            data=payload,
            headers={"X-Signature": signature, "content-type": "application/json"},
        )
        assert good_response.status_code == 202
        assert marker_file.read_text() == "ok"
