"""Unit tests for Cron scheduling utilities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.agent_server.utils.cron import (
    get_cron_description,
    get_next_n_runs,
    get_next_run_time,
    get_previous_run_time,
    validate_cron_schedule,
)


class TestValidateCronSchedule:
    """Test cron schedule validation."""

    # ==================== Valid Schedules ====================

    def test_valid_every_minute(self) -> None:
        """Every minute schedule should be valid."""
        assert validate_cron_schedule("* * * * *") is True

    def test_valid_every_hour(self) -> None:
        """Every hour schedule should be valid."""
        assert validate_cron_schedule("0 * * * *") is True

    def test_valid_daily_at_9am(self) -> None:
        """Daily at 9am schedule should be valid."""
        assert validate_cron_schedule("0 9 * * *") is True

    def test_valid_weekdays_at_9am(self) -> None:
        """Weekdays at 9am schedule should be valid."""
        assert validate_cron_schedule("0 9 * * 1-5") is True

    def test_valid_every_15_minutes(self) -> None:
        """Every 15 minutes schedule should be valid."""
        assert validate_cron_schedule("*/15 * * * *") is True

    def test_valid_monthly_first_day(self) -> None:
        """Monthly on first day schedule should be valid."""
        assert validate_cron_schedule("0 0 1 * *") is True

    def test_valid_specific_time(self) -> None:
        """Specific time schedule should be valid."""
        assert validate_cron_schedule("30 14 * * *") is True

    def test_valid_complex_schedule(self) -> None:
        """Complex schedule with ranges and steps should be valid."""
        assert validate_cron_schedule("0,30 9-17 * * 1-5") is True

    # ==================== Invalid Schedules ====================

    def test_invalid_empty_string(self) -> None:
        """Empty string should be invalid."""
        assert validate_cron_schedule("") is False

    def test_invalid_random_text(self) -> None:
        """Random text should be invalid."""
        assert validate_cron_schedule("invalid") is False

    def test_invalid_too_few_fields(self) -> None:
        """Schedule with too few fields should be invalid."""
        assert validate_cron_schedule("* * * *") is False

    def test_six_fields_valid_with_seconds(self) -> None:
        """Schedule with 6 fields is valid (includes seconds field)."""
        # croniter supports 6-field cron expressions (with seconds)
        assert validate_cron_schedule("* * * * * *") is True

    def test_invalid_minute_out_of_range(self) -> None:
        """Minute out of range (0-59) should be invalid."""
        assert validate_cron_schedule("60 * * * *") is False

    def test_invalid_hour_out_of_range(self) -> None:
        """Hour out of range (0-23) should be invalid."""
        assert validate_cron_schedule("0 24 * * *") is False

    def test_invalid_day_out_of_range(self) -> None:
        """Day of month out of range (1-31) should be invalid."""
        assert validate_cron_schedule("0 0 32 * *") is False

    def test_invalid_month_out_of_range(self) -> None:
        """Month out of range (1-12) should be invalid."""
        assert validate_cron_schedule("0 0 1 13 *") is False

    def test_weekday_7_valid_as_sunday(self) -> None:
        """Weekday 7 is valid (croniter treats both 0 and 7 as Sunday)."""
        # croniter accepts 7 as Sunday (same as 0)
        assert validate_cron_schedule("0 0 * * 7") is True

    def test_invalid_weekday_out_of_range(self) -> None:
        """Weekday out of range (>7) should be invalid."""
        assert validate_cron_schedule("0 0 * * 8") is False


class TestGetNextRunTime:
    """Test next run time calculation."""

    def test_next_run_every_minute(self) -> None:
        """Next run for every-minute schedule should be within 1 minute."""
        base_time = datetime(2026, 1, 4, 10, 30, 0, tzinfo=UTC)
        result = get_next_run_time("* * * * *", base_time)

        assert result > base_time
        assert (result - base_time) <= timedelta(minutes=1)

    def test_next_run_every_hour(self) -> None:
        """Next run for every-hour schedule should be at next hour."""
        base_time = datetime(2026, 1, 4, 10, 30, 0, tzinfo=UTC)
        result = get_next_run_time("0 * * * *", base_time)

        assert result == datetime(2026, 1, 4, 11, 0, 0, tzinfo=UTC)

    def test_next_run_daily_at_9am(self) -> None:
        """Next run for daily 9am schedule should be next 9am."""
        # Before 9am
        base_time = datetime(2026, 1, 4, 8, 0, 0, tzinfo=UTC)
        result = get_next_run_time("0 9 * * *", base_time)
        assert result == datetime(2026, 1, 4, 9, 0, 0, tzinfo=UTC)

        # After 9am - should be next day
        base_time = datetime(2026, 1, 4, 10, 0, 0, tzinfo=UTC)
        result = get_next_run_time("0 9 * * *", base_time)
        assert result == datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)

    def test_next_run_uses_current_time_by_default(self) -> None:
        """When no base_time provided, should use current time."""
        result = get_next_run_time("0 * * * *")
        now = datetime.now(UTC)

        # Result should be in the future
        assert result > now
        # Result should be within 1 hour
        assert (result - now) <= timedelta(hours=1)

    def test_next_run_invalid_schedule_raises_error(self) -> None:
        """Invalid schedule should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            get_next_run_time("invalid")


class TestGetPreviousRunTime:
    """Test previous run time calculation."""

    def test_previous_run_every_minute(self) -> None:
        """Previous run for every-minute schedule should be within 1 minute."""
        base_time = datetime(2026, 1, 4, 10, 30, 0, tzinfo=UTC)
        result = get_previous_run_time("* * * * *", base_time)

        assert result < base_time
        assert (base_time - result) <= timedelta(minutes=1)

    def test_previous_run_every_hour(self) -> None:
        """Previous run for every-hour schedule should be at previous hour."""
        base_time = datetime(2026, 1, 4, 10, 30, 0, tzinfo=UTC)
        result = get_previous_run_time("0 * * * *", base_time)

        assert result == datetime(2026, 1, 4, 10, 0, 0, tzinfo=UTC)

    def test_previous_run_daily_at_9am(self) -> None:
        """Previous run for daily 9am should be yesterday or today 9am."""
        # After 9am - should be today
        base_time = datetime(2026, 1, 4, 10, 0, 0, tzinfo=UTC)
        result = get_previous_run_time("0 9 * * *", base_time)
        assert result == datetime(2026, 1, 4, 9, 0, 0, tzinfo=UTC)

        # Before 9am - should be yesterday
        base_time = datetime(2026, 1, 4, 8, 0, 0, tzinfo=UTC)
        result = get_previous_run_time("0 9 * * *", base_time)
        assert result == datetime(2026, 1, 3, 9, 0, 0, tzinfo=UTC)

    def test_previous_run_uses_current_time_by_default(self) -> None:
        """When no base_time provided, should use current time."""
        result = get_previous_run_time("0 * * * *")
        now = datetime.now(UTC)

        # Result should be in the past
        assert result < now
        # Result should be within 1 hour
        assert (now - result) <= timedelta(hours=1)

    def test_previous_run_invalid_schedule_raises_error(self) -> None:
        """Invalid schedule should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            get_previous_run_time("invalid")


class TestGetNextNRuns:
    """Test multiple next run times calculation."""

    def test_get_next_3_runs(self) -> None:
        """Should return exactly 3 next run times."""
        base_time = datetime(2026, 1, 4, 10, 0, 0, tzinfo=UTC)
        result = get_next_n_runs("0 * * * *", 3, base_time)

        assert len(result) == 3
        assert result[0] == datetime(2026, 1, 4, 11, 0, 0, tzinfo=UTC)
        assert result[1] == datetime(2026, 1, 4, 12, 0, 0, tzinfo=UTC)
        assert result[2] == datetime(2026, 1, 4, 13, 0, 0, tzinfo=UTC)

    def test_get_next_5_runs_daily(self) -> None:
        """Should return 5 consecutive daily runs."""
        base_time = datetime(2026, 1, 4, 10, 0, 0, tzinfo=UTC)
        result = get_next_n_runs("0 9 * * *", 5, base_time)

        assert len(result) == 5
        # First run should be next day since we're after 9am
        assert result[0] == datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)
        assert result[1] == datetime(2026, 1, 6, 9, 0, 0, tzinfo=UTC)
        assert result[2] == datetime(2026, 1, 7, 9, 0, 0, tzinfo=UTC)
        assert result[3] == datetime(2026, 1, 8, 9, 0, 0, tzinfo=UTC)
        assert result[4] == datetime(2026, 1, 9, 9, 0, 0, tzinfo=UTC)

    def test_get_next_1_run(self) -> None:
        """Should work with n=1."""
        base_time = datetime(2026, 1, 4, 10, 0, 0, tzinfo=UTC)
        result = get_next_n_runs("0 * * * *", 1, base_time)

        assert len(result) == 1
        assert result[0] == datetime(2026, 1, 4, 11, 0, 0, tzinfo=UTC)

    def test_get_next_runs_zero_raises_error(self) -> None:
        """n=0 should raise ValueError."""
        with pytest.raises(ValueError, match="n must be positive"):
            get_next_n_runs("0 * * * *", 0)

    def test_get_next_runs_negative_raises_error(self) -> None:
        """Negative n should raise ValueError."""
        with pytest.raises(ValueError, match="n must be positive"):
            get_next_n_runs("0 * * * *", -1)

    def test_get_next_runs_invalid_schedule_raises_error(self) -> None:
        """Invalid schedule should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid cron expression"):
            get_next_n_runs("invalid", 3)

    def test_get_next_runs_uses_current_time_by_default(self) -> None:
        """When no base_time provided, should use current time."""
        result = get_next_n_runs("0 * * * *", 3)
        now = datetime.now(UTC)

        assert len(result) == 3
        # All results should be in the future
        for run_time in result:
            assert run_time > now
        # Results should be in order
        assert result[0] < result[1] < result[2]


class TestGetCronDescription:
    """Test human-readable cron description."""

    def test_every_minute(self) -> None:
        """Every minute should have clear description."""
        assert get_cron_description("* * * * *") == "Every minute"

    def test_every_n_minutes(self) -> None:
        """Every N minutes should have clear description."""
        assert get_cron_description("*/15 * * * *") == "Every 15 minutes"
        assert get_cron_description("*/5 * * * *") == "Every 5 minutes"
        assert get_cron_description("*/30 * * * *") == "Every 30 minutes"

    def test_every_hour(self) -> None:
        """Every hour should have clear description."""
        assert get_cron_description("0 * * * *") == "Every hour"

    def test_at_specific_time(self) -> None:
        """Specific time should show formatted time."""
        assert get_cron_description("0 9 * * *") == "At 09:00"
        assert get_cron_description("0 14 * * *") == "At 14:00"
        assert get_cron_description("30 9 * * *") == "At 09:30"

    def test_complex_schedule_returns_original(self) -> None:
        """Complex schedules that don't match patterns return original."""
        schedule = "0,30 9-17 * * 1-5"
        assert get_cron_description(schedule) == schedule

    def test_invalid_schedule_returns_message(self) -> None:
        """Invalid schedule should return error message."""
        assert get_cron_description("invalid") == "Invalid cron expression"


class TestCronEdgeCases:
    """Test edge cases and special scenarios."""

    def test_leap_year_handling(self) -> None:
        """Cron should handle leap year dates correctly."""
        # February 29, 2028 is a leap year
        base_time = datetime(2028, 2, 28, 10, 0, 0, tzinfo=UTC)
        result = get_next_run_time("0 9 29 2 *", base_time)

        # Should get Feb 29, 2028 at 9am (leap year)
        assert result == datetime(2028, 2, 29, 9, 0, 0, tzinfo=UTC)

    def test_year_boundary_crossing(self) -> None:
        """Next run should correctly cross year boundaries."""
        # December 31, 2026 at 23:30
        base_time = datetime(2026, 12, 31, 23, 30, 0, tzinfo=UTC)
        result = get_next_run_time("0 9 * * *", base_time)

        # Should be January 1, 2027 at 9am
        assert result == datetime(2027, 1, 1, 9, 0, 0, tzinfo=UTC)

    def test_month_boundary_crossing(self) -> None:
        """Next run should correctly cross month boundaries."""
        # January 31, 2026 at 23:30
        base_time = datetime(2026, 1, 31, 23, 30, 0, tzinfo=UTC)
        result = get_next_run_time("0 9 * * *", base_time)

        # Should be February 1, 2026 at 9am
        assert result == datetime(2026, 2, 1, 9, 0, 0, tzinfo=UTC)

    def test_weekday_schedule(self) -> None:
        """Weekday-only schedule should skip weekends."""
        # Saturday, January 3, 2026 at 10am
        base_time = datetime(2026, 1, 3, 10, 0, 0, tzinfo=UTC)
        result = get_next_run_time("0 9 * * 1-5", base_time)

        # Should be Monday, January 5, 2026 at 9am
        assert result == datetime(2026, 1, 5, 9, 0, 0, tzinfo=UTC)
