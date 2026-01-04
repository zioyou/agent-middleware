"""Cron 스케줄링 유틸리티 함수

이 모듈은 Cron 표현식 검증 및 실행 시간 계산 기능을 제공합니다.
croniter 라이브러리를 사용하여 표준 Cron 표현식을 처리합니다.

주요 기능:
• validate_cron_schedule - Cron 표현식 유효성 검증
• get_next_run_time - 다음 실행 시간 계산
• get_previous_run_time - 이전 실행 시간 계산
• get_next_n_runs - 다음 n개 실행 시간 목록 계산

Cron 표현식 형식:
    ┌───────────── minute (0 - 59)
    │ ┌───────────── hour (0 - 23)
    │ │ ┌───────────── day of month (1 - 31)
    │ │ │ ┌───────────── month (1 - 12)
    │ │ │ │ ┌───────────── day of week (0 - 6) (Sunday=0)
    │ │ │ │ │
    * * * * *

예시:
    "0 * * * *"     - 매 시간 정각
    "0 9 * * *"     - 매일 오전 9시
    "0 9 * * 1-5"   - 평일 오전 9시
    "*/15 * * * *"  - 15분마다
    "0 0 1 * *"     - 매월 1일 자정
"""

from datetime import UTC, datetime

from croniter import croniter


def validate_cron_schedule(schedule: str) -> bool:
    """Cron 표현식 유효성 검증

    주어진 문자열이 유효한 Cron 표현식인지 확인합니다.

    Args:
        schedule: 검증할 Cron 표현식

    Returns:
        유효하면 True, 아니면 False

    사용 예:
        >>> validate_cron_schedule("0 * * * *")
        True
        >>> validate_cron_schedule("invalid")
        False
        >>> validate_cron_schedule("60 * * * *")  # 분 범위 초과
        False
    """
    return croniter.is_valid(schedule)


def get_next_run_time(schedule: str, base_time: datetime | None = None) -> datetime:
    """다음 실행 시간 계산

    Cron 표현식을 기반으로 다음 실행 시간을 계산합니다.

    Args:
        schedule: Cron 표현식
        base_time: 기준 시간 (None이면 현재 UTC 시간)

    Returns:
        다음 실행 시간 (datetime)

    Raises:
        ValueError: 유효하지 않은 Cron 표현식

    사용 예:
        >>> get_next_run_time("0 9 * * *")
        datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)
    """
    if base_time is None:
        base_time = datetime.now(UTC)

    if not croniter.is_valid(schedule):
        raise ValueError(f"Invalid cron expression: {schedule}")

    cron = croniter(schedule, base_time)
    return cron.get_next(datetime)


def get_previous_run_time(schedule: str, base_time: datetime | None = None) -> datetime:
    """이전 실행 시간 계산

    Cron 표현식을 기반으로 이전 실행 시간을 계산합니다.

    Args:
        schedule: Cron 표현식
        base_time: 기준 시간 (None이면 현재 UTC 시간)

    Returns:
        이전 실행 시간 (datetime)

    Raises:
        ValueError: 유효하지 않은 Cron 표현식

    사용 예:
        >>> get_previous_run_time("0 9 * * *")
        datetime(2026, 1, 4, 9, 0, 0, tzinfo=UTC)
    """
    if base_time is None:
        base_time = datetime.now(UTC)

    if not croniter.is_valid(schedule):
        raise ValueError(f"Invalid cron expression: {schedule}")

    cron = croniter(schedule, base_time)
    return cron.get_prev(datetime)


def get_next_n_runs(
    schedule: str,
    n: int,
    base_time: datetime | None = None,
) -> list[datetime]:
    """다음 n개의 실행 시간 계산

    Cron 표현식을 기반으로 다음 n개의 실행 시간 목록을 반환합니다.

    Args:
        schedule: Cron 표현식
        n: 반환할 실행 시간 개수
        base_time: 기준 시간 (None이면 현재 UTC 시간)

    Returns:
        다음 n개 실행 시간 리스트

    Raises:
        ValueError: 유효하지 않은 Cron 표현식 또는 n이 0 이하

    사용 예:
        >>> get_next_n_runs("0 * * * *", 3)
        [datetime(...), datetime(...), datetime(...)]
    """
    if n <= 0:
        raise ValueError("n must be positive")

    if base_time is None:
        base_time = datetime.now(UTC)

    if not croniter.is_valid(schedule):
        raise ValueError(f"Invalid cron expression: {schedule}")

    cron = croniter(schedule, base_time)
    return [cron.get_next(datetime) for _ in range(n)]


def get_cron_description(schedule: str) -> str:
    """Cron 표현식을 사람이 읽을 수 있는 설명으로 변환

    Args:
        schedule: Cron 표현식

    Returns:
        사람이 읽을 수 있는 설명 문자열

    사용 예:
        >>> get_cron_description("0 9 * * *")
        "At 09:00"
        >>> get_cron_description("*/15 * * * *")
        "Every 15 minutes"
    """
    if not croniter.is_valid(schedule):
        return "Invalid cron expression"

    parts = schedule.split()
    if len(parts) != 5:
        return schedule

    minute, hour, day, month, weekday = parts

    # 간단한 패턴 매칭
    if schedule == "* * * * *":
        return "Every minute"
    if minute.startswith("*/") and hour == "*":
        interval = minute[2:]
        return f"Every {interval} minutes"
    if minute == "0" and hour == "*":
        return "Every hour"
    if minute == "0" and hour.isdigit():
        return f"At {hour.zfill(2)}:00"
    if minute.isdigit() and hour.isdigit():
        return f"At {hour.zfill(2)}:{minute.zfill(2)}"

    return schedule
