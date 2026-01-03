# Rate Limiting Guide

This document describes the rate limiting system in Open LangGraph, including configuration, endpoint-specific limits, and organization quota management.

## Overview

Open LangGraph uses a Redis-based rate limiting system with the following features:

- **Global rate limiting**: Applied via middleware to all API requests
- **Endpoint-specific limits**: Different limits for streaming, runs, and general operations
- **Organization quotas**: Per-organization usage tracking and limits
- **Graceful degradation**: System continues working when Redis is unavailable

## Architecture

```
Request → Rate Limit Middleware → Endpoint-Specific Check → Route Handler
                ↓
         Organization Quota Check (Redis)
                ↓
         429 Too Many Requests (if exceeded)
```

### Rate Limit Buckets

The system uses separate buckets for different operation types, allowing users to have independent limits for each:

| Bucket Type | Default Limit (Auth) | Default Limit (Anon) | Use Case |
|------------|---------------------|---------------------|----------|
| `streaming` | 100/hour | 20/hour | POST /runs/stream, /runs/wait |
| `runs` | 500/hour | 100/hour | POST /runs, /threads/*/runs |
| `write` | 2000/hour | 400/hour | POST/PUT/DELETE operations |
| `read` | 5000/hour | 1000/hour | GET requests |

**Note**: Each bucket is independent. A user can make 100 streaming requests + 500 run creations + 2000 other writes + 5000 reads within an hour.

## Configuration

### Environment Variables

```bash
# Enable/disable rate limiting (default: true)
RATE_LIMIT_ENABLED=true

# Redis storage (required for distributed rate limiting)
RATE_LIMIT_STORAGE=redis

# Default limits per hour
RATE_LIMIT_DEFAULT_PER_HOUR=5000      # Authenticated users (general)
RATE_LIMIT_ANON_PER_HOUR=1000         # Anonymous/unauthenticated users
RATE_LIMIT_STREAMING_PER_HOUR=100     # Streaming endpoints
RATE_LIMIT_RUNS_PER_HOUR=500          # Run creation endpoints

# Fallback behavior when Redis unavailable
# skip = disable rate limiting (fail-open)
# error = reject requests (fail-closed)
RATE_LIMIT_FALLBACK=skip

# Rate limit strategy
RATE_LIMIT_STRATEGY=moving-window
```

### Redis Configuration

Rate limiting requires Redis. Configure via:

```bash
REDIS_URL=redis://localhost:6379/0
```

If Redis is unavailable:
- With `RATE_LIMIT_FALLBACK=skip`: All requests allowed (default)
- With `RATE_LIMIT_FALLBACK=error`: Requests rejected with 503

## Response Headers

All responses include rate limit information:

```http
X-RateLimit-Limit: 5000
X-RateLimit-Remaining: 4999
X-RateLimit-Reset: 1704326400
```

### 429 Response

When rate limit exceeded:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json
Retry-After: 3600
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1704326400

{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please slow down.",
  "retry_after": 3600,
  "details": {
    "limit": 100,
    "remaining": 0,
    "reset_at": 1704326400
  }
}
```

## Organization Quotas

Organizations can have custom rate limits stored in `organization.settings`:

```json
{
  "rate_limits": {
    "requests_per_hour": 10000,
    "runs_per_hour": 1000,
    "streaming_per_hour": 200,
    "enabled": true
  },
  "quotas": {
    "max_threads": 10000,
    "max_assistants": 100,
    "max_runs_per_day": 5000
  }
}
```

### API Endpoints

#### Get Organization Quotas
```http
GET /organizations/{org_id}/quotas
Authorization: Bearer <token>
```

Response:
```json
{
  "org_id": "org-123",
  "rate_limits": {
    "requests_per_hour": 10000,
    "runs_per_hour": 1000,
    "streaming_per_hour": 200,
    "enabled": true
  },
  "quotas": {
    "max_threads": 10000,
    "max_assistants": 100,
    "max_runs_per_day": 5000
  },
  "usage": {
    "requests": {
      "current_usage": 500,
      "limit": 10000,
      "reset_at": 1704326400
    },
    "runs": {
      "current_usage": 50,
      "limit": 1000,
      "reset_at": 1704326400
    },
    "streaming": {
      "current_usage": 10,
      "limit": 200,
      "reset_at": 1704326400
    }
  }
}
```

#### Get Usage Only
```http
GET /organizations/{org_id}/quotas/usage
Authorization: Bearer <token>
```

#### Update Rate Limits (Admin only)
```http
PUT /organizations/{org_id}/quotas/limits
Authorization: Bearer <token>
Content-Type: application/json

{
  "requests_per_hour": 20000,
  "runs_per_hour": 2000,
  "streaming_per_hour": 400
}
```

## Key Extraction

Rate limit keys are extracted in the following priority:

1. **Organization ID** (preferred): `org:{org_id}` - All users in the same org share limits
2. **User ID**: `user:{user_id}` - Individual user limits when no org
3. **IP Address**: `ip:{ip_address}` - For unauthenticated requests

### Key Format Examples

```
# Authenticated user with organization
read:org:org-123
streaming:org:org-123
runs:org:org-123

# Authenticated user without organization
read:user:user-456
streaming:user:user-456

# Unauthenticated request
read:ip:192.168.1.100
```

## Excluded Paths

The following paths are excluded from rate limiting:

- `/health` - Health check endpoint
- `/docs` - Swagger UI
- `/redoc` - ReDoc documentation
- `/openapi.json` - OpenAPI schema
- `/metrics` - Prometheus metrics
- `/static/*` - Static assets
- `/_next/*` - Next.js assets

## Best Practices

### For API Consumers

1. **Check headers**: Always check `X-RateLimit-Remaining` before making requests
2. **Implement backoff**: When receiving 429, wait for `Retry-After` seconds
3. **Batch operations**: Combine multiple operations where possible
4. **Use streaming wisely**: Streaming endpoints have stricter limits

### For Administrators

1. **Monitor Redis**: Rate limiting depends on Redis availability
2. **Set appropriate limits**: Balance between protection and usability
3. **Configure fallback**: Choose `skip` for availability or `error` for protection
4. **Review logs**: Check for rate limit exceeded events

## Troubleshooting

### Rate limiting not working

1. Check if Redis is available: `redis-cli ping`
2. Verify `RATE_LIMIT_ENABLED=true`
3. Check logs for "Rate limiter initialized with Redis backend"

### All requests returning 429

1. Check current usage with quota API
2. Verify organization limits are configured correctly
3. Check if `RATE_LIMIT_FALLBACK=error` with Redis unavailable

### Inconsistent rate limiting in distributed setup

1. Ensure all instances connect to the same Redis
2. Verify `RATE_LIMIT_STORAGE=redis`
3. Check for clock synchronization issues

## Related Documentation

- [Architecture Overview](./architecture.md)
- [Audit Logging](./audit-logging.md)
- [API Reference](./api-reference.md)
