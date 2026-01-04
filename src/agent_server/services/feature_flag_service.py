"""Feature Flag Service - CRUD and Evaluation Logic

This service manages feature flags with support for:
- Flag creation, update, deletion
- Override management (org/user level)
- Flag evaluation with consistent hashing for rollout
- Change logging for audit trail
- Redis caching for performance
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.orm import (
    FeatureFlag as FeatureFlagORM,
)
from ..core.orm import (
    FeatureFlagChangeLog as FeatureFlagChangeLogORM,
)
from ..core.orm import (
    FeatureFlagOverride as FeatureFlagOverrideORM,
)
from ..models.feature_flags import (
    FeatureFlag,
    FeatureFlagCreate,
    FeatureFlagListRequest,
    FeatureFlagListResponse,
    FeatureFlagOverride,
    FeatureFlagOverrideCreate,
    FeatureFlagOverrideListRequest,
    FeatureFlagOverrideListResponse,
    FeatureFlagOverrideUpdate,
    FeatureFlagUpdate,
    FlagChangeEvent,
    FlagEvaluationContext,
    FlagEvaluationResponse,
    FlagEvaluationResult,
    FlagHistoryRequest,
    FlagHistoryResponse,
    FlagStatus,
    OverrideScope,
    PercentageRolloutConfig,
    RolloutStrategy,
)

logger = logging.getLogger(__name__)

CACHE_TTL_FLAGS = 300
CACHE_PREFIX_FLAGS = "ff_flags"
CACHE_PREFIX_EVAL = "ff_eval"


class FeatureFlagService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_flags(
        self,
        org_id: str,
        request: FeatureFlagListRequest | None = None,
    ) -> FeatureFlagListResponse:
        query = select(FeatureFlagORM).where(FeatureFlagORM.org_id == org_id)

        if request:
            if request.status is not None:
                query = query.where(FeatureFlagORM.status == request.status.value)
            if request.tags:
                query = query.where(FeatureFlagORM.tags.overlap(request.tags))
            if request.is_killswitch is not None:
                query = query.where(FeatureFlagORM.is_killswitch == request.is_killswitch)
            if request.search:
                search_pattern = f"%{request.search}%"
                query = query.where(
                    or_(
                        FeatureFlagORM.key.ilike(search_pattern),
                        FeatureFlagORM.name.ilike(search_pattern),
                        FeatureFlagORM.description.ilike(search_pattern),
                    )
                )

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self._session.execute(count_query)).scalar_one()

        limit = request.limit if request else 20
        offset = request.offset if request else 0

        query = query.order_by(FeatureFlagORM.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        flags = [self._to_pydantic(row) for row in result.scalars().all()]

        return FeatureFlagListResponse(
            flags=flags,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_flag(
        self,
        org_id: str,
        flag_id: str,
    ) -> FeatureFlag | None:
        result = await self._session.execute(
            select(FeatureFlagORM).where(
                FeatureFlagORM.org_id == org_id,
                FeatureFlagORM.flag_id == flag_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_pydantic(row) if row else None

    async def get_flag_by_key(
        self,
        org_id: str,
        key: str,
    ) -> FeatureFlag | None:
        result = await self._session.execute(
            select(FeatureFlagORM).where(
                FeatureFlagORM.org_id == org_id,
                FeatureFlagORM.key == key,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_pydantic(row) if row else None

    async def create_flag(
        self,
        org_id: str,
        request: FeatureFlagCreate,
        created_by: str,
    ) -> FeatureFlag:
        existing = await self.get_flag_by_key(org_id, request.key)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Feature flag '{request.key}' already exists",
            )

        now = datetime.now(UTC)
        flag_orm = FeatureFlagORM(
            org_id=org_id,
            key=request.key,
            name=request.name,
            description=request.description,
            value_type=request.value_type.value,
            default_value=request.default_value,
            enabled_value=request.enabled_value,
            enabled=request.enabled,
            is_killswitch=request.is_killswitch,
            status=FlagStatus.ACTIVE.value,
            rollout=request.rollout.model_dump() if request.rollout else {},
            targeting=request.targeting.model_dump() if request.targeting else None,
            tags=request.tags,
            metadata_dict=request.metadata,
            expires_at=request.expires_at,
            version=1,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )

        self._session.add(flag_orm)
        await self._session.commit()
        await self._session.refresh(flag_orm)

        await self._log_change(
            flag_orm.flag_id,
            flag_orm.key,
            org_id,
            "created",
            changed_by=created_by,
            new_value=self._to_pydantic(flag_orm).model_dump(),
        )

        await self._invalidate_flag_cache(org_id, request.key)
        return self._to_pydantic(flag_orm)

    async def update_flag(
        self,
        org_id: str,
        flag_id: str,
        request: FeatureFlagUpdate,
        updated_by: str,
    ) -> FeatureFlag:
        result = await self._session.execute(
            select(FeatureFlagORM).where(
                FeatureFlagORM.org_id == org_id,
                FeatureFlagORM.flag_id == flag_id,
            )
        )
        flag_orm = result.scalar_one_or_none()
        if not flag_orm:
            raise HTTPException(status_code=404, detail=f"Feature flag '{flag_id}' not found")

        previous_value = self._to_pydantic(flag_orm).model_dump()

        update_data = request.model_dump(exclude_unset=True)

        if "rollout" in update_data and update_data["rollout"] is not None:
            update_data["rollout"] = (
                update_data["rollout"].model_dump()
                if hasattr(update_data["rollout"], "model_dump")
                else update_data["rollout"]
            )
        if "targeting" in update_data and update_data["targeting"] is not None:
            update_data["targeting"] = (
                update_data["targeting"].model_dump()
                if hasattr(update_data["targeting"], "model_dump")
                else update_data["targeting"]
            )
        if "status" in update_data and update_data["status"] is not None:
            update_data["status"] = update_data["status"].value

        event_type = "updated"
        if "enabled" in update_data:
            event_type = "enabled" if update_data["enabled"] else "disabled"
        if "status" in update_data and update_data["status"] == FlagStatus.ARCHIVED.value:
            event_type = "archived"

        for field, value in update_data.items():
            if hasattr(flag_orm, field):
                setattr(flag_orm, field, value)
            elif field == "metadata":
                flag_orm.metadata_dict = value

        flag_orm.version += 1
        flag_orm.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(flag_orm)

        await self._log_change(
            flag_orm.flag_id,
            flag_orm.key,
            org_id,
            event_type,
            changed_by=updated_by,
            previous_value=previous_value,
            new_value=self._to_pydantic(flag_orm).model_dump(),
        )

        await self._invalidate_flag_cache(org_id, flag_orm.key)
        return self._to_pydantic(flag_orm)

    async def delete_flag(
        self,
        org_id: str,
        flag_id: str,
        deleted_by: str,
    ) -> None:
        result = await self._session.execute(
            select(FeatureFlagORM).where(
                FeatureFlagORM.org_id == org_id,
                FeatureFlagORM.flag_id == flag_id,
            )
        )
        flag_orm = result.scalar_one_or_none()
        if not flag_orm:
            raise HTTPException(status_code=404, detail=f"Feature flag '{flag_id}' not found")

        flag_key = flag_orm.key
        previous_value = self._to_pydantic(flag_orm).model_dump()

        await self._session.delete(flag_orm)
        await self._session.commit()

        await self._log_change(
            flag_id,
            flag_key,
            org_id,
            "deleted",
            changed_by=deleted_by,
            previous_value=previous_value,
        )

        await self._invalidate_flag_cache(org_id, flag_key)

    async def list_overrides(
        self,
        org_id: str,
        request: FeatureFlagOverrideListRequest | None = None,
    ) -> FeatureFlagOverrideListResponse:
        query = select(FeatureFlagOverrideORM).where(FeatureFlagOverrideORM.org_id == org_id)

        if request:
            if request.flag_key:
                query = query.where(FeatureFlagOverrideORM.flag_key == request.flag_key)
            if request.scope:
                query = query.where(FeatureFlagOverrideORM.scope == request.scope.value)
            if request.target_id:
                query = query.where(FeatureFlagOverrideORM.target_id == request.target_id)
            if request.enabled is not None:
                query = query.where(FeatureFlagOverrideORM.enabled == request.enabled)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self._session.execute(count_query)).scalar_one()

        limit = request.limit if request else 20
        offset = request.offset if request else 0

        query = query.order_by(FeatureFlagOverrideORM.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        overrides = [self._override_to_pydantic(row) for row in result.scalars().all()]

        return FeatureFlagOverrideListResponse(
            overrides=overrides,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def create_override(
        self,
        org_id: str,
        request: FeatureFlagOverrideCreate,
        created_by: str,
    ) -> FeatureFlagOverride:
        flag = await self.get_flag_by_key(org_id, request.flag_key)
        if not flag:
            raise HTTPException(
                status_code=404,
                detail=f"Feature flag '{request.flag_key}' not found",
            )

        existing = await self._session.execute(
            select(FeatureFlagOverrideORM).where(
                FeatureFlagOverrideORM.flag_id == flag.flag_id,
                FeatureFlagOverrideORM.org_id == org_id,
                FeatureFlagOverrideORM.scope == request.scope.value,
                FeatureFlagOverrideORM.target_id == request.target_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Override for flag '{request.flag_key}' with scope '{request.scope.value}' already exists",
            )

        now = datetime.now(UTC)
        override_orm = FeatureFlagOverrideORM(
            flag_id=flag.flag_id,
            flag_key=request.flag_key,
            org_id=org_id,
            scope=request.scope.value,
            target_id=request.target_id,
            value=request.value,
            enabled=request.enabled,
            reason=request.reason,
            expires_at=request.expires_at,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )

        self._session.add(override_orm)
        await self._session.commit()
        await self._session.refresh(override_orm)

        await self._log_change(
            flag.flag_id,
            request.flag_key,
            org_id,
            "override_added",
            changed_by=created_by,
            new_value=self._override_to_pydantic(override_orm).model_dump(),
        )

        await self._invalidate_flag_cache(org_id, request.flag_key)
        return self._override_to_pydantic(override_orm)

    async def update_override(
        self,
        org_id: str,
        override_id: str,
        request: FeatureFlagOverrideUpdate,
        updated_by: str,
    ) -> FeatureFlagOverride:
        result = await self._session.execute(
            select(FeatureFlagOverrideORM).where(
                FeatureFlagOverrideORM.org_id == org_id,
                FeatureFlagOverrideORM.override_id == override_id,
            )
        )
        override_orm = result.scalar_one_or_none()
        if not override_orm:
            raise HTTPException(status_code=404, detail=f"Override '{override_id}' not found")

        previous_value = self._override_to_pydantic(override_orm).model_dump()

        update_data = request.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(override_orm, field):
                setattr(override_orm, field, value)

        override_orm.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(override_orm)

        await self._log_change(
            override_orm.flag_id,
            override_orm.flag_key,
            org_id,
            "override_updated",
            changed_by=updated_by,
            previous_value=previous_value,
            new_value=self._override_to_pydantic(override_orm).model_dump(),
        )

        await self._invalidate_flag_cache(org_id, override_orm.flag_key)
        return self._override_to_pydantic(override_orm)

    async def delete_override(
        self,
        org_id: str,
        override_id: str,
        deleted_by: str,
    ) -> None:
        result = await self._session.execute(
            select(FeatureFlagOverrideORM).where(
                FeatureFlagOverrideORM.org_id == org_id,
                FeatureFlagOverrideORM.override_id == override_id,
            )
        )
        override_orm = result.scalar_one_or_none()
        if not override_orm:
            raise HTTPException(status_code=404, detail=f"Override '{override_id}' not found")

        flag_id = override_orm.flag_id
        flag_key = override_orm.flag_key
        previous_value = self._override_to_pydantic(override_orm).model_dump()

        await self._session.delete(override_orm)
        await self._session.commit()

        await self._log_change(
            flag_id,
            flag_key,
            org_id,
            "override_removed",
            changed_by=deleted_by,
            previous_value=previous_value,
        )

        await self._invalidate_flag_cache(org_id, flag_key)

    async def evaluate_flags(
        self,
        org_id: str,
        context: FlagEvaluationContext,
        flag_keys: list[str] | None = None,
    ) -> FlagEvaluationResponse:
        if flag_keys:
            flags = [await self.get_flag_by_key(org_id, key) for key in flag_keys]
            flags = [f for f in flags if f is not None]
        else:
            response = await self.list_flags(
                org_id,
                FeatureFlagListRequest(status=FlagStatus.ACTIVE, limit=100),
            )
            flags = response.flags

        results: dict[str, FlagEvaluationResult] = {}
        now = datetime.now(UTC)

        for flag in flags:
            result = await self._evaluate_single_flag(flag, org_id, context, now)
            results[flag.key] = result

        return FlagEvaluationResponse(
            flags=results,
            context=context,
            evaluated_at=now,
        )

    async def _evaluate_single_flag(
        self,
        flag: FeatureFlag,
        org_id: str,
        context: FlagEvaluationContext,
        now: datetime,
    ) -> FlagEvaluationResult:
        cache_key = self._build_eval_cache_key(org_id, flag.key, context)
        cached = await cache_manager.get(cache_key)
        if cached:
            return FlagEvaluationResult.model_validate(cached)

        if flag.status != FlagStatus.ACTIVE:
            result = FlagEvaluationResult(
                flag_key=flag.key,
                value=flag.default_value,
                enabled=False,
                source="default",
                reason=f"Flag is {flag.status.value}",
                flag_id=flag.flag_id,
                evaluated_at=now,
            )
            return result

        if flag.expires_at and flag.expires_at < now:
            result = FlagEvaluationResult(
                flag_key=flag.key,
                value=flag.default_value,
                enabled=False,
                source="default",
                reason="Flag has expired",
                flag_id=flag.flag_id,
                evaluated_at=now,
            )
            return result

        if context.user_id:
            user_override = await self._get_active_override(
                flag.flag_id, org_id, OverrideScope.USER, context.user_id, now
            )
            if user_override:
                result = FlagEvaluationResult(
                    flag_key=flag.key,
                    value=user_override.value,
                    enabled=True,
                    source="override",
                    reason=f"User override: {user_override.reason or 'no reason'}",
                    flag_id=flag.flag_id,
                    override_id=user_override.override_id,
                    evaluated_at=now,
                )
                await cache_manager.set(cache_key, result.model_dump(), ttl=CACHE_TTL_FLAGS)
                return result

        org_override = await self._get_active_override(flag.flag_id, org_id, OverrideScope.ORG, None, now)
        if org_override:
            result = FlagEvaluationResult(
                flag_key=flag.key,
                value=org_override.value,
                enabled=True,
                source="override",
                reason=f"Org override: {org_override.reason or 'no reason'}",
                flag_id=flag.flag_id,
                override_id=org_override.override_id,
                evaluated_at=now,
            )
            await cache_manager.set(cache_key, result.model_dump(), ttl=CACHE_TTL_FLAGS)
            return result

        if not flag.enabled:
            result = FlagEvaluationResult(
                flag_key=flag.key,
                value=flag.default_value,
                enabled=False,
                source="flag",
                reason="Flag is disabled",
                flag_id=flag.flag_id,
                evaluated_at=now,
            )
            await cache_manager.set(cache_key, result.model_dump(), ttl=CACHE_TTL_FLAGS)
            return result

        rollout = PercentageRolloutConfig.model_validate(flag.rollout) if flag.rollout else None
        if rollout and rollout.enabled and rollout.percentage < 100:
            is_in_rollout = self._check_rollout(
                rollout,
                context.user_id,
                context.org_id or org_id,
                flag.key,
            )
            if not is_in_rollout:
                result = FlagEvaluationResult(
                    flag_key=flag.key,
                    value=flag.default_value,
                    enabled=False,
                    source="rollout",
                    reason=f"Not in rollout ({rollout.percentage}%)",
                    flag_id=flag.flag_id,
                    evaluated_at=now,
                )
                await cache_manager.set(cache_key, result.model_dump(), ttl=CACHE_TTL_FLAGS)
                return result

        result = FlagEvaluationResult(
            flag_key=flag.key,
            value=flag.enabled_value,
            enabled=True,
            source="flag",
            reason="Flag is enabled",
            flag_id=flag.flag_id,
            evaluated_at=now,
        )
        await cache_manager.set(cache_key, result.model_dump(), ttl=CACHE_TTL_FLAGS)
        return result

    async def _get_active_override(
        self,
        flag_id: str,
        org_id: str,
        scope: OverrideScope,
        target_id: str | None,
        now: datetime,
    ) -> FeatureFlagOverride | None:
        query = select(FeatureFlagOverrideORM).where(
            and_(
                FeatureFlagOverrideORM.flag_id == flag_id,
                FeatureFlagOverrideORM.org_id == org_id,
                FeatureFlagOverrideORM.scope == scope.value,
                FeatureFlagOverrideORM.enabled == True,  # noqa: E712
                or_(
                    FeatureFlagOverrideORM.expires_at.is_(None),
                    FeatureFlagOverrideORM.expires_at > now,
                ),
            )
        )
        if target_id:
            query = query.where(FeatureFlagOverrideORM.target_id == target_id)
        else:
            query = query.where(FeatureFlagOverrideORM.target_id.is_(None))

        result = await self._session.execute(query)
        row = result.scalar_one_or_none()
        return self._override_to_pydantic(row) if row else None

    def _check_rollout(
        self,
        rollout: PercentageRolloutConfig,
        user_id: str | None,
        org_id: str,
        flag_key: str,
    ) -> bool:
        if rollout.percentage >= 100:
            return True
        if rollout.percentage <= 0:
            return False

        if rollout.strategy == RolloutStrategy.RANDOM:
            import random

            return random.random() * 100 < rollout.percentage

        if rollout.strategy == RolloutStrategy.USER_HASH:
            if not user_id:
                return False
            hash_input = f"{flag_key}:{user_id}"
            if rollout.seed:
                hash_input = f"{rollout.seed}:{hash_input}"
        else:
            hash_input = f"{flag_key}:{org_id}"
            if rollout.seed:
                hash_input = f"{rollout.seed}:{hash_input}"

        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        bucket = hash_value % 100
        return bucket < rollout.percentage

    async def get_flag_history(
        self,
        org_id: str,
        request: FlagHistoryRequest,
    ) -> FlagHistoryResponse:
        query = select(FeatureFlagChangeLogORM).where(FeatureFlagChangeLogORM.org_id == org_id)

        if request.flag_key:
            query = query.where(FeatureFlagChangeLogORM.flag_key == request.flag_key)
        if request.event_type:
            query = query.where(FeatureFlagChangeLogORM.event_type == request.event_type)
        if request.start_time:
            query = query.where(FeatureFlagChangeLogORM.timestamp >= request.start_time)
        if request.end_time:
            query = query.where(FeatureFlagChangeLogORM.timestamp <= request.end_time)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self._session.execute(count_query)).scalar_one()

        query = query.order_by(FeatureFlagChangeLogORM.timestamp.desc())
        query = query.limit(request.limit).offset(request.offset)

        result = await self._session.execute(query)
        events = [self._changelog_to_pydantic(row) for row in result.scalars().all()]

        return FlagHistoryResponse(
            events=events,
            total=total,
            limit=request.limit,
            offset=request.offset,
        )

    async def _log_change(
        self,
        flag_id: str,
        flag_key: str,
        org_id: str,
        event_type: str,
        changed_by: str | None = None,
        previous_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        log_orm = FeatureFlagChangeLogORM(
            flag_id=flag_id,
            flag_key=flag_key,
            org_id=org_id,
            event_type=event_type,
            changed_by=changed_by,
            previous_value=previous_value,
            new_value=new_value,
            metadata_dict=metadata or {},
            timestamp=datetime.now(UTC),
        )
        self._session.add(log_orm)
        await self._session.commit()

    async def _invalidate_flag_cache(self, org_id: str, flag_key: str) -> None:
        await cache_manager.delete(f"{CACHE_PREFIX_FLAGS}:{org_id}:{flag_key}")
        pattern = f"{CACHE_PREFIX_EVAL}:{org_id}:{flag_key}:*"
        await cache_manager.delete_pattern(pattern)

    def _build_eval_cache_key(
        self,
        org_id: str,
        flag_key: str,
        context: FlagEvaluationContext,
    ) -> str:
        user_part = context.user_id or "anon"
        return f"{CACHE_PREFIX_EVAL}:{org_id}:{flag_key}:{user_part}"

    def _to_pydantic(self, orm: FeatureFlagORM) -> FeatureFlag:
        return FeatureFlag(
            flag_id=orm.flag_id,
            org_id=orm.org_id,
            key=orm.key,
            name=orm.name,
            description=orm.description,
            value_type=orm.value_type,
            default_value=orm.default_value,
            enabled_value=orm.enabled_value,
            enabled=orm.enabled,
            is_killswitch=orm.is_killswitch,
            status=FlagStatus(orm.status),
            rollout=PercentageRolloutConfig.model_validate(orm.rollout)
            if orm.rollout
            else PercentageRolloutConfig(),
            targeting=orm.targeting,
            tags=orm.tags or [],
            metadata=orm.metadata_dict or {},
            expires_at=orm.expires_at,
            version=orm.version,
            created_by=orm.created_by,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    def _override_to_pydantic(self, orm: FeatureFlagOverrideORM) -> FeatureFlagOverride:
        return FeatureFlagOverride(
            override_id=orm.override_id,
            flag_id=orm.flag_id,
            flag_key=orm.flag_key,
            org_id=orm.org_id,
            scope=OverrideScope(orm.scope),
            target_id=orm.target_id,
            value=orm.value,
            enabled=orm.enabled,
            reason=orm.reason,
            expires_at=orm.expires_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            created_by=orm.created_by,
        )

    def _changelog_to_pydantic(self, orm: FeatureFlagChangeLogORM) -> FlagChangeEvent:
        return FlagChangeEvent(
            event_id=orm.event_id,
            flag_id=orm.flag_id,
            flag_key=orm.flag_key,
            org_id=orm.org_id,
            event_type=orm.event_type,
            changed_by=orm.changed_by,
            previous_value=orm.previous_value,
            new_value=orm.new_value,
            timestamp=orm.timestamp,
            metadata=orm.metadata_dict or {},
        )


async def get_feature_flag_service(session: AsyncSession) -> FeatureFlagService:
    return FeatureFlagService(session)
