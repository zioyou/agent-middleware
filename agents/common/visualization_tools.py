import os
import json
import uuid
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import numpy as np
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

try:
    if os.path.exists(FONT_PATH):
        fm.fontManager.addfont(FONT_PATH)
        font_prop = fm.FontProperties(fname=FONT_PATH)
        font_name = font_prop.get_name()
        plt.rcParams['font.family'] = font_name
        plt.rcParams['axes.unicode_minus'] = False
        print(f"Loaded and registered font: {font_name}")
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
