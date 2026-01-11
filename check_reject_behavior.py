import asyncio
import os
from langgraph_sdk import get_client

async def test_reject_status():
    client = get_client(url="http://localhost:8002")
    assistant = await client.assistants.create(graph_id="agent_hitl", if_exists="do_nothing")
    thread = await client.threads.create()
    
    print(f"Thread ID: {thread['thread_id']}")
    
    # 1. 실행 시작
    run = await client.runs.create(
        thread_id=thread['thread_id'],
        assistant_id=assistant['assistant_id'],
        input={"messages": [{"role": "user", "content": "33 * 2 계산해줘"}]}
    )
    
    # 2. 인터럽트 대기
    print("Waiting for interrupt...")
    import time
    start_time = time.time()
    while time.time() - start_time < 20:
        await asyncio.sleep(1)
        r = await client.runs.get(thread['thread_id'], run['run_id'])
        if r['status'] == 'interrupted':
            print("Interrupted!")
            break
    
    # 3. 거절 전송
    print("Sending REJECT...")
    await client.runs.create(
        thread['thread_id'],
        assistant_id=assistant['assistant_id'],
        command={"resume": [{"type": "reject"}]}
    )
    
    # 4. 완료 상태 확인
    print("Waiting for completion...")
    while True:
        await asyncio.sleep(1)
        r = await client.runs.get(thread['thread_id'], run['run_id'])
        if r['status'] in ('completed', 'failed', 'error', 'cancelled'):
            print(f"Final Status: {r['status']}")
            break
            
    # 5. 히스토리 확인
    history = await client.threads.get_history(thread['thread_id'])
    messages = history[0]['values'].get('messages', [])
    print("\n--- Message History ---")
    for m in messages:
        print(f"[{m.get('type')}] {m.get('content')[:50]}...")

if __name__ == "__main__":
    asyncio.run(test_reject_status())
