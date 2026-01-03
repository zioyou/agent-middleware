"""Audit Logging API Router

감사 로그 조회 및 내보내기 API 엔드포인트를 제공합니다.
멀티테넌트 격리를 위해 org_id 필터링이 모든 쿼리에서 필수입니다.

엔드포인트:
    GET  /audit/logs     - 감사 로그 조회 (ADMIN 역할 필수)
    GET  /audit/summary  - 집계 통계 조회 (ADMIN 역할 필수)
    POST /audit/export   - CSV/JSON 내보내기 (OWNER 역할 필수)

보안 설계:
    - 모든 엔드포인트는 인증 필수
    - org_id 필터링 필수 (멀티테넌트 격리)
    - ADMIN 역할: 조회 가능
    - OWNER 역할: 내보내기 가능 (민감 데이터 접근 권한)

아키텍처:
    이 API는 파티션된 audit_logs 테이블을 직접 쿼리합니다.
    성능을 위해 모든 쿼리에 timestamp 범위 필터가 적용됩니다.
"""

import csv
import io
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth_deps import get_current_user
from ..core.orm import AuditLog, get_session
from ..models.audit import (
    AuditAction,
    AuditEntry,
    AuditExportFormat,
    AuditExportRequest,
    AuditGroupBy,
    AuditLogListResponse,
    AuditResourceType,
    AuditSummaryItem,
    AuditSummaryResponse,
)
from ..models.auth import User

router = APIRouter(prefix="/audit", tags=["Audit"])


# ---------------------------------------------------------------------------
# 의존성 함수 (Dependencies)
# ---------------------------------------------------------------------------


def require_org_id(user: User = Depends(get_current_user)) -> str:
    """org_id 필수 추출 (멀티테넌트 격리)

    감사 로그는 조직별로 격리되어야 합니다.
    org_id가 없는 사용자는 감사 로그에 접근할 수 없습니다.

    Args:
        user: 인증된 사용자 객체

    Returns:
        str: 사용자의 org_id

    Raises:
        HTTPException(403): org_id가 없는 경우
    """
    if not user.org_id:
        raise HTTPException(
            status_code=403,
            detail="Organization membership required to access audit logs",
        )
    return user.org_id


def require_admin(user: User = Depends(get_current_user)) -> User:
    """ADMIN 역할 필수

    감사 로그 조회는 ADMIN 또는 OWNER 역할이 필요합니다.

    Args:
        user: 인증된 사용자 객체

    Returns:
        User: 권한이 확인된 사용자 객체

    Raises:
        HTTPException(403): ADMIN 역할이 없는 경우
    """
    if "admin" not in user.permissions and "owner" not in user.permissions:
        raise HTTPException(
            status_code=403,
            detail="ADMIN role required to access audit logs",
        )
    return user


def require_owner(user: User = Depends(get_current_user)) -> User:
    """OWNER 역할 필수 (내보내기용)

    감사 로그 내보내기는 민감 데이터 접근이므로 OWNER 역할이 필요합니다.

    Args:
        user: 인증된 사용자 객체

    Returns:
        User: 권한이 확인된 사용자 객체

    Raises:
        HTTPException(403): OWNER 역할이 없는 경우
    """
    if "owner" not in user.permissions:
        raise HTTPException(
            status_code=403,
            detail="OWNER role required for audit log export",
        )
    return user


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------


def _to_audit_entry(row: AuditLog) -> AuditEntry:
    """ORM 모델을 Pydantic 모델로 변환

    Args:
        row: AuditLog ORM 객체

    Returns:
        AuditEntry: Pydantic 응답 모델
    """
    return AuditEntry(
        id=row.id,
        timestamp=row.timestamp,
        user_id=row.user_id,
        org_id=row.org_id,
        action=AuditAction(row.action),
        resource_type=AuditResourceType(row.resource_type),
        resource_id=row.resource_id,
        http_method=row.http_method,
        path=row.path,
        ip_address=row.ip_address,
        user_agent=row.user_agent,
        request_body=row.request_body,
        response_summary=row.response_summary,
        status_code=row.status_code,
        duration_ms=row.duration_ms,
        error_message=row.error_message,
        error_class=row.error_class,
        is_streaming=row.is_streaming,
        metadata=row.metadata_dict or {},
    )


def _get_group_column(group_by: AuditGroupBy):
    """group_by 값에 따른 SQLAlchemy 컬럼 반환

    Args:
        group_by: 집계 기준

    Returns:
        SQLAlchemy column 또는 function
    """
    if group_by == AuditGroupBy.ACTION:
        return AuditLog.action
    elif group_by == AuditGroupBy.RESOURCE_TYPE:
        return AuditLog.resource_type
    elif group_by == AuditGroupBy.USER_ID:
        return AuditLog.user_id
    elif group_by == AuditGroupBy.DAY:
        # PostgreSQL date_trunc 함수 사용
        return func.date_trunc("day", AuditLog.timestamp)
    else:
        raise HTTPException(400, f"Unknown group_by: {group_by}")


# ---------------------------------------------------------------------------
# GET /audit/logs - 감사 로그 목록 조회
# ---------------------------------------------------------------------------


@router.get("/logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    # 필수 의존성
    org_id: str = Depends(require_org_id),
    _user: User = Depends(require_admin),  # 권한 체크용 (실제 사용 안 함)
    session: AsyncSession = Depends(get_session),
    # 필터 파라미터
    user_id: str | None = Query(None, description="사용자 ID 필터"),
    action: AuditAction | None = Query(None, description="액션 필터"),
    resource_type: AuditResourceType | None = Query(
        None, description="리소스 타입 필터"
    ),
    resource_id: str | None = Query(None, description="리소스 ID 필터"),
    start_time: datetime | None = Query(None, description="시작 시간 (기본: 7일 전)"),
    end_time: datetime | None = Query(None, description="종료 시간 (기본: 현재)"),
    status_code: int | None = Query(None, description="HTTP 상태 코드 정확히 일치"),
    status_code_gte: int | None = Query(None, description="HTTP 상태 코드 하한 (>=)"),
    status_code_lte: int | None = Query(None, description="HTTP 상태 코드 상한 (<=)"),
    is_streaming: bool | None = Query(None, description="스트리밍 응답 여부"),
    # 페이지네이션
    limit: int = Query(100, ge=1, le=1000, description="페이지 크기 (최대 1000)"),
    offset: int = Query(0, ge=0, description="시작 위치"),
) -> AuditLogListResponse:
    """감사 로그 목록 조회

    조직 내의 감사 로그를 시간순으로 조회합니다.
    멀티테넌트 격리를 위해 org_id 필터가 자동 적용됩니다.

    파티션 테이블 성능을 위해 timestamp 범위 필터가 필수입니다.
    start_time/end_time을 지정하지 않으면 기본 7일 범위가 적용됩니다.

    Args:
        org_id: 조직 ID (인증된 사용자에서 자동 추출)
        user_id: 특정 사용자 필터
        action: 특정 액션 필터 (CREATE, READ, UPDATE, DELETE 등)
        resource_type: 특정 리소스 타입 필터 (assistant, thread, run 등)
        resource_id: 특정 리소스 ID 필터
        start_time: 시작 시간 (기본: 7일 전)
        end_time: 종료 시간 (기본: 현재)
        status_code: HTTP 상태 코드 정확히 일치
        status_code_gte: HTTP 상태 코드 하한
        status_code_lte: HTTP 상태 코드 상한
        is_streaming: 스트리밍 응답 여부
        limit: 페이지 크기 (1-1000)
        offset: 시작 위치

    Returns:
        AuditLogListResponse: 페이지네이션된 감사 로그 목록
    """
    # 기본 시간 범위 설정 (파티션 성능 최적화)
    if not end_time:
        end_time = datetime.now(UTC)
    if not start_time:
        start_time = end_time - timedelta(days=7)

    # 기본 쿼리 - org_id와 timestamp 필터 필수
    query = select(AuditLog).where(
        AuditLog.org_id == org_id,
        AuditLog.timestamp >= start_time,
        AuditLog.timestamp <= end_time,
    )

    # 선택적 필터 적용
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action.value)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type.value)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)
    if status_code is not None:
        query = query.where(AuditLog.status_code == status_code)
    if status_code_gte is not None:
        query = query.where(AuditLog.status_code >= status_code_gte)
    if status_code_lte is not None:
        query = query.where(AuditLog.status_code <= status_code_lte)
    if is_streaming is not None:
        query = query.where(AuditLog.is_streaming == is_streaming)

    # 전체 카운트 조회 (페이지네이션 전)
    count_query = select(func.count()).select_from(query.subquery())
    total = await session.scalar(count_query) or 0

    # 정렬 및 페이지네이션
    query = query.order_by(AuditLog.timestamp.desc())
    query = query.limit(limit).offset(offset)

    # 쿼리 실행
    result = await session.execute(query)
    rows = result.scalars().all()

    # Pydantic 모델로 변환
    entries = [_to_audit_entry(row) for row in rows]

    return AuditLogListResponse(
        entries=entries,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(offset + len(entries)) < total,
    )


# ---------------------------------------------------------------------------
# GET /audit/summary - 감사 로그 집계 통계
# ---------------------------------------------------------------------------


@router.get("/summary", response_model=AuditSummaryResponse)
async def get_audit_summary(
    # 필수 의존성
    org_id: str = Depends(require_org_id),
    _user: User = Depends(require_admin),  # 권한 체크용 (실제 사용 안 함)
    session: AsyncSession = Depends(get_session),
    # 쿼리 파라미터
    group_by: AuditGroupBy = Query(..., description="집계 기준"),
    start_time: datetime | None = Query(None, description="시작 시간 (기본: 7일 전)"),
    end_time: datetime | None = Query(None, description="종료 시간 (기본: 현재)"),
) -> AuditSummaryResponse:
    """감사 로그 집계 통계 조회

    지정된 기준으로 감사 로그를 집계하여 통계를 반환합니다.

    집계 기준:
    - action: 액션별 카운트 (CREATE, READ, UPDATE 등)
    - resource_type: 리소스 타입별 카운트 (assistant, thread, run 등)
    - user_id: 사용자별 카운트
    - day: 일별 카운트

    Args:
        org_id: 조직 ID (인증된 사용자에서 자동 추출)
        group_by: 집계 기준
        start_time: 시작 시간 (기본: 7일 전)
        end_time: 종료 시간 (기본: 현재)

    Returns:
        AuditSummaryResponse: 집계 결과
    """
    # 기본 시간 범위 설정
    if not end_time:
        end_time = datetime.now(UTC)
    if not start_time:
        start_time = end_time - timedelta(days=7)

    # 집계 컬럼 결정
    group_column = _get_group_column(group_by)

    # 집계 쿼리
    query = (
        select(
            group_column.label("key"),
            func.count().label("count"),
            func.min(AuditLog.timestamp).label("earliest"),
            func.max(AuditLog.timestamp).label("latest"),
        )
        .where(
            AuditLog.org_id == org_id,
            AuditLog.timestamp >= start_time,
            AuditLog.timestamp <= end_time,
        )
        .group_by(group_column)
        .order_by(func.count().desc())
    )

    result = await session.execute(query)
    rows = result.fetchall()

    # 전체 카운트 조회
    total_query = (
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.org_id == org_id,
            AuditLog.timestamp >= start_time,
            AuditLog.timestamp <= end_time,
        )
    )
    total_count = await session.scalar(total_query) or 0

    # 응답 생성
    items = [
        AuditSummaryItem(
            key=str(row.key) if row.key is not None else "unknown",
            count=row.count,
            earliest=row.earliest,
            latest=row.latest,
        )
        for row in rows
    ]

    return AuditSummaryResponse(
        group_by=group_by,
        items=items,
        total_count=total_count,
        start_time=start_time,
        end_time=end_time,
    )


# ---------------------------------------------------------------------------
# POST /audit/export - 감사 로그 내보내기
# ---------------------------------------------------------------------------


async def _stream_csv(
    session: AsyncSession,
    query: Any,
) -> AsyncGenerator[bytes, None]:
    """감사 로그를 CSV 형식으로 스트리밍

    대용량 데이터를 메모리 효율적으로 처리하기 위해
    행 단위로 스트리밍합니다.

    Args:
        session: 데이터베이스 세션
        query: SQLAlchemy 쿼리 객체

    Yields:
        bytes: CSV 형식의 데이터 청크
    """
    fieldnames = [
        "id",
        "timestamp",
        "user_id",
        "org_id",
        "action",
        "resource_type",
        "resource_id",
        "http_method",
        "path",
        "status_code",
        "duration_ms",
        "ip_address",
        "is_streaming",
        "error_message",
    ]

    # 헤더 출력
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    yield output.getvalue().encode("utf-8")

    # 행 단위 스트리밍
    result = await session.stream(query)
    async for row in result.scalars():
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writerow(
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat(),
                "user_id": row.user_id,
                "org_id": row.org_id or "",
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id or "",
                "http_method": row.http_method,
                "path": row.path,
                "status_code": row.status_code,
                "duration_ms": row.duration_ms,
                "ip_address": row.ip_address or "",
                "is_streaming": row.is_streaming,
                "error_message": row.error_message or "",
            }
        )
        yield output.getvalue().encode("utf-8")


async def _stream_json(
    session: AsyncSession,
    query: Any,
) -> AsyncGenerator[bytes, None]:
    """감사 로그를 JSON 배열 형식으로 스트리밍

    JSON 배열의 시작([), 각 항목, 종료(])를 순차적으로 스트리밍합니다.

    Args:
        session: 데이터베이스 세션
        query: SQLAlchemy 쿼리 객체

    Yields:
        bytes: JSON 형식의 데이터 청크
    """
    yield b"[\n"

    first = True
    result = await session.stream(query)
    async for row in result.scalars():
        entry = _to_audit_entry(row)
        json_str = entry.model_dump_json()

        if first:
            first = False
        else:
            yield b",\n"

        yield json_str.encode("utf-8")

    yield b"\n]"


@router.post("/export")
async def export_audit_logs(
    request: AuditExportRequest,
    # 필수 의존성
    org_id: str = Depends(require_org_id),
    _user: User = Depends(require_owner),  # 권한 체크용 (실제 사용 안 함)
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """감사 로그 내보내기

    감사 로그를 CSV 또는 JSON 형식으로 내보냅니다.
    대용량 데이터를 메모리 효율적으로 처리하기 위해 스트리밍 응답을 사용합니다.

    보안:
    - OWNER 역할만 내보내기 가능 (민감 데이터 접근)
    - org_id 스코핑 자동 적용 (다른 조직 로그 접근 불가)

    Args:
        request: 내보내기 요청 (형식, 시간 범위, 필터)
        org_id: 조직 ID (인증된 사용자에서 자동 추출)
        user: 권한이 확인된 사용자

    Returns:
        StreamingResponse: CSV 또는 JSON 파일 다운로드
    """
    # 시간 범위 설정
    end_time = request.end_time or datetime.now(UTC)
    start_time = request.start_time or (end_time - timedelta(days=7))

    # 기본 쿼리 - org_id 필수 필터
    query = select(AuditLog).where(
        AuditLog.org_id == org_id,
        AuditLog.timestamp >= start_time,
        AuditLog.timestamp <= end_time,
    )

    # 추가 필터 적용
    if request.filters:
        if request.filters.user_id:
            query = query.where(AuditLog.user_id == request.filters.user_id)
        if request.filters.action:
            query = query.where(AuditLog.action == request.filters.action.value)
        if request.filters.resource_type:
            query = query.where(
                AuditLog.resource_type == request.filters.resource_type.value
            )
        if request.filters.resource_id:
            query = query.where(AuditLog.resource_id == request.filters.resource_id)
        if request.filters.status_code is not None:
            query = query.where(AuditLog.status_code == request.filters.status_code)
        if request.filters.is_streaming is not None:
            query = query.where(AuditLog.is_streaming == request.filters.is_streaming)

    # 정렬
    query = query.order_by(AuditLog.timestamp.desc())

    # 파일명 생성
    timestamp_str = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    if request.format == AuditExportFormat.CSV:
        filename = f"audit_logs_{timestamp_str}.csv"
        media_type = "text/csv"
        generator = _stream_csv(session, query)
    else:
        filename = f"audit_logs_{timestamp_str}.json"
        media_type = "application/json"
        generator = _stream_json(session, query)

    return StreamingResponse(
        generator,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
