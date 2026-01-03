# Audit Logging

This document describes the audit logging implementation in Open LangGraph and
how to operate it in production. It covers the middleware capture path, outbox
reliability, partitioned storage, API endpoints, and operational guidance.

## Feature Overview

- Captures all HTTP requests (excluding health/docs/static) with user identity,
  org scoping, inferred action, and resource metadata.
- Infers `action`, `resource_type`, and `resource_id` from HTTP method and path
  using `src/agent_server/utils/audit_helpers.py`.
- Uses a transactional outbox table to make logging crash-safe.
- Moves outbox records to a partitioned `audit_logs` table in the background.
- Supports audit log search, aggregation, and export (CSV/JSON).
- Masks sensitive data before persistence to avoid leaking secrets.

## Architecture and Data Flow

```
HTTP request
  -> AuditMiddleware (capture + mask + infer action/resource)
  -> INSERT audit_logs_outbox (synchronous, timeout bounded)
  -> AuditOutboxService mover (batch)
     -> audit_logs partition (monthly RANGE on timestamp)
  -> API queries (GET /audit/logs, /audit/summary, POST /audit/export)
```

Core components:

- `src/agent_server/middleware/audit.py`
  - Captures request metadata and optional request body.
  - Infers `action`, `resource_type`, `resource_id` with special cases for
    stream/cancel/run/search/history paths.
  - Logs streaming completions and client disconnects (status `499`).
- `src/agent_server/services/audit_outbox_service.py`
  - Inserts payloads into `audit_logs_outbox`.
  - Background mover drains outbox into `audit_logs` using savepoints.
  - Auto-creates missing partitions when inserts fail.
- `src/agent_server/services/partition_service.py`
  - Creates future partitions (default 3 months).
  - Optionally drops old partitions (default 90 days retention).
- `src/agent_server/api/audit.py`
  - Query, summarize, and export audit logs with org scoping and RBAC.

Database tables:

- `audit_logs_outbox`: crash-safe staging table (JSONB payload).
- `audit_logs`: partitioned by month on `timestamp` with indexes for org/user.

## Configuration Options

There are no environment-driven audit settings yet; tuning is done via module
constants. Changes require a code update and deploy.

### Middleware (`src/agent_server/middleware/audit.py`)

- `EXCLUDED_PATHS`: exact paths skipped from audit logging.
- `EXCLUDED_PREFIXES`: static path prefixes skipped.
- `MAX_BODY_SIZE`: maximum captured request body size (bytes, default 10_000).
- `INSERT_TIMEOUT_SECONDS`: timeout around outbox insert (default 1.0s).

Behavior defaults:

- Request body capture only for `POST`, `PUT`, `PATCH`.
- Non-JSON payloads are stored as `{ "_binary": true, "_size": <bytes> }`.
- Oversize payloads store `{ "_truncated": true, "_size": <bytes> }`.

### Outbox mover (`src/agent_server/services/audit_outbox_service.py`)

- `BATCH_SIZE`: records per batch (default 500).
- `MOVE_INTERVAL_SECONDS`: sleep between drain cycles (default 10s).
- `INSERT_TIMEOUT_SECONDS`: DB insert timeout for outbox insert (default 1.0s).
- `FLUSH_TIMEOUT_SECONDS`: shutdown flush timeout (default 5.0s).
- `MAX_RETRY_COUNT`: poison-pill retry limit (default 3).
- `MAX_RETRY_CACHE_SIZE`: retry cache bound (default 1000).

### Partition management (`src/agent_server/services/partition_service.py`)

- `DEFAULT_MONTHS_AHEAD`: pre-create partitions (default 3).
- `DEFAULT_RETENTION_DAYS`: cleanup cutoff (default 90).

### Sensitive data masking (`src/agent_server/utils/masking.py`)

- `SENSITIVE_PATTERNS`: key substrings that trigger masking.
- `ALLOWED_FIELDS`: keys explicitly allowed to remain unmasked.
- `MAX_DEPTH`: maximum recursion depth (default 10).
- `MAX_STRING_LENGTH`: string truncation limit (default 1000).
- `MAX_LIST_ITEMS`: list size limit (default 100).
- `MASK_VALUE`: replacement value (default `***REDACTED***`).
- `TRUNCATED_SUFFIX`: appended to truncated strings.

### API defaults (`src/agent_server/api/audit.py`)

- `start_time`/`end_time`: default to last 7 days if omitted.
- `limit`: default 100, max 1000.
- `offset`: default 0.

## API Reference

All endpoints require authentication. `org_id` is mandatory for multi-tenant
isolation and is derived from the authenticated user.

### GET /audit/logs

Role: `admin` or `owner`

Query params:

- `user_id`: filter by user.
- `action`: one of `CREATE`, `READ`, `UPDATE`, `DELETE`, `LIST`, `SEARCH`, `RUN`,
  `STREAM`, `CANCEL`, `COPY`, `HISTORY`, `UNKNOWN`.
- `resource_type`: `assistant`, `thread`, `run`, `store`, `organization`,
  `api_key`, `agent`, `audit`, `unknown`.
- `resource_id`: filter by resource ID.
- `start_time`: ISO timestamp (default: now - 7 days).
- `end_time`: ISO timestamp (default: now).
- `status_code`: exact match.
- `status_code_gte`: lower bound (>=).
- `status_code_lte`: upper bound (<=).
- `is_streaming`: `true` or `false`.
- `limit`: 1-1000 (default 100).
- `offset`: >= 0 (default 0).

Response: `AuditLogListResponse`

```json
{
  "entries": [ /* AuditEntry[] */ ],
  "total": 42,
  "limit": 100,
  "offset": 0,
  "has_more": false
}
```

Example:

```bash
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/audit/logs?resource_type=run&start_time=2024-01-01T00:00:00Z"
```

### GET /audit/summary

Role: `admin` or `owner`

Query params:

- `group_by`: `action`, `resource_type`, `user_id`, `day` (required).
- `start_time`: ISO timestamp (default: now - 7 days).
- `end_time`: ISO timestamp (default: now).

Response: `AuditSummaryResponse`

```json
{
  "group_by": "action",
  "items": [
    { "key": "RUN", "count": 18, "earliest": "...", "latest": "..." }
  ],
  "total_count": 42,
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-08T00:00:00Z"
}
```

### POST /audit/export

Role: `owner`

Body: `AuditExportRequest`

```json
{
  "format": "csv",
  "start_time": "2024-01-01T00:00:00Z",
  "end_time": "2024-01-08T00:00:00Z",
  "filters": {
    "user_id": "user-123",
    "action": "RUN",
    "resource_type": "run",
    "resource_id": "run-uuid",
    "status_code": 200,
    "is_streaming": true
  }
}
```

Response:

- Streaming download with `Content-Disposition` filename.
- CSV includes a fixed column subset:
  `id,timestamp,user_id,org_id,action,resource_type,resource_id,http_method,
   path,status_code,duration_ms,ip_address,is_streaming,error_message`
- JSON streams full `AuditEntry` records.

Example:

```bash
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"format":"json"}' \
  -o audit.json \
  http://localhost:8000/audit/export
```

## Sensitive Data Masking

Masking runs before persistence and applies only to captured request bodies.

Capture rules:

- Only `POST`, `PUT`, `PATCH` bodies are captured.
- Body limit: 10KB; oversize payloads record truncation metadata.
- Non-JSON bodies are not stored, only size metadata.
- Responses are not captured; for streaming responses the log includes a
  `response_summary` with `bytes_sent`.

Masking rules (`src/agent_server/utils/masking.py`):

- Keys containing any `SENSITIVE_PATTERNS` substring are replaced with
  `***REDACTED***` (case-insensitive).
- Keys in `ALLOWED_FIELDS` are never masked.
- Max recursion depth: 10 levels, then `{ "_depth_exceeded": true }`.
- Circular references yield `{ "_circular_reference": true }`.
- Long strings are truncated; long lists are capped with a truncation marker.

Exception safety:

- Exception messages are sanitized before logging.
- Messages are truncated to 500 characters and redact quoted strings, long hex
  tokens, and base64-like sequences.

Other privacy protections:

- `User-Agent` is truncated to 500 characters.
- Client IP is taken from the last IP in `X-Forwarded-For`, falling back to
  the direct client address.

## Partition Management

The `audit_logs` table is partitioned by month (PostgreSQL RANGE on `timestamp`)
to keep queries fast and maintenance manageable.

Partition behavior:

- Startup creates partitions for current month + next 3 months:
  `partition_service.ensure_future_partitions(months_ahead=3)`
  in `src/agent_server/main.py`.
- Missing partitions are created on demand if an insert fails.
- Optional cleanup drops partitions older than a retention cutoff.

Partition naming:

- `audit_logs_yYYYYmMM` (e.g., `audit_logs_y2026m01`)

Operational tips:

- Schedule `partition_service.cleanup_old_partitions()` if you want automatic
  retention enforcement. It is not run automatically by default.
- Use `partition_service.get_partition_stats()` for approximate row counts.

## Performance Tuning

1) Keep time ranges tight
   - Always pass `start_time`/`end_time` to prune partitions.
   - Defaults are 7 days to encourage efficient scans.

2) Tune the outbox mover
   - Increase `BATCH_SIZE` for fewer transactions at higher memory cost.
   - Reduce `MOVE_INTERVAL_SECONDS` to drain outbox faster under heavy load.

3) Reduce capture cost when needed
   - Lower `MAX_BODY_SIZE` to reduce JSON parsing overhead.
   - Adjust `MAX_DEPTH`, `MAX_LIST_ITEMS`, `MAX_STRING_LENGTH` for large payloads.

4) Watch index usage
   - Primary query path is `(org_id, timestamp)`; keep this index intact.
   - Add targeted indexes if you introduce new heavy filters.

5) Export sizing
   - For very large exports, consider narrowing filters or time windows to avoid
     long-lived streaming connections.

## Troubleshooting

### Missing audit logs

- Verify `AuditMiddleware` is enabled in `src/agent_server/main.py`.
- Ensure `AuthenticationMiddleware` runs before `AuditMiddleware`, otherwise
  user identity may show as `anonymous`.
- Check `audit_logs_outbox` for unprocessed rows.
- Confirm `audit_outbox_service.start_mover()` runs at startup.
- Look for timeout warnings: "Audit insert timed out".

### Outbox grows but audit_logs is empty

- Mover may not be running or is failing.
- Check logs for "Batch move failed" or "Error in audit mover loop".
- Inspect partition creation errors or DB permissions for `CREATE TABLE`.

### Partition errors

- Errors like "no partition of relation audit_logs found" indicate missing
  partitions. Run `partition_service.ensure_future_partitions()` or allow the
  mover to auto-create via `create_partition_for_date()`.

### Access denied (403)

- "Organization membership required" means the user has no `org_id`.
- "ADMIN role required" or "OWNER role required" indicates missing permissions.

### Export returns empty or partial data

- Check time range defaults; they only cover the last 7 days if omitted.
- Validate filters (resource_type/action strings must match enum values).
- CSV output is a subset of fields; use JSON for full payloads.

### Streaming requests show status 499

- This indicates a client-initiated disconnect during SSE.
- It is expected for interrupted streams and is recorded for completeness.
