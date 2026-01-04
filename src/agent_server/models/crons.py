"""Cron 스케줄링 관련 Pydantic 모델

이 모듈은 LangGraph 그래프의 정기적 실행을 위한 Cron 스케줄링 API 모델을 정의합니다.
Agent Protocol과 LangGraph SDK 호환성을 위해 설계되었습니다.

주요 구성 요소:
• CronCreate - Cron 작업 생성 요청 모델
• Cron - Cron 작업 엔티티 모델 (ORM 매핑)
• CronCountRequest/Response - Cron 개수 조회 모델
• CronSearchRequest/Response - Cron 검색 모델
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CronCreate(BaseModel):
    """Cron 작업 생성 요청 모델

    정기적으로 실행될 그래프 작업을 스케줄링할 때 사용합니다.

    필드 설명:
        assistant_id: 실행할 어시스턴트 ID
        schedule: Cron 표현식 (예: "0 * * * *" - 매 시간)
        input: 그래프 실행 시 전달할 입력 데이터
        metadata: 사용자 정의 메타데이터
        config: 런타임 설정 (model, temperature 등)
        webhook: 실행 완료 시 호출할 웹훅 URL
        interrupt_before: 이 노드들 실행 전 중단
        interrupt_after: 이 노드들 실행 후 중단
        multitask_strategy: 동시 실행 전략 (reject, rollback, interrupt, enqueue)

    사용 예:
        request = CronCreate(
            assistant_id="weather_agent",
            schedule="0 9 * * *",  # 매일 오전 9시
            input={"location": "Seoul"},
            metadata={"type": "daily_weather"}
        )
    """

    assistant_id: str = Field(..., description="실행할 어시스턴트 ID")
    schedule: str = Field(..., description="Cron 표현식 (예: '0 * * * *' - 매 시간)")
    input: dict[str, Any] | None = Field(None, description="그래프 실행 입력 데이터")
    metadata: dict[str, Any] | None = Field(None, description="사용자 정의 메타데이터")
    config: dict[str, Any] | None = Field(None, description="런타임 설정")
    webhook: str | None = Field(None, description="실행 완료 시 호출할 웹훅 URL")
    interrupt_before: list[str] | None = Field(None, description="실행 전 중단할 노드 목록")
    interrupt_after: list[str] | None = Field(None, description="실행 후 중단할 노드 목록")
    multitask_strategy: str | None = Field(None, description="동시 실행 전략")


class Cron(BaseModel):
    """Cron 작업 엔티티 모델

    데이터베이스에 저장된 Cron 작업을 나타내는 모델입니다.
    ORM 모델과 직접 매핑되며, Agent Protocol 응답으로 반환됩니다.

    필드 설명:
        cron_id: Cron 작업 고유 식별자
        assistant_id: 연결된 어시스턴트 ID
        thread_id: 연결된 스레드 ID (선택)
        user_id: Cron 소유자 사용자 ID
        schedule: Cron 표현식
        payload: 실행 시 사용할 전체 페이로드
        next_run_date: 다음 실행 예정 시간
        end_time: Cron 종료 시간 (선택)
        created_at: 생성 타임스탬프
        updated_at: 수정 타임스탬프
    """

    cron_id: str = Field(..., description="Cron 작업 고유 ID")
    assistant_id: str = Field(..., description="연결된 어시스턴트 ID")
    thread_id: str | None = Field(None, description="연결된 스레드 ID")
    user_id: str = Field(..., description="Cron 소유자 사용자 ID")
    schedule: str = Field(..., description="Cron 표현식")
    payload: dict[str, Any] = Field(default_factory=dict, description="실행 페이로드")
    next_run_date: datetime | None = Field(None, description="다음 실행 예정 시간")
    end_time: datetime | None = Field(None, description="Cron 종료 시간")
    created_at: datetime = Field(..., description="생성 타임스탬프")
    updated_at: datetime | None = Field(None, description="수정 타임스탬프")

    model_config = ConfigDict(from_attributes=True)


class CronCountRequest(BaseModel):
    """Cron 개수 조회 요청 모델

    필터 조건에 맞는 Cron 작업 개수를 조회할 때 사용합니다.

    필드 설명:
        assistant_id: 어시스턴트 ID 필터
        thread_id: 스레드 ID 필터
        metadata: 메타데이터 필터 (JSONB 부분 매칭)
    """

    assistant_id: str | None = Field(None, description="어시스턴트 ID 필터")
    thread_id: str | None = Field(None, description="스레드 ID 필터")
    metadata: dict[str, Any] | None = Field(None, description="메타데이터 필터")


class CronCountResponse(BaseModel):
    """Cron 개수 조회 응답 모델"""

    count: int = Field(..., description="조건에 맞는 Cron 작업 개수")


class CronSearchRequest(BaseModel):
    """Cron 검색 요청 모델

    필터 조건과 페이지네이션으로 Cron 작업을 검색합니다.

    필드 설명:
        assistant_id: 어시스턴트 ID 필터
        thread_id: 스레드 ID 필터
        metadata: 메타데이터 필터
        limit: 최대 결과 개수 (1~1000)
        offset: 결과 시작 위치
    """

    assistant_id: str | None = Field(None, description="어시스턴트 ID 필터")
    thread_id: str | None = Field(None, description="스레드 ID 필터")
    metadata: dict[str, Any] | None = Field(None, description="메타데이터 필터")
    limit: int = Field(10, ge=1, le=1000, description="최대 결과 개수")
    offset: int = Field(0, ge=0, description="결과 시작 위치")


class CronSearchResponse(BaseModel):
    """Cron 검색 응답 모델"""

    crons: list[Cron] = Field(..., description="검색된 Cron 작업 목록")
    total: int = Field(..., description="전체 매칭 개수")
    limit: int = Field(..., description="요청된 최대 개수")
    offset: int = Field(..., description="결과 시작 위치")
