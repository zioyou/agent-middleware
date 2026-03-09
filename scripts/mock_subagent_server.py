import asyncio
import json
import logging
from fastapi import FastAPI, BackgroundTasks, Request
import httpx
import uvicorn

app = FastAPI(title="Mock Subagent Server")
logger = logging.getLogger("mock_server")
logging.basicConfig(level=logging.INFO)

async def process_and_callback(webhook_url: str, query: str):
    """
    10초간 대기하며 무거운 처리(검색)를 하는 척 한 뒤,
    전달받은 webhook_url 로 콜백 전송
    """
    logger.info(f"Starting fake work for query: '{query}'")
    logger.info("Sleeping for 10 seconds to simulate subagent processing...")
    
    await asyncio.sleep(10)
    
    fake_result = {
        "run_id": "fake_mock_run_999",
        "thread_id": "does_not_matter_here", # Webhook URL contains the true thread_id in query param
        "status": "completed",
        "output": {
            "message": f"Successfully searched for '{query}'",
            "data": [
                {"doc_id": 1, "content": "Mock document 1 about " + query},
                {"doc_id": 2, "content": "Mock document 2 about " + query}
            ]
        }
    }
    
    logger.info(f"Work finished. Sending callback to {webhook_url}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(webhook_url, json=fake_result)
            logger.info(f"Callback sent. Response status: {response.status_code}")
        except Exception as e:
            logger.error(f"Failed to send callback to {webhook_url}: {e}")

@app.post("/runs")
async def create_mock_run(request: Request, background_tasks: BackgroundTasks):
    """
    Agent Protocol의 POST /runs 형태를 흉내냅니다.
    """
    body = await request.json()
    webhook_url = body.get("webhook")
    input_data = body.get("input", {})
    query = input_data.get("query", "Default query")
    
    if not webhook_url:
        logger.warning("No webhook URL provided in the request payload.")
        return {"status": "failed", "error": "webhook URL is missing"}
        
    logger.info(f"Received request with webhook: {webhook_url}")
    
    # 즉시 200 반환 후 백그라운드 워커 시작
    background_tasks.add_task(process_and_callback, webhook_url, query)
    
    return {
        "run_id": "fake_mock_run_999",
        "status": "pending",
        "message": "Mock Subagent started your task."
    }

if __name__ == "__main__":
    logger.info("Starting Mock Subagent Server on port 8001...")
    uvicorn.run(app, host="0.0.0.0", port=8001)
