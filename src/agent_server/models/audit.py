"""Audit Logging Pydantic Models

이 모듈은 감사 로깅 기능의 요청/응답 모델을 정의합니다.
Agent Protocol 규격을 준수하며, 멀티테넌트 격리와 세분화된 권한 제어를 지원합니다.

주요 모델:
• AuditAction - 감사 로그 액션 열거형
• AuditEntry - 단일 감사 로그 엔트리
• AuditLogResponse - 감사 로그 조회 응답
• AuditLogListResponse - 감사 로그 목록 응답 (페이지네이션)
• AuditLogFilters - 감사 로그 필터 조건
• AuditSummary - 감사 로그 집계 응답
• AuditExportRequest - 감사 로그 내보내기 요청

보안 고려사항:
- org_id 필터링은 모든 조회에서 필수 (멀티테넌트 격리)
- ADMIN 역할: 조회 가능
- OWNER 역할: 내보내기 가능 (더 높은 권한 필요)
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditAction(str, Enum):
    """감사 로그 액션 열거형

    HTTP 메서드와 리소스 경로에서 추론되는 액션 유형입니다.

    액션 종류:
    - CREATE: 리소스 생성 (POST /assistants, POST /threads)
    - READ: 리소스 조회 (GET /assistants, GET /threads/{id})
    - UPDATE: 리소스 수정 (PATCH /assistants/{id}, PUT /threads/{id})
    - DELETE: 리소스 삭제 (DELETE /assistants/{id})
    - LIST: 리소스 목록 조회 (GET /assistants, GET /threads)
    - SEARCH: 리소스 검색 (POST /assistants/search)
    - RUN: 그래프 실행 (POST /runs, POST /threads/{id}/runs)
    - STREAM: 스트리밍 실행 (POST /runs/stream)
    - CANCEL: 실행 취소 (POST /runs/{id}/cancel)
    - COPY: 리소스 복사 (POST /threads/{id}/copy)
    - HISTORY: 이력 조회 (GET /threads/{id}/history)
    - UNKNOWN: 분류 불가
    """

    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LIST = "LIST"
    SEARCH = "SEARCH"
    RUN = "RUN"
    STREAM = "STREAM"
    CANCEL = "CANCEL"
    COPY = "COPY"
    HISTORY = "HISTORY"
    UNKNOWN = "UNKNOWN"


class AuditResourceType(str, Enum):
    """감사 로그 리소스 타입 열거형

    API 경로에서 추론되는 리소스 유형입니다.
    """

    ASSISTANT = "assistant"
    THREAD = "thread"
    RUN = "run"
    STORE = "store"
    ORGANIZATION = "organization"
    API_KEY = "api_key"
    AGENT = "agent"  # A2A 에이전트
    AUDIT = "audit"  # 감사 로그 자체
    UNKNOWN = "unknown"


class AuditGroupBy(str, Enum):
    """감사 로그 집계 기준 열거형

    집계 쿼리에서 사용 가능한 그룹화 기준입니다.
    """

    ACTION = "action"
    RESOURCE_TYPE = "resource_type"
    USER_ID = "user_id"
    DAY = "day"


class AuditEntry(BaseModel):
    """단일 감사 로그 엔트리

    API 요청/응답에 대한 완전한 감사 정보를 담습니다.

    필드 그룹:
    1. 식별자: id, timestamp
    2. 사용자: user_id, org_id
    3. 액션: action, resource_type, resource_id
    4. 요청: http_method, path, request_body, ip_address, user_agent
    5. 응답: status_code, response_summary, duration_ms
    6. 오류: error_message, error_class
    7. 스트리밍: is_streaming
    8. 메타데이터: metadata
    """

    # 식별자
    id: str = Field(..., description="감사 로그 고유 ID")
    timestamp: datetime = Field(..., description="감사 로그 생성 시간")

    # 사용자 정보
    user_id: str = Field(..., description="요청 사용자 ID")
    org_id: str | None = Field(None, description="요청 사용자 조직 ID")

    # 액션 정보
    action: AuditAction = Field(..., description="수행된 액션 (CREATE, READ, UPDATE 등)")
    resource_type: AuditResourceType = Field(..., description="대상 리소스 타입")
    resource_id: str | None = Field(None, description="대상 리소스 ID (있는 경우)")

    # HTTP 요청 정보
    http_method: str = Field(..., description="HTTP 메서드 (GET, POST, PATCH, DELETE)")
    path: str = Field(..., description="API 경로")
    ip_address: str | None = Field(None, description="클라이언트 IP 주소")
    user_agent: str | None = Field(None, description="클라이언트 User-Agent")

    # 요청/응답 데이터
    request_body: dict[str, Any] | None = Field(
        None, description="요청 본문 (민감 정보 마스킹됨, 10KB 제한)"
    )
    response_summary: dict[str, Any] | None = Field(
        None, description="응답 요약 (스트리밍 시 bytes_sent 포함)"
    )
    status_code: int = Field(..., description="HTTP 응답 상태 코드")
    duration_ms: int = Field(..., description="요청 처리 시간 (밀리초)")

    # 오류 정보
    error_message: str | None = Field(None, description="오류 메시지 (실패 시)")
    error_class: str | None = Field(None, description="예외 클래스명 (실패 시)")

    # 스트리밍 여부
    is_streaming: bool = Field(False, description="SSE 스트리밍 응답 여부")

    # 메타데이터
    metadata: dict[str, Any] = Field(default_factory=dict, description="추가 메타데이터")

    model_config = ConfigDict(from_attributes=True)


class AuditLogFilters(BaseModel):
    """감사 로그 필터 조건

    감사 로그 조회 시 사용되는 필터 조건입니다.
    org_id는 멀티테넌트 격리를 위해 필수입니다.

    필터 옵션:
    - org_id: 조직 ID (필수, 보안)
    - user_id: 특정 사용자
    - action: 특정 액션
    - resource_type: 특정 리소스 타입
    - resource_id: 특정 리소스 ID
    - start_time: 시작 시간
    - end_time: 종료 시간
    - status_code: HTTP 상태 코드
    - is_streaming: 스트리밍 여부
    """

    # 필수 필터 (보안)
    org_id: str = Field(..., description="조직 ID (필수, 멀티테넌트 격리)")

    # 선택 필터
    user_id: str | None = Field(None, description="사용자 ID 필터")
    action: AuditAction | None = Field(None, description="액션 필터")
    resource_type: AuditResourceType | None = Field(None, description="리소스 타입 필터")
    resource_id: str | None = Field(None, description="리소스 ID 필터")
    start_time: datetime | None = Field(None, description="시작 시간 (기본: 7일 전)")
    end_time: datetime | None = Field(None, description="종료 시간 (기본: 현재)")
    status_code: int | None = Field(None, description="HTTP 상태 코드 정확히 일치 필터")
    status_code_gte: int | None = Field(None, description="HTTP 상태 코드 하한 (포함)")
    status_code_lte: int | None = Field(None, description="HTTP 상태 코드 상한 (포함)")
    is_streaming: bool | None = Field(None, description="스트리밍 여부 필터")


class AuditLogResponse(BaseModel):
    """단일 감사 로그 조회 응답

    GET /audit/logs/{id} 엔드포인트의 응답 모델입니다.
    """

    entry: AuditEntry = Field(..., description="감사 로그 엔트리")

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    """감사 로그 목록 응답 (페이지네이션)

    GET /audit/logs 엔드포인트의 응답 모델입니다.
    페이지네이션과 필터링을 지원합니다.
    """

    entries: list[AuditEntry] = Field(default_factory=list, description="감사 로그 목록")
    total: int = Field(..., description="전체 결과 수")
    limit: int = Field(..., description="페이지 크기")
    offset: int = Field(..., description="시작 위치")
    has_more: bool = Field(..., description="추가 결과 존재 여부")


class AuditSummaryItem(BaseModel):
    """감사 로그 집계 항목

    집계 쿼리 결과의 단일 항목입니다.
    """

    key: str = Field(..., description="집계 키 (액션, 리소스 타입, 사용자 ID 등)")
    count: int = Field(..., description="해당 키의 로그 수")
    earliest: datetime | None = Field(None, description="가장 이른 로그 시간")
    latest: datetime | None = Field(None, description="가장 최근 로그 시간")


class AuditSummaryRequest(BaseModel):
    """감사 로그 집계 요청

    GET /audit/summary 엔드포인트의 요청 모델입니다.
    """

    group_by: AuditGroupBy = Field(
        ...,
        description="집계 기준 (action, resource_type, user_id, day)",
    )
    start_time: datetime | None = Field(None, description="시작 시간")
    end_time: datetime | None = Field(None, description="종료 시간")


class AuditSummaryResponse(BaseModel):
    """감사 로그 집계 응답

    GET /audit/summary 엔드포인트의 응답 모델입니다.
    """

    group_by: AuditGroupBy = Field(..., description="집계 기준")
    items: list[AuditSummaryItem] = Field(default_factory=list, description="집계 결과")
    total_count: int = Field(..., description="전체 로그 수")
    start_time: datetime = Field(..., description="집계 시작 시간")
    end_time: datetime = Field(..., description="집계 종료 시간")


class AuditExportFormat(str, Enum):
    """감사 로그 내보내기 형식"""

    CSV = "csv"
    JSON = "json"


class AuditExportRequest(BaseModel):
    """감사 로그 내보내기 요청

    POST /audit/export 엔드포인트의 요청 모델입니다.
    OWNER 권한이 필요합니다.

    내보내기 형식:
    - csv: CSV 형식 (스트리밍)
    - json: JSON 형식 (스트리밍)

    보안 고려사항:
    - OWNER 역할만 내보내기 가능 (민감 데이터 접근)
    - org_id 스코핑 적용 (다른 조직 로그 접근 불가)
    """

    format: AuditExportFormat = Field(
        AuditExportFormat.CSV, description="내보내기 형식 (csv, json)"
    )
    start_time: datetime | None = Field(None, description="시작 시간")
    end_time: datetime | None = Field(None, description="종료 시간")
    filters: AuditLogFilters | None = Field(None, description="추가 필터")


class AuditExportResponse(BaseModel):
    """감사 로그 내보내기 응답 메타데이터

    내보내기 작업의 결과 정보입니다.
    실제 데이터는 StreamingResponse로 반환됩니다.
    """

    format: AuditExportFormat = Field(..., description="내보내기 형식")
    total_records: int = Field(..., description="내보낸 레코드 수")
    start_time: datetime = Field(..., description="데이터 시작 시간")
    end_time: datetime = Field(..., description="데이터 종료 시간")
    filename: str = Field(..., description="생성된 파일명")


# ---------------------------------------------------------------------------
# API 요청/응답 모델 (경량)
# ---------------------------------------------------------------------------


class AuditLogListRequest(BaseModel):
    """감사 로그 목록 조회 요청 (쿼리 파라미터용)

    GET /audit/logs 엔드포인트의 쿼리 파라미터를 정의합니다.
    """

    user_id: str | None = Field(None, description="사용자 ID 필터")
    action: str | None = Field(None, description="액션 필터")
    resource_type: str | None = Field(None, description="리소스 타입 필터")
    resource_id: str | None = Field(None, description="리소스 ID 필터")
    start_time: datetime | None = Field(None, description="시작 시간")
    end_time: datetime | None = Field(None, description="종료 시간")
    limit: int = Field(100, ge=1, le=1000, description="페이지 크기")
    offset: int = Field(0, ge=0, description="시작 위치")
