# Human-in-the-Loop (HITL) 구현 가이드

> **agent-middleware / agent_ontology** 기준으로 작성된 문서입니다.

---

## 개요

HITL은 AI 에이전트가 **민감하거나 부작용이 큰 도구(tool)를 실행하기 전에 사람의 승인을 받는** 흐름입니다.

우리 시스템에서는 `call_subagent` 도구가 외부 서브 에이전트를 호출할 때 HITL을 적용합니다.

---

## 핵심 원칙

> **`interrupt()`는 도구 함수 내부에서 호출합니다.**

별도의 "승인 노드"를 그래프 중간에 끼우는 방식 **(❌ 잘못된 방식)** 이 아니라, 도구 함수 자체가 실행 도중 멈추고 재개되는 방식 **(✅ 올바른 방식)** 을 사용합니다.

---

## 전체 흐름

```
1. Worker LLM → call_subagent 도구 호출 계획 (AIMessage 생성)
2. worker_tools 노드 → call_subagent 함수 실행 시작
3. call_subagent 내부 → interrupt() 호출 → 그래프 정지 (체크포인트 저장)
4. 서버 → thread.status = "interrupted", 프론트엔드에 승인 UI 표시
5. 사용자 → [승인] 또는 [거부] 클릭
6. 프론트엔드 → Command(resume={decisions: [{type: "approve"}]}) 전송
7. LangGraph → call_subagent 함수 재개 (interrupt()가 결정값 반환)
8. call_subagent → 실제 외부 API 호출 → 결과 반환 (ToolMessage)
9. worker_tools → worker LLM → 결과를 보고 최종 응답 생성
10. 실행 완료 → thread.status = "idle"
```

---

## 코드 구현

### 1. 도구 함수 내 `interrupt()` (tools.py)

```python
from langgraph.types import interrupt

@tool
async def call_subagent(agent_id, task_description, config, state, input_data={}):
    # ① 실행 전 사용자 승인 요청
    human_decision = interrupt({
        "action_requests": [{
            "name": "call_subagent",
            "args": {"agent_id": agent_id, "task_description": task_description},
            "description": f"서브 에이전트 '{agent_id}'를 호출하려고 합니다.",
        }],
        "review_configs": [{
            "action_name": "call_subagent",
            "allowed_decisions": ["approve", "reject"],
        }],
    })

    # ② 거부 처리
    decisions = human_decision.get("decisions", [])
    if decisions and decisions[0].get("type") == "reject":
        return {"status": "rejected", "message": decisions[0].get("message")}

    # ③ 승인 시 실제 실행
    result = await call_external_api(...)
    return result
```

**동작 원리:**
- `interrupt()` 호출 시 LangGraph는 현재 상태를 체크포인트에 저장하고 일시정지
- 재개(resume) 시 함수를 **처음부터 다시 실행**하여 `interrupt()`가 결정값을 반환
- LLM은 하나의 AIMessage + 하나의 ToolMessage만 보게 되어 중복 호출 없음

---

### 2. 그래프 구조 (graph.py)

```python
# ✅ 올바른 구조 - 별도 승인 노드 없음
builder.add_node("worker",       worker_node)
builder.add_node("worker_tools", ToolNode(WORKER_TOOLS_EXEC))

# worker가 tool_call을 생성하면 → worker_tools 실행
# interrupt()는 worker_tools 내부(call_subagent)에서 발생
builder.add_conditional_edges("worker", route_worker_output, {
    "worker_tools":   "worker_tools",
    "task_completer": "task_completer",
})
builder.add_edge("worker_tools", "worker")  # 단순 엣지
```

**과거 잘못된 구조 (❌):**
```
worker → human_approval 노드 → worker_tools → worker → 또 호출!
```
→ LLM이 tool 결과 없이 한 번 더 실행되어 `call_subagent`가 2번 호출됨

---

### 3. 서버의 interrupt 감지 (runs.py)

`execute_run_async` 함수에서 실행 완료 후 interrupt 상태를 판단합니다.

```python
# interrupt()가 ToolNode 내부에서 발생하면 스트림에 __interrupt__ 이벤트가 
# 나오지 않을 수 있으므로, aget_state()로 보조 확인
is_resume_run = (command is not None and command.get("resume") is not None)

if not has_interrupt and not is_resume_run:
    # 일반(새) run: aget_state().tasks 로 live interrupt 감지
    thread_state = await graph.aget_state(run_config)
    has_live_interrupt = any(task.interrupts for task in thread_state.tasks)
    if has_live_interrupt:
        has_interrupt = True

elif is_resume_run and not has_interrupt:
    # resume run: aget_state() 사용 금지!
    # → 승인 전 interrupt 체크포인트를 계속 가리키므로 오탐 발생
    # → 스트림 이벤트만 신뢰 (새 interrupt 없으면 완료 처리)
    pass

# thread 상태 업데이트
if has_interrupt:
    await set_thread_status(session, thread_id, "interrupted")
else:
    await set_thread_status(session, thread_id, "idle")
```

**핵심 주의사항:**

| 상황 | `aget_state().tasks` | 올바른 판단 |
|------|---------------------|------------|
| 새 run, interrupt 발생 | interrupts 있음 | ✅ interrupted |
| resume run, 실행 완료 | **interrupts 있음** (이전 체크포인트!) | ⚠️ 오탐 → idle로 처리해야 함 |
| 새 run, 정상 완료 | interrupts 없음 | ✅ idle |

→ 따라서 **resume run에서는 `aget_state()`를 사용하지 않습니다.**

---

## 두 가지 에러 패턴과 원인

### ❌ Error 1: 승인 후 `call_subagent`가 2번 호출됨

**원인:** 그래프에 `human_approval` 노드를 별도로 만들었을 때 발생
```
worker(LLM) → human_approval → worker_tools → worker(LLM)
                                               ↑ 도구 결과가 없어 또 호출
```

**해결:** `interrupt()`를 도구 함수 내부로 이동

---

### ❌ Error 2: `HTTP 409` - Thread is currently interrupted

**원인:** resume 완료 후 `aget_state().tasks.interrupts`가 이전 체크포인트를 가리켜 thread가 `interrupted`로 남음

**해결:** resume run에서는 `aget_state()` 체크 생략

---

## 프론트엔드 요청 형식

### 승인 시
```json
POST /threads/{thread_id}/runs/stream
{
  "command": {
    "resume": {
      "decisions": [{"type": "approve"}]
    }
  },
  "checkpoint": {
    "checkpoint_id": "...",
    "checkpoint_ns": ""
  }
}
```

### 거부 시
```json
{
  "command": {
    "resume": {
      "decisions": [{"type": "reject", "message": "거부 사유"}]
    }
  }
}
```

---

## 참고

- [DeepAgents HITL 공식 문서](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
- LangGraph `interrupt()` 공식 패턴: *"Interrupts within tool calls"*
