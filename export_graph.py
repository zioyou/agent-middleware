
import os
import sys

# 프로젝트 루트를 경로에 추가
sys.path.append(os.path.join(os.getcwd(), "src"))
sys.path.append(os.path.join(os.getcwd(), "graphs"))

try:
    from react_agent_hitl.graph import graph
    
    # 그래프 시각화 (Mermaid PNG)
    # pygraphviz가 없어도 LangGraph는 mermaid.ink 서비스를 통해 생성 시도합니다.
    mermaid_png = graph.get_graph().draw_mermaid_png()
    
    output_path = "zio_workflow_graph.png"
    with open(output_path, "wb") as f:
        f.write(mermaid_png)
    
    print(f"✅ Successfully saved workflow graph to {os.path.abspath(output_path)}")
except ImportError as e:
    print(f"❌ Import Error: {e}")
    print("패키지 경로를 확인해주세요. (graphs 폴더가 python path에 있어야 합니다)")
except Exception as e:
    print(f"❌ Error saving workflow graph: {e}")
    import traceback
    traceback.print_exc()
