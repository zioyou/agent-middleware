# HITL Interrupt Bug Fix

## 문제 요약

Human-in-the-Loop (HITL) 워크플로우에서 `interrupt()` 발생 후 사용자가 "Approve"를 클릭하면 다음 오류가 발생:

```
HTTP 400: {"error":"bad_request","message":"Cannot resume: thread is not in interrupted state"}
```

## 근본 원인

### 1. Run Status 오류 (Critical Bug)

**파일**: `src/agent_server/api/runs.py` (Lines 1341-1364)

**문제**:
- Thread는 `human_approval` 노드에서 올바르게 중단됨 ✅
- 하지만 Run status가 `"interrupted"` 대신 `"completed"`로 잘못 설정됨 ❌
- Resume 시도 시 run이 이미 완료 상태라서 실패

**원인**:
```python
# 기존 코드 - 이벤트에서만 확인
if isinstance(event_data, dict) and "__interrupt__" in event_data:
    has_interrupt = True

# has_interrupt가 False로 유지되어 "completed"로 설정됨
```

**LangGraph 버그와의 관계**:
- LangGraph는 `interrupt()` 호출 시 `__interrupt__` 키를 이벤트에 추가해야 함
- 하지만 일부 환경(특히 Docker)에서 이 이벤트가 제대로 전달되지 않음
- GitHub 이슈 참조: [LangGraph issue #1395 - thread_state.interrupts missing in self-hosted Docker](https://github.com/langchain-ai/langgraph/issues/1395) 및 관련 커뮤니티 보고 사항

### 2. 부수적 문제들

**Rate Limiting** (HTTP 429):
- 기본 rate limiting 설정으로 인해 테스트 중 요청 차단
- 해결: `RATE_LIMIT_ENABLED=false` 설정

**Docker 볼륨 마운트**:
- `graphs/` 폴더가 read-only로 마운트되어 코드 변경 미반영
- 해결: 볼륨 마운트 제거하여 이미지 빌드 코드 사용

## 해결 방법

### 수정된 코드

**파일**: `src/agent_server/api/runs.py` (Lines 1352-1365)

```python
# 스트림 완료 후 스레드 상태를 확인하여 interrupt 여부 판단
# LangGraph의 interrupt()는 이벤트에 __interrupt__를 추가하지만,
# 더 확실한 방법은 스레드 상태의 'next' 필드를 확인하는 것
try:
    thread_state = await graph.aget_state(run_config)
    # 'next' 필드가 있으면 그래프가 중단되어 다음 노드를 기다리는 상태
    if thread_state and hasattr(thread_state, 'next') and thread_state.next:
        has_interrupt = True
        print(f"[execute_run_async] Detected interrupt via thread state: next={thread_state.next}")
except Exception as e:
    # thread state 확인 실패 시 기존 이벤트 기반 감지 결과 사용
    print(f"[execute_run_async] Failed to check thread state: {e}, using event-based detection")

if has_interrupt:
    await update_run_status(run_id, "interrupted", output=final_output or {}, session=session)
    # ...
```

**핵심 개선사항**:
1. ✅ 이벤트 기반 감지 유지 (`__interrupt__` 체크)
2. ✅ **Thread state 직접 확인 추가** (`thread.next` 확인)
3. ✅ 더블 체크로 견고성 향상
4. ✅ 에러 발생 시 기존 방식으로 폴백

### 추가 설정 변경

**파일**: `docker-compose.yml`

```yaml
environment:
  - RATE_LIMIT_ENABLED=false  # 테스트/개발 환경용

volumes:
  # - ./graphs:/app/graphs:ro  # 주석 처리: 이미지 빌드 코드 사용
```

## 테스트 방법

### 재현 단계

1. 새 대화 시작
2. "33 * 2 계산해줘" 입력
3. Calculator 도구 호출 시 인터럽트 발생 확인
4. "Approve" 버튼 클릭
5. ✅ 도구 실행 결과 반환 (수정 후)
   ❌ HTTP 400 오류 (수정 전)

### 검증 방법

```bash
# Thread 상태 확인
curl http://localhost:8002/threads/{thread_id}/history | jq '.[-1].next'
# 출력: ["human_approval"] → 중단됨

# Run 상태 확인
curl http://localhost:8002/threads/{thread_id}/runs | jq '.[0].status'
# 출력: "interrupted" (수정 후) ✅
# 출력: "completed" (수정 전) ❌
```

## Upstream 이슈

### 1. agent-middleware Repository

**이슈 제목**: "Fix run status detection for interrupted threads in HITL workflows"

**설명**:
Run status가 thread의 interrupt 상태를 정확히 반영하지 못하는 버그 수정. 이벤트 기반 감지(`__interrupt__`)에 더해 LangGraph thread state를 직접 확인하여 더 견고한 감지 구현.

**영향**:
- HITL 워크플로우에서 resume이 실패하는 문제 해결
- Docker 환경에서 interrupt 감지 신뢰성 향상

**제안 사항**:
- PR 제출 권장
- 다른 사용자들도 동일한 문제를 겪을 가능성 높음

### 2. LangGraph Repository

**이슈 제목**: "Interrupt events (`__interrupt__`) not properly detected in stream on Docker deployments"

**설명**:
LangGraph의 `interrupt()` 함수가 호출될 때 `__interrupt__` 키가 이벤트 스트림에 포함되어야 하지만, 일부 환경(특히 Docker)에서 이 이벤트가 제대로 전달되지 않음.

**재현**:
- Docker 환경에서 LangGraph 실행
- `interrupt()` 호출
- 이벤트 스트림에서 `__interrupt__` 누락 관찰

**임시 해결책**:
```python
# 이벤트 대신 thread state로 확인
thread_state = await graph.aget_state(config)
if thread_state.next:
    # 그래프가 중단됨
```

**근본 해결 필요**:
- LangGraph에서 모든 환경에서 `__interrupt__` 이벤트가 올바르게 전달되도록 보장
- 또는 thread state 확인을 공식 권장 방법으로 문서화

## 참고 자료

### LangGraph 문서
- [Interrupts - Official Docs](https://langchain.com/docs/langgraph/interrupts)
- [Human-in-the-Loop Guide](https://langchain.com/docs/langgraph/how-tos/human-in-the-loop)

### Agent Protocol
- [Runs API Specification](https://github.com/langchain-ai/agent-protocol)
- Thread States and Interrupts

### 관련 이슈
- LangGraph interrupt detection in self-hosted environments
- Thread state vs event-based interrupt detection

## 변경 이력

- **2026-01-09**: 초기 버그 수정 및 문서 작성
  - Thread state 확인 로직 추가
  - Rate limiting 비활성화
  - Docker 볼륨 설정 수정

## 라이선스 및 기여

이 수정은 agent-middleware 프로젝트의 라이선스를 따릅니다. Upstream 프로젝트에 PR로 기여하실 것을 권장합니다.
