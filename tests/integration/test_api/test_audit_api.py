"""Integration tests for Audit API endpoints

이 테스트는 감사 로그 API의 권한 체크와 기본 기능을 검증합니다.

테스트 범위:
1. 권한 체크 (org_id 필수, ADMIN/OWNER 역할)
2. GET /audit/logs 쿼리 기능
3. GET /audit/summary 집계 기능
4. POST /audit/export 내보내기 기능
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_server.api.audit import router as audit_router
from agent_server.core.auth_deps import get_current_user
from agent_server.core.orm import AuditLog, get_session
from agent_server.models.auth import User

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def create_audit_test_app(
    user_org_id: str | None = "test-org-123",
    user_permissions: list[str] | None = None,
) -> FastAPI:
    """감사 API 테스트용 FastAPI 앱 생성

    Args:
        user_org_id: 테스트 사용자의 org_id (None이면 org_id 없음)
        user_permissions: 테스트 사용자의 권한 목록

    Returns:
        FastAPI: 설정된 테스트 앱
    """
    app = FastAPI()
    app.include_router(audit_router)

    # 테스트 사용자 생성
    test_user = User(
        identity="test-user",
        display_name="Test User",
        org_id=user_org_id,
        permissions=user_permissions or [],
        is_authenticated=True,
    )

    # 의존성 오버라이드
    app.dependency_overrides[get_current_user] = lambda: test_user

    return app


def create_mock_session(
    scalar_return: int = 0,
    execute_rows: list | None = None,
    fetchall_rows: list | None = None,
):
    """Mock AsyncSession 생성

    Args:
        scalar_return: session.scalar()의 반환값 (count 등)
        execute_rows: session.execute().scalars().all()의 반환값
        fetchall_rows: session.execute().fetchall()의 반환값

    Returns:
        AsyncMock: 설정된 mock 세션
    """
    session = AsyncMock()

    # session.scalar() - count 쿼리용
    session.scalar.return_value = scalar_return

    # session.execute() 결과 설정
    mock_result = MagicMock()

    # .scalars().all() 패턴 (SELECT 쿼리)
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = execute_rows or []
    mock_result.scalars.return_value = mock_scalars

    # .fetchall() 패턴 (집계 쿼리)
    mock_result.fetchall.return_value = fetchall_rows or []

    session.execute.return_value = mock_result

    return session


def make_audit_log(
    id: str = "audit-123",
    timestamp: datetime | None = None,
    user_id: str = "user-123",
    org_id: str = "test-org-123",
    action: str = "CREATE",
    resource_type: str = "assistant",
    resource_id: str | None = "assistant-456",
    http_method: str = "POST",
    path: str = "/assistants",
    status_code: int = 200,
    duration_ms: int = 150,
) -> MagicMock:
    """테스트용 AuditLog 객체 생성"""
    log = MagicMock(spec=AuditLog)
    log.id = id
    log.timestamp = timestamp or datetime.now(UTC)
    log.user_id = user_id
    log.org_id = org_id
    log.action = action
    log.resource_type = resource_type
    log.resource_id = resource_id
    log.http_method = http_method
    log.path = path
    log.ip_address = "127.0.0.1"
    log.user_agent = "TestClient/1.0"
    log.request_body = {"name": "Test"}
    log.response_summary = {"status": "ok"}
    log.status_code = status_code
    log.duration_ms = duration_ms
    log.error_message = None
    log.error_class = None
    log.is_streaming = False
    log.metadata_dict = {}
    return log


# ---------------------------------------------------------------------------
# Permission Tests - org_id Required
# ---------------------------------------------------------------------------


class TestOrgIdRequired:
    """org_id 필수 검증 테스트"""

    def test_logs_without_org_id_returns_403(self):
        """org_id가 없는 사용자는 /audit/logs 접근 불가"""
        app = create_audit_test_app(user_org_id=None, user_permissions=["admin"])
        client = TestClient(app)

        response = client.get("/audit/logs")

        assert response.status_code == 403
        assert "Organization membership required" in response.json()["detail"]

    def test_summary_without_org_id_returns_403(self):
        """org_id가 없는 사용자는 /audit/summary 접근 불가"""
        app = create_audit_test_app(user_org_id=None, user_permissions=["admin"])
        client = TestClient(app)

        response = client.get("/audit/summary?group_by=action")

        assert response.status_code == 403
        assert "Organization membership required" in response.json()["detail"]

    def test_export_without_org_id_returns_403(self):
        """org_id가 없는 사용자는 /audit/export 접근 불가"""
        app = create_audit_test_app(user_org_id=None, user_permissions=["owner"])
        client = TestClient(app)

        response = client.post("/audit/export", json={"format": "csv"})

        assert response.status_code == 403
        assert "Organization membership required" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Permission Tests - Role Required
# ---------------------------------------------------------------------------


class TestRoleRequired:
    """역할 기반 접근 제어 테스트"""

    def test_logs_without_admin_returns_403(self):
        """ADMIN 역할이 없으면 /audit/logs 접근 불가"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["viewer"])
        client = TestClient(app)

        response = client.get("/audit/logs")

        assert response.status_code == 403
        assert "ADMIN role required" in response.json()["detail"]

    def test_logs_with_admin_allowed(self):
        """ADMIN 역할이 있으면 /audit/logs 접근 가능"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])
        mock_session = create_mock_session(scalar_return=0, execute_rows=[])

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/logs")

        assert response.status_code == 200

    def test_logs_with_owner_allowed(self):
        """OWNER 역할도 /audit/logs 접근 가능"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["owner"])
        mock_session = create_mock_session(scalar_return=0, execute_rows=[])

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/logs")

        assert response.status_code == 200

    def test_export_without_owner_returns_403(self):
        """OWNER 역할이 없으면 /audit/export 접근 불가"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])
        client = TestClient(app)

        response = client.post("/audit/export", json={"format": "csv"})

        assert response.status_code == 403
        assert "OWNER role required" in response.json()["detail"]

    def test_export_with_owner_allowed(self):
        """OWNER 역할이 있으면 /audit/export 접근 가능"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["owner"])
        mock_session = create_mock_session()

        # Mock streaming result
        async def mock_stream(*args, **kwargs):
            mock_result = MagicMock()

            async def async_gen():
                return
                yield  # Empty generator

            mock_result.scalars.return_value = async_gen()
            return mock_result

        mock_session.stream = mock_stream

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.post("/audit/export", json={"format": "csv"})

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"


# ---------------------------------------------------------------------------
# Query Functionality Tests
# ---------------------------------------------------------------------------


class TestListAuditLogs:
    """GET /audit/logs 기능 테스트"""

    def test_returns_paginated_results(self):
        """페이지네이션된 결과 반환"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])

        # Mock data
        logs = [make_audit_log(id=f"audit-{i}") for i in range(3)]
        mock_session = create_mock_session(scalar_return=10, execute_rows=logs)

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/logs?limit=3&offset=0")

        assert response.status_code == 200
        data = response.json()
        assert len(data["entries"]) == 3
        assert data["total"] == 10
        assert data["limit"] == 3
        assert data["offset"] == 0
        assert data["has_more"] is True

    def test_accepts_filter_parameters(self):
        """필터 파라미터 적용 확인"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])
        mock_session = create_mock_session(scalar_return=0, execute_rows=[])

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get(
            "/audit/logs"
            "?user_id=user-123"
            "&action=CREATE"
            "&resource_type=assistant"
            "&status_code=200"
        )

        assert response.status_code == 200

    def test_default_time_range_applied(self):
        """기본 시간 범위(7일) 적용 확인"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])
        mock_session = create_mock_session(scalar_return=0, execute_rows=[])

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        # start_time/end_time 없이 호출해도 동작
        response = client.get("/audit/logs")

        assert response.status_code == 200


class TestAuditSummary:
    """GET /audit/summary 기능 테스트"""

    def test_group_by_action(self):
        """액션별 집계"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])

        # Mock aggregation result
        mock_rows = [
            MagicMock(
                key="CREATE",
                count=50,
                earliest=datetime.now(UTC),
                latest=datetime.now(UTC),
            ),
            MagicMock(
                key="READ",
                count=30,
                earliest=datetime.now(UTC),
                latest=datetime.now(UTC),
            ),
        ]
        mock_session = create_mock_session(scalar_return=80, fetchall_rows=mock_rows)

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/summary?group_by=action")

        assert response.status_code == 200
        data = response.json()
        assert data["group_by"] == "action"
        assert len(data["items"]) == 2
        assert data["total_count"] == 80

    def test_group_by_resource_type(self):
        """리소스 타입별 집계"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])

        mock_rows = [
            MagicMock(
                key="assistant",
                count=40,
                earliest=datetime.now(UTC),
                latest=datetime.now(UTC),
            ),
        ]
        mock_session = create_mock_session(scalar_return=40, fetchall_rows=mock_rows)

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/summary?group_by=resource_type")

        assert response.status_code == 200
        data = response.json()
        assert data["group_by"] == "resource_type"

    def test_requires_group_by_parameter(self):
        """group_by 파라미터 필수"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])
        # 세션 의존성 오버라이드 (검증 에러가 먼저 발생하지만 안전을 위해)
        mock_session = create_mock_session()
        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/summary")

        assert response.status_code == 422  # Validation error


class TestAuditExport:
    """POST /audit/export 기능 테스트"""

    def test_csv_export_format(self):
        """CSV 형식 내보내기"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["owner"])
        mock_session = create_mock_session()

        async def mock_stream(*args, **kwargs):
            mock_result = MagicMock()

            async def async_gen():
                return
                yield

            mock_result.scalars.return_value = async_gen()
            return mock_result

        mock_session.stream = mock_stream

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.post("/audit/export", json={"format": "csv"})

        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
        assert ".csv" in response.headers["content-disposition"]

    def test_json_export_format(self):
        """JSON 형식 내보내기"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["owner"])
        mock_session = create_mock_session()

        async def mock_stream(*args, **kwargs):
            mock_result = MagicMock()

            async def async_gen():
                return
                yield

            mock_result.scalars.return_value = async_gen()
            return mock_result

        mock_session.stream = mock_stream

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.post("/audit/export", json={"format": "json"})

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
        assert ".json" in response.headers["content-disposition"]

    def test_export_with_filters(self):
        """필터 적용된 내보내기"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["owner"])
        mock_session = create_mock_session()

        async def mock_stream(*args, **kwargs):
            mock_result = MagicMock()

            async def async_gen():
                return
                yield

            mock_result.scalars.return_value = async_gen()
            return mock_result

        mock_session.stream = mock_stream

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.post(
            "/audit/export",
            json={
                "format": "csv",
                "filters": {"org_id": "test-org", "action": "CREATE"},
            },
        )

        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Response Format Tests
# ---------------------------------------------------------------------------


class TestResponseFormat:
    """응답 형식 테스트"""

    def test_audit_entry_fields(self):
        """AuditEntry 응답 필드 확인"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])

        log = make_audit_log()
        mock_session = create_mock_session(scalar_return=1, execute_rows=[log])

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/logs")

        assert response.status_code == 200
        data = response.json()
        entry = data["entries"][0]

        # 필수 필드 확인
        assert "id" in entry
        assert "timestamp" in entry
        assert "user_id" in entry
        assert "org_id" in entry
        assert "action" in entry
        assert "resource_type" in entry
        assert "http_method" in entry
        assert "path" in entry
        assert "status_code" in entry
        assert "duration_ms" in entry
        assert "is_streaming" in entry

    def test_summary_response_fields(self):
        """AuditSummaryResponse 응답 필드 확인"""
        app = create_audit_test_app(user_org_id="test-org", user_permissions=["admin"])

        mock_rows = [
            MagicMock(
                key="CREATE",
                count=10,
                earliest=datetime.now(UTC),
                latest=datetime.now(UTC),
            ),
        ]
        mock_session = create_mock_session(scalar_return=10, fetchall_rows=mock_rows)

        app.dependency_overrides[get_session] = lambda: mock_session
        client = TestClient(app)

        response = client.get("/audit/summary?group_by=action")

        assert response.status_code == 200
        data = response.json()

        assert "group_by" in data
        assert "items" in data
        assert "total_count" in data
        assert "start_time" in data
        assert "end_time" in data

        # items 필드 확인
        item = data["items"][0]
        assert "key" in item
        assert "count" in item
