from __future__ import annotations

import fnmatch
import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.cache import cache_manager
from ..core.orm import (
    RateLimitHistory as RateLimitHistoryORM,
)
from ..core.orm import (
    RateLimitRule as RateLimitRuleORM,
)
from ..models.rate_limit_rules import (
    RateLimitRule,
    RateLimitRuleCreate,
    RateLimitRuleListRequest,
    RateLimitRuleListResponse,
    RateLimitRuleMatch,
    RateLimitRuleUpdate,
    RateLimitStatus,
    RateLimitTarget,
)

logger = logging.getLogger(__name__)

CACHE_TTL_RULES = 300  # 5 minutes
CACHE_PREFIX_RULES = "rl_rules"


class RateLimitRuleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_rules(
        self,
        org_id: str,
        request: RateLimitRuleListRequest | None = None,
    ) -> RateLimitRuleListResponse:
        query = select(RateLimitRuleORM).where(RateLimitRuleORM.org_id == org_id)

        if request:
            if request.target_type is not None:
                query = query.where(RateLimitRuleORM.target_type == request.target_type.value)
            if request.target_id is not None:
                query = query.where(RateLimitRuleORM.target_id == request.target_id)
            if request.enabled is not None:
                query = query.where(RateLimitRuleORM.enabled == request.enabled)

        count_result = await self._session.execute(
            select(RateLimitRuleORM.rule_id).where(RateLimitRuleORM.org_id == org_id)
        )
        total = len(count_result.all())

        limit = request.limit if request else 20
        offset = request.offset if request else 0

        query = query.order_by(RateLimitRuleORM.priority.desc(), RateLimitRuleORM.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await self._session.execute(query)
        rules = [RateLimitRule.model_validate(row) for row in result.scalars().all()]

        return RateLimitRuleListResponse(
            rules=rules,
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_rule(
        self,
        org_id: str,
        rule_id: str,
    ) -> RateLimitRule | None:
        result = await self._session.execute(
            select(RateLimitRuleORM).where(
                RateLimitRuleORM.org_id == org_id,
                RateLimitRuleORM.rule_id == rule_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return RateLimitRule.model_validate(row)
        return None

    async def get_rule_by_name(
        self,
        org_id: str,
        name: str,
    ) -> RateLimitRule | None:
        result = await self._session.execute(
            select(RateLimitRuleORM).where(
                RateLimitRuleORM.org_id == org_id,
                RateLimitRuleORM.name == name,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            return RateLimitRule.model_validate(row)
        return None

    async def create_rule(
        self,
        org_id: str,
        request: RateLimitRuleCreate,
        created_by: str,
    ) -> RateLimitRule:
        existing = await self.get_rule_by_name(org_id, request.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Rate limit rule '{request.name}' already exists in organization",
            )

        now = datetime.now(UTC)
        rule_orm = RateLimitRuleORM(
            org_id=org_id,
            name=request.name,
            description=request.description,
            target_type=request.target_type.value,
            target_id=request.target_id,
            endpoint_pattern=request.endpoint_pattern,
            requests_per_window=request.requests_per_window,
            window_size=request.window_size.value,
            burst_limit=request.burst_limit,
            burst_window=request.burst_window.value if request.burst_window else None,
            action=request.action.value,
            priority=request.priority,
            enabled=request.enabled,
            status=RateLimitStatus.ACTIVE.value,
            expires_at=request.expires_at,
            metadata_dict=request.metadata,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )

        self._session.add(rule_orm)
        await self._session.commit()
        await self._session.refresh(rule_orm)

        await self._invalidate_rules_cache(org_id)
        return RateLimitRule.model_validate(rule_orm)

    async def update_rule(
        self,
        org_id: str,
        rule_id: str,
        request: RateLimitRuleUpdate,
        updated_by: str,
    ) -> RateLimitRule:
        result = await self._session.execute(
            select(RateLimitRuleORM).where(
                RateLimitRuleORM.org_id == org_id,
                RateLimitRuleORM.rule_id == rule_id,
            )
        )
        rule_orm = result.scalar_one_or_none()
        if not rule_orm:
            raise HTTPException(status_code=404, detail=f"Rate limit rule '{rule_id}' not found")

        update_data = request.model_dump(exclude_unset=True)
        if "window_size" in update_data and update_data["window_size"] is not None:
            update_data["window_size"] = update_data["window_size"].value
        if "burst_window" in update_data and update_data["burst_window"] is not None:
            update_data["burst_window"] = update_data["burst_window"].value
        if "action" in update_data and update_data["action"] is not None:
            update_data["action"] = update_data["action"].value

        for field, value in update_data.items():
            if hasattr(rule_orm, field):
                setattr(rule_orm, field, value)
            elif field == "metadata":
                rule_orm.metadata_dict = value

        rule_orm.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(rule_orm)

        await self._invalidate_rules_cache(org_id)
        return RateLimitRule.model_validate(rule_orm)

    async def delete_rule(
        self,
        org_id: str,
        rule_id: str,
    ) -> None:
        result = await self._session.execute(
            select(RateLimitRuleORM).where(
                RateLimitRuleORM.org_id == org_id,
                RateLimitRuleORM.rule_id == rule_id,
            )
        )
        rule_orm = result.scalar_one_or_none()
        if not rule_orm:
            raise HTTPException(status_code=404, detail=f"Rate limit rule '{rule_id}' not found")

        await self._session.delete(rule_orm)
        await self._session.commit()

        await self._invalidate_rules_cache(org_id)

    async def resolve_rule(
        self,
        org_id: str,
        endpoint: str,
        user_id: str | None = None,
        api_key_id: str | None = None,
    ) -> RateLimitRuleMatch | None:
        cache_key = f"{CACHE_PREFIX_RULES}:resolve:{org_id}:{endpoint}:{user_id or ''}:{api_key_id or ''}"
        cached = await cache_manager.get(cache_key)
        if cached:
            return RateLimitRuleMatch.model_validate(cached)

        rules = await self._get_active_rules(org_id)
        if not rules:
            return None

        matched_rule: RateLimitRule | None = None
        highest_priority = -1

        for rule in rules:
            if not self._rule_matches(rule, endpoint, user_id, api_key_id):
                continue

            if rule.priority > highest_priority:
                highest_priority = rule.priority
                matched_rule = rule

        if matched_rule is None:
            return None

        match_result = RateLimitRuleMatch.from_rule(matched_rule)
        await cache_manager.set(cache_key, match_result.model_dump(), ttl=CACHE_TTL_RULES)
        return match_result

    async def _get_active_rules(self, org_id: str) -> list[RateLimitRule]:
        cache_key = f"{CACHE_PREFIX_RULES}:active:{org_id}"
        cached = await cache_manager.get(cache_key)
        if cached:
            return [RateLimitRule.model_validate(r) for r in cached]

        now = datetime.now(UTC)
        result = await self._session.execute(
            select(RateLimitRuleORM)
            .where(
                and_(
                    RateLimitRuleORM.org_id == org_id,
                    RateLimitRuleORM.enabled == True,  # noqa: E712
                    or_(
                        RateLimitRuleORM.expires_at.is_(None),
                        RateLimitRuleORM.expires_at > now,
                    ),
                )
            )
            .order_by(RateLimitRuleORM.priority.desc())
        )
        rules = [RateLimitRule.model_validate(row) for row in result.scalars().all()]

        await cache_manager.set(cache_key, [r.model_dump() for r in rules], ttl=CACHE_TTL_RULES)
        return rules

    def _rule_matches(
        self,
        rule: RateLimitRule,
        endpoint: str,
        user_id: str | None,
        api_key_id: str | None,
    ) -> bool:
        if rule.target_type == RateLimitTarget.GLOBAL:
            return True

        if rule.target_type == RateLimitTarget.ORG:
            return True

        if rule.target_type == RateLimitTarget.USER:
            if user_id and rule.target_id == user_id:
                return True
            return False

        if rule.target_type == RateLimitTarget.API_KEY:
            if api_key_id and rule.target_id == api_key_id:
                return True
            return False

        if rule.target_type == RateLimitTarget.ENDPOINT:
            if rule.endpoint_pattern:
                return fnmatch.fnmatch(endpoint, rule.endpoint_pattern)
            return False

        return False

    async def _invalidate_rules_cache(self, org_id: str) -> None:
        await cache_manager.delete(f"{CACHE_PREFIX_RULES}:active:{org_id}")

    async def record_check(
        self,
        org_id: str,
        rule_id: str | None,
        rule_name: str | None,
        allowed: bool,
        current_count: int,
        limit_value: int,
        user_id: str | None = None,
        api_key_id: str | None = None,
        endpoint: str | None = None,
        action_taken: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        history_orm = RateLimitHistoryORM(
            org_id=org_id,
            rule_id=rule_id,
            rule_name=rule_name,
            timestamp=datetime.now(UTC),
            user_id=user_id,
            api_key_id=api_key_id,
            endpoint=endpoint,
            allowed=allowed,
            current_count=current_count,
            limit_value=limit_value,
            action_taken=action_taken,
            ip_address=ip_address,
        )
        self._session.add(history_orm)
        await self._session.commit()


async def get_rate_limit_rule_service(session: AsyncSession) -> RateLimitRuleService:
    return RateLimitRuleService(session)
