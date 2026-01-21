# LLM 모델 상태 체크 원리

미들웨어 실행전 `model_health.py`를 호출하여 LLM 모델이 정상적으로 실행 중인지 확인합니다.

## 목표

에이전트 선택 화면 진입 전 `.env`의 `MODEL` 환경변수에 정의된 LLM 서버가 
정상 접속 가능한지 확인하여, 문제 시 사전에 안내합니다.

---

## 동작 흐름

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. 웹 UI 접속 (http://localhost:3000/?apiUrl=http://localhost:8002)          │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. Frontend: Stream.tsx                                                      │
│    - useEffect → checkModelHealth() 호출                                     │
│    - GET /model/health 요청                                                  │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. Backend: model_health.py                                                  │
│    - MODEL 환경변수 파싱 (provider/model_name)                                │
│    - get_chat_model() → 모델 인스턴스 생성                                    │
│    - 테스트 메시지 전송 ("ping") + 10초 타임아웃                               │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
            ┌───────────────────────┴───────────────────────┐
            ▼                                               ▼
┌───────────────────────────┐               ┌───────────────────────────────┐
│ 4a. 성공 (status: "ok")   │               │ 4b. 실패 (status: "error")    │
│     → 에이전트 선택 화면   │               │     → 모델 오류 화면          │
│                           │               │     [🔄 다시 확인]             │
└───────────────────────────┘               └───────────────────────────────┘
```

---

## 코드 호출 경로

### Frontend (agent-chat)

```
src/providers/Stream.tsx
├── StreamProvider 컴포넌트
│   ├── [STATE] modelHealth: { status, model, provider, message }
│   │
│   ├── checkModelHealth() 함수 (line 175-204)
│   │   └── fetch(`${finalApiUrl}/model/health`)
│   │
│   ├── [useEffect] 모델 상태 체크 트리거 (line 207-211)
│   │   └── checkModelHealth() 호출
│   │
│   ├── [UI] status === 'loading' → 로딩 스피너 (line 240-249)
│   │
│   ├── [UI] status === 'error' → 오류 화면 (line 252-303)
│   │   ├── 모델 정보 표시 (MODEL, Provider, 오류 메시지)
│   │   ├── [버튼] "🔄 다시 확인" → checkModelHealth()
│   │   └── [버튼] "⚙️ 서버 주소 변경" → setApiUrl(null)
│   │
│   └── [UI] status === 'ok' → 에이전트 선택 화면 (line 306~)
```

### Backend (agent-middleware)

```
src/agent_server/
├── main.py
│   ├── from .api.model_health import router as model_health_router (line 81)
│   └── app.include_router(model_health_router, prefix="/model", ...) (line 420)
│
└── api/model_health.py
    ├── parse_model_string(model_str) → (provider, model_name)
    │   └── "lmstudio/openai/gpt-oss-20b" → ("lmstudio", "openai/gpt-oss-20b")
    │
    └── check_model_health() [GET /model/health]
        ├── os.environ.get("MODEL") → 모델 문자열 가져오기
        ├── parse_model_string() → provider, model_name 추출
        ├── get_chat_model(provider, model_name) → 모델 인스턴스 생성
        │   └── src/ai_providers/__init__.py
        │       ├── provider == "lmstudio" → get_lmstudio_model()
        │       │   └── src/ai_providers/lmstudio.py
        │       │       └── ChatOpenAI(base_url=LMSTUDIO_BASE_URL, ...)
        │       └── 기타 → init_chat_model(model, model_provider=provider)
        │
        └── model.ainvoke([{"role": "user", "content": "ping"}])
            └── 타임아웃 10초 설정
```

---

## 환경변수

| 변수 | 예시 | 설명 |
|------|------|------|
| `MODEL` | `lmstudio/openai/gpt-oss-20b` | 사용할 모델 (provider/model_name 형식) |
| `LMSTUDIO_BASE_URL` | `http://host.docker.internal:1234/v1` | LM Studio 서버 URL |

---

## API 엔드포인트

### GET /model/health

**요청:**
```bash
curl http://localhost:8002/model/health
```

**응답 (성공):**
```json
{
  "status": "ok",
  "model": "lmstudio/openai/gpt-oss-20b",
  "provider": "lmstudio",
  "message": "Model is accessible"
}
```

**응답 (실패):**
```json
{
  "status": "error",
  "model": "lmstudio/openai/gpt-oss-20b",
  "provider": "lmstudio",
  "message": "Connection refused - 모델 서버가 실행 중인지 확인하세요"
}
```

---

## 지원 Provider

| Provider | 예시 MODEL 값 | 필요 환경변수 |
|----------|--------------|--------------|
| `lmstudio` | `lmstudio/openai/gpt-oss-20b` | `LMSTUDIO_BASE_URL` |
| `openai` | `openai/gpt-4o-mini` | `OPENAI_API_KEY` |
| `google_genai` | `google_genai/gemini-2.0-flash` | `GOOGLE_API_KEY` |
| `anthropic` | `anthropic/claude-3-5-sonnet` | `ANTHROPIC_API_KEY` |

---

## 유지보수 참고

### 새 Provider 추가 시

1. `src/ai_providers/__init__.py`의 `get_chat_model()` 함수 수정
2. 필요 시 `src/ai_providers/` 아래에 새 provider 파일 추가
3. `model_health.py`의 `parse_model_string()`은 수정 불필요 (자동 파싱)

### 타임아웃 조정

- `model_health.py` line 66: `timeout=10.0` 값 수정
