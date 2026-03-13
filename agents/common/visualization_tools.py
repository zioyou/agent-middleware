import os
import json
import uuid
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import numpy as np
import networkx as nx
from typing import Union, List, Dict, Any, Optional
from langchain_core.tools import tool

# Set non-interactive backend for server environment
matplotlib.use('Agg')

# Constants
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Upload Directory
if os.path.exists("/app/uploads") and os.access("/app/uploads", os.W_OK):
    UPLOAD_DIR = "/app/uploads"
else:
    UPLOAD_DIR = "/tmp/agent_uploads"
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR, exist_ok=True)

# Font Setup
FONT_DIR = os.path.join(CURRENT_DIR, "fonts")
FONT_PATH = os.path.join(FONT_DIR, "NanumGothic.ttf")

REGISTERED_FONT_NAME = "DejaVu Sans"  # fallback
try:
    if os.path.exists(FONT_PATH):
        fm.fontManager.addfont(FONT_PATH)
        font_prop = fm.FontProperties(fname=FONT_PATH)
        REGISTERED_FONT_NAME = font_prop.get_name()
        plt.rcParams['font.family'] = REGISTERED_FONT_NAME
        plt.rcParams['axes.unicode_minus'] = False
        print(f"Loaded and registered font: {REGISTERED_FONT_NAME}")
    else:
        print(f"Font not found at {FONT_PATH}. Using default font.")
except Exception as e:
    print(f"Failed to load custom font: {e}")

# Modern Color Palettes
PALETTES = {
    "blue":    ["#4C9BE8", "#5DADE2", "#85C1E9", "#AED6F1", "#D6EAF8"],
    "green":   ["#27AE60", "#2ECC71", "#58D68D", "#82E0AA", "#A9DFBF"],
    "purple":  ["#8E44AD", "#9B59B6", "#AF7AC5", "#C39BD3", "#D7BDE2"],
    "orange":  ["#E67E22", "#F39C12", "#F5B041", "#F8C471", "#FAD7A0"],
    "mixed":   ["#4C9BE8", "#27AE60", "#E67E22", "#8E44AD", "#E74C3C",
                "#16A085", "#D4AC0D", "#CB4335", "#1F618D", "#1E8449"],
}


def _apply_modern_style(fig, ax, bg_color="#1a1a2e", grid_color="#2d2d4e"):
    """모던 다크 테마 스타일 적용"""
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    ax.spines['bottom'].set_color('#4a4a6a')
    ax.spines['left'].set_color('#4a4a6a')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.tick_params(colors='#c8c8d8', labelsize=10)
    ax.xaxis.label.set_color('#c8c8d8')
    ax.yaxis.label.set_color('#c8c8d8')
    ax.grid(True, linestyle='--', alpha=0.25, color=grid_color, zorder=0)


@tool
async def create_graph(
    data: Union[str, List[Dict[str, Any]]],
    x_col: str,
    y_col: str,
    plot_type: str = "bar",
    title: str = "그래프",
    x_label: Optional[str] = None,
    y_label: Optional[str] = None,
    color_palette: str = "mixed",
) -> Dict[str, Any]:
    """
    데이터를 시각화하여 그래프 이미지를 생성합니다.

    Args:
        data: CSV/Excel/JSON 파일 경로 또는 딕셔너리 리스트 (예: [{"날짜": "월", "건수": 5}]).
        x_col: X축으로 사용할 컬럼 이름.
        y_col: Y축으로 사용할 컬럼 이름.
        plot_type: 차트 종류 - 'bar'(막대), 'line'(선), 'scatter'(산점도), 'pie'(파이). 기본값 'bar'.
        title: 그래프 제목 (한국어 권장).
        x_label: X축 레이블 (생략 시 x_col 사용).
        y_label: Y축 레이블 (생략 시 y_col 사용).
        color_palette: 색상 팔레트 ('blue', 'green', 'purple', 'orange', 'mixed'). 기본값 'mixed'.

    Returns:
        dict: image_url, file_path, markdown 포함.
    """
    try:
        # 1. 데이터 로드
        df = None
        if isinstance(data, str):
            if not os.path.exists(data):
                return {"error": f"파일을 찾을 수 없습니다: {data}"}
            ext = os.path.splitext(data)[1].lower()
            if ext == '.csv':
                df = pd.read_csv(data)
            elif ext in ['.xls', '.xlsx']:
                df = pd.read_excel(data)
            elif ext == '.json':
                with open(data, 'r', encoding='utf-8') as f:
                    data_json = json.load(f)
                df = pd.DataFrame(data_json) if isinstance(data_json, list) else None
            if df is None:
                return {"error": f"지원하지 않는 형식: {ext}"}
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        else:
            return {"error": "data는 파일 경로 또는 딕셔너리 리스트여야 합니다."}

        if df is None or df.empty:
            return {"error": "데이터가 비어 있습니다."}
        if x_col not in df.columns:
            return {"error": f"컬럼 '{x_col}' 없음. 사용 가능: {list(df.columns)}"}
        if plot_type != 'pie' and y_col not in df.columns:
            return {"error": f"컬럼 '{y_col}' 없음. 사용 가능: {list(df.columns)}"}

        # 2. 색상 팔레트
        colors = PALETTES.get(color_palette, PALETTES["mixed"])

        # 3. 그래프 생성
        fig, ax = plt.subplots(figsize=(11, 6))
        _apply_modern_style(fig, ax)

        n = len(df)
        bar_colors = [colors[i % len(colors)] for i in range(n)]

        if plot_type == 'bar':
            bars = ax.bar(df[x_col], df[y_col], color=bar_colors,
                          edgecolor='none', zorder=3, width=0.6)
            # 값 라벨
            for bar in bars:
                h = bar.get_height()
                ax.text(bar.get_x() + bar.get_width() / 2, h + 0.05,
                        f'{h:,.0f}', ha='center', va='bottom',
                        color='#e0e0f0', fontsize=9)

        elif plot_type == 'line':
            ax.plot(df[x_col], df[y_col], color=colors[0],
                    marker='o', markersize=7, linewidth=2.5,
                    markerfacecolor='white', markeredgewidth=2, zorder=3)
            ax.fill_between(range(len(df)), df[y_col],
                            alpha=0.15, color=colors[0])
            ax.set_xticks(range(len(df)))
            ax.set_xticklabels(df[x_col])

        elif plot_type == 'scatter':
            scatter_colors = [colors[i % len(colors)] for i in range(n)]
            ax.scatter(df[x_col], df[y_col], c=scatter_colors,
                       s=120, edgecolors='white', linewidth=0.8, zorder=3)

        elif plot_type == 'pie':
            wedge_colors = [colors[i % len(colors)] for i in range(n)]
            wedges, texts, autotexts = ax.pie(
                df[y_col], labels=df[x_col], colors=wedge_colors,
                autopct='%1.1f%%', startangle=90,
                wedgeprops={'edgecolor': '#1a1a2e', 'linewidth': 2},
                textprops={'color': '#e0e0f0'},
            )
            for at in autotexts:
                at.set_color('white')
                at.set_fontsize(9)
        else:
            return {"error": f"지원하지 않는 차트: {plot_type}. 'bar','line','scatter','pie' 중 선택하세요."}

        # 4. 제목 및 축 레이블
        ax.set_title(title, color='#e8e8f8', fontsize=14, fontweight='bold', pad=16)
        if plot_type != 'pie':
            ax.set_xlabel(x_label or x_col, labelpad=8, fontsize=11)
            ax.set_ylabel(y_label or y_col, labelpad=8, fontsize=11)
            plt.xticks(rotation=0, ha='center')

        plt.tight_layout(pad=2.0)

        # 5. 저장
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = f"graph_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(UPLOAD_DIR, filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight',
                    facecolor=fig.get_facecolor())
        plt.close()

        image_url = f"/static/{filename}"
        return {
            "result": "그래프가 생성되었습니다.",
            "image_url": image_url,
            "file_path": filepath,
            "markdown": f"![{title}]({image_url})",
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"그래프 생성 실패: {str(e)}"}


@tool
async def create_network_graph(
    edges: List[Dict[str, Any]],
    title: str = "관계도",
    layout: str = "spring",
    color_palette: str = "mixed",
    node_size: int = 1800,
    show_edge_labels: bool = True,
) -> Dict[str, Any]:
    """
    노드-엣지 관계 데이터를 네트워크 그래프(관계도)로 시각화합니다.
    온톨로지, 조직도, 연관 관계 등 엔티티 간의 연결을 표현할 때 사용하세요.

    Args:
        edges: 엣지 목록. 각 항목은 'from'(출발 노드)과 'to'(도착 노드)를 필수로 포함하며,
               선택적으로 'relation'(관계 레이블)을 포함할 수 있습니다.
               예: [{"from": "A팀", "to": "B팀", "relation": "산하조직"},
                    {"from": "A팀", "to": "C팀"}]
        title: 그래프 제목.
        layout: 노드 배치 방식.
                'spring'(기본, 범용), 'circular'(원형), 'kamada_kawai'(균형잡힌 대규모 그래프).
        color_palette: 노드 색상 팔레트 ('blue', 'green', 'purple', 'orange', 'mixed').
        node_size: 노드 크기 (기본값: 1800).
        show_edge_labels: 엣지에 관계 레이블 표시 여부 (기본값: True).

    Returns:
        dict: image_url, file_path, markdown, node_count, edge_count 포함.
    """
    try:
        if not edges:
            return {"error": "edges 목록이 비어 있습니다."}

        # 1. 그래프 구성
        G = nx.DiGraph()
        edge_labels = {}
        for e in edges:
            src = str(e.get("from", ""))
            dst = str(e.get("to", ""))
            if not src or not dst:
                continue
            G.add_edge(src, dst)
            relation = e.get("relation", "")
            if relation:
                edge_labels[(src, dst)] = relation

        if G.number_of_nodes() == 0:
            return {"error": "유효한 노드가 없습니다. 'from'과 'to' 필드를 확인하세요."}

        # 2. 레이아웃 계산
        layout_map = {
            "spring": nx.spring_layout,
            "circular": nx.circular_layout,
            "kamada_kawai": nx.kamada_kawai_layout,
        }
        layout_fn = layout_map.get(layout, nx.spring_layout)
        pos = layout_fn(G, seed=42) if layout == "spring" else layout_fn(G)

        # 3. 색상 할당 (노드마다 순환)
        colors = PALETTES.get(color_palette, PALETTES["mixed"])
        nodes = list(G.nodes())
        node_colors = [colors[i % len(colors)] for i in range(len(nodes))]

        # 4. 그리기
        fig, ax = plt.subplots(figsize=(13, 8))
        bg_color = "#1a1a2e"
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)
        ax.axis("off")

        nx.draw_networkx_nodes(
            G, pos, ax=ax,
            node_color=node_colors,
            node_size=node_size,
            alpha=0.92,
        )
        nx.draw_networkx_labels(
            G, pos, ax=ax,
            font_color="#ffffff",
            font_size=9,
            font_weight="bold",
            font_family=REGISTERED_FONT_NAME,
        )
        nx.draw_networkx_edges(
            G, pos, ax=ax,
            edge_color="#7a7aaa",
            arrows=True,
            arrowsize=18,
            width=1.5,
            connectionstyle="arc3,rad=0.08",
        )
        if show_edge_labels and edge_labels:
            nx.draw_networkx_edge_labels(
                G, pos, edge_labels=edge_labels, ax=ax,
                font_color="#c8c8d8",
                font_size=8,
                font_family=REGISTERED_FONT_NAME,
                bbox={"boxstyle": "round,pad=0.2", "facecolor": "#2d2d4e", "alpha": 0.7, "edgecolor": "none"},
            )

        ax.set_title(title, color="#e8e8f8", fontsize=14, fontweight="bold", pad=16)
        plt.tight_layout(pad=2.0)

        # 5. 저장
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = f"network_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(UPLOAD_DIR, filename)
        plt.savefig(filepath, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close()

        image_url = f"/static/{filename}"
        return {
            "result": "네트워크 그래프가 생성되었습니다.",
            "image_url": image_url,
            "file_path": filepath,
            "markdown": f"![{title}]({image_url})",
            "node_count": G.number_of_nodes(),
            "edge_count": G.number_of_edges(),
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"네트워크 그래프 생성 실패: {str(e)}"}


def _hierarchy_pos(G: nx.DiGraph, root: str, width: float = 1.0, vert_gap: float = 0.2) -> dict:
    """트리 계층 레이아웃 위치 계산 (BFS 기반)"""
    pos = {}
    queue = [(root, 0, 0.0, width)]  # (node, depth, x_left, x_right)
    depth_counter: dict[int, int] = {}

    # BFS로 레벨별 노드 수집
    from collections import deque
    levels: dict[int, list] = {}
    visited = set()
    bfs_q: deque = deque([(root, 0)])
    visited.add(root)
    while bfs_q:
        node, depth = bfs_q.popleft()
        levels.setdefault(depth, []).append(node)
        for child in G.successors(node):
            if child not in visited:
                visited.add(child)
                bfs_q.append((child, depth + 1))

    max_depth = max(levels.keys()) if levels else 0

    # 레벨별 균등 배치
    for depth, nodes in levels.items():
        n = len(nodes)
        for i, node in enumerate(nodes):
            x = (i + 0.5) / n
            y = 1.0 - depth / (max_depth + 1) if max_depth > 0 else 0.5
            pos[node] = (x, y)

    return pos


@tool
async def create_tree_chart(
    nodes: List[Dict[str, Any]],
    title: str = "계층 구조도",
    color_palette: str = "blue",
    node_size: int = 2000,
    show_labels: bool = True,
) -> Dict[str, Any]:
    """
    부모-자식 관계 데이터를 트리(계층 구조도)로 시각화합니다.
    조직도, 카테고리 분류, 온톨로지 클래스 계층 등 위계 구조 표현에 사용하세요.

    Args:
        nodes: 노드 목록. 각 항목은 'id'(노드 이름)를 필수로 포함하며,
               'parent'(부모 노드 이름)를 선택적으로 포함합니다.
               루트 노드는 'parent'를 생략하거나 null로 지정합니다.
               예: [{"id": "본사"},
                    {"id": "개발팀", "parent": "본사"},
                    {"id": "영업팀", "parent": "본사"},
                    {"id": "프론트엔드", "parent": "개발팀"}]
        title: 차트 제목.
        color_palette: 노드 색상 팔레트 ('blue', 'green', 'purple', 'orange', 'mixed').
        node_size: 노드 크기 (기본값: 2000).
        show_labels: 노드 레이블 표시 여부 (기본값: True).

    Returns:
        dict: image_url, file_path, markdown, node_count 포함.
    """
    try:
        if not nodes:
            return {"error": "nodes 목록이 비어 있습니다."}

        # 1. 그래프 구성
        G = nx.DiGraph()
        roots = []
        for n in nodes:
            node_id = str(n.get("id", "")).strip()
            if not node_id:
                continue
            G.add_node(node_id)
            parent = n.get("parent")
            if parent:
                G.add_edge(str(parent).strip(), node_id)
            else:
                roots.append(node_id)

        if G.number_of_nodes() == 0:
            return {"error": "유효한 노드가 없습니다. 'id' 필드를 확인하세요."}

        # 루트가 없으면 in-degree 0인 노드를 루트로
        if not roots:
            roots = [n for n, d in G.in_degree() if d == 0]
        if not roots:
            return {"error": "루트 노드를 찾을 수 없습니다. 'parent'가 없는 노드를 하나 이상 포함해야 합니다."}

        # 루트가 여러 개면 가상 루트로 연결
        if len(roots) > 1:
            virtual_root = "__root__"
            G.add_node(virtual_root)
            for r in roots:
                G.add_edge(virtual_root, r)
            root_node = virtual_root
        else:
            root_node = roots[0]

        # 2. 레이아웃
        pos = _hierarchy_pos(G, root_node)

        # 3. 색상 할당 (깊이별)
        colors = PALETTES.get(color_palette, PALETTES["blue"])
        # BFS로 깊이 계산
        depths = nx.single_source_shortest_path_length(G, root_node)
        node_list = [n for n in G.nodes() if n != "__root__"]
        node_colors = [colors[depths.get(n, 0) % len(colors)] for n in node_list]

        # 4. 그리기
        fig, ax = plt.subplots(figsize=(14, 8))
        bg_color = "#1a1a2e"
        fig.patch.set_facecolor(bg_color)
        ax.set_facecolor(bg_color)
        ax.axis("off")

        # 가상 루트 제외한 서브그래프로 그리기
        draw_nodes = [n for n in G.nodes() if n != "__root__"]
        draw_edges = [(u, v) for u, v in G.edges() if u != "__root__" and v != "__root__"]
        # 가상 루트에서 실제 루트로의 엣지도 표시 (실제 루트들)
        root_edges = [(u, v) for u, v in G.edges() if u == "__root__"]
        draw_edges_visible = [(u, v) for u, v in G.edges() if u != "__root__"]

        sub_pos = {n: pos[n] for n in draw_nodes if n in pos}
        sub_colors = node_colors  # 이미 __root__ 제외됨

        nx.draw_networkx_nodes(
            G, sub_pos, nodelist=draw_nodes, ax=ax,
            node_color=sub_colors,
            node_size=node_size,
            alpha=0.92,
        )
        if show_labels:
            nx.draw_networkx_labels(
                G, sub_pos, labels={n: n for n in draw_nodes}, ax=ax,
                font_color="#ffffff",
                font_size=9,
                font_weight="bold",
                font_family=REGISTERED_FONT_NAME,
            )
        nx.draw_networkx_edges(
            G, sub_pos, edgelist=draw_edges_visible, ax=ax,
            edge_color="#7a7aaa",
            arrows=True,
            arrowsize=16,
            width=1.8,
            connectionstyle="arc3,rad=0.0",
        )

        ax.set_title(title, color="#e8e8f8", fontsize=14, fontweight="bold", pad=16)
        plt.tight_layout(pad=2.0)

        # 5. 저장
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        filename = f"tree_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(UPLOAD_DIR, filename)
        plt.savefig(filepath, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close()

        image_url = f"/static/{filename}"
        return {
            "result": "트리 차트가 생성되었습니다.",
            "image_url": image_url,
            "file_path": filepath,
            "markdown": f"![{title}]({image_url})",
            "node_count": len(draw_nodes),
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"트리 차트 생성 실패: {str(e)}"}
