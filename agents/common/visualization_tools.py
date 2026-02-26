import os
import json
import uuid
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from typing import Union, List, Dict, Any, Optional

# Set non-interactive backend for server environment
matplotlib.use('Agg')

# Constants
# Determine the directory of this file
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Setup Upload Directory
# Try /app/uploads first (Docker default)
if os.path.exists("/app/uploads") and os.access("/app/uploads", os.W_OK):
    UPLOAD_DIR = "/app/uploads"
else:
    # Use /tmp/agent_uploads as a reliable fallback
    UPLOAD_DIR = "/tmp/agent_uploads"
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR, exist_ok=True)

# 2. Setup Font Path
# Font should be in agents/common/fonts/NanumGothic.ttf
FONT_DIR = os.path.join(CURRENT_DIR, "fonts")
FONT_PATH = os.path.join(FONT_DIR, "NanumGothic.ttf")

# Load Korean Font
try:
    if os.path.exists(FONT_PATH):
        # Register the custom font
        fm.fontManager.addfont(FONT_PATH)
        
        # Get the font family name from the file
        font_prop = fm.FontProperties(fname=FONT_PATH)
        font_name = font_prop.get_name()
        
        # Set as default font
        plt.rcParams['font.family'] = font_name
        
        # Fallback for minus sign
        plt.rcParams['axes.unicode_minus'] = False
        print(f"Loaded and registered font: {font_name}")
    else:
        print(f"Font not found at {FONT_PATH}. Using default font.")
except Exception as e:
    print(f"Failed to load custom font: {e}")

async def create_graph(
    data: Union[str, List[Dict[str, Any]]],
    x_col: str,
    y_col: str,
    plot_type: str = "line",
    title: str = "Graph",
    x_label: Optional[str] = None,
    y_label: Optional[str] = None,
    color: Optional[str] = None
) -> Dict[str, Any]:
    """
    Creates a graph from provided data and saves it as an image.

    Args:
        data: File path (CSV/Excel/JSON) or list of dictionaries.
        x_col: Column name for X axis.
        y_col: Column name for Y axis.
        plot_type: Type of plot ('line', 'bar', 'scatter', 'pie'). Default is 'line'.
        title: Title of the graph.
        x_label: Label for X axis (optional).
        y_label: Label for Y axis (optional).
        color: Color of the plot elements (optional).

    Returns:
        Dictionary containing the URL of the generated image or error message.
    """
    try:
        # 1. Load Data
        df = None
        if isinstance(data, str):
            if not os.path.exists(data):
                return {"error": f"File not found: {data}"}
            
            ext = os.path.splitext(data)[1].lower()
            if ext == '.csv':
                df = pd.read_csv(data)
            elif ext in ['.xls', '.xlsx']:
                df = pd.read_excel(data)
            elif ext == '.json':
                with open(data, 'r', encoding='utf-8') as f:
                    data_json = json.load(f)
                if isinstance(data_json, list):
                    df = pd.DataFrame(data_json)
                else:
                    return {"error": "JSON file must contain a list of records."}
            else:
                return {"error": f"Unsupported file format: {ext}"}
        elif isinstance(data, list):
            df = pd.DataFrame(data)
        else:
            return {"error": "Invalid data format. Must be file path or list of dicts."}

        # 2. Validate Columns
        if df is None or df.empty:
            return {"error": "Data is empty or could not be loaded."}
        
        if x_col not in df.columns:
            return {"error": f"Column '{x_col}' not found in data. Available columns: {list(df.columns)}"}
        if y_col not in df.columns and plot_type != 'pie': # Pie chart uses x_col as labels, y_col as values
             return {"error": f"Column '{y_col}' not found in data. Available columns: {list(df.columns)}"}

        # 3. Create Plot
        plt.figure(figsize=(10, 6))
        
        if plot_type == 'line':
            plt.plot(df[x_col], df[y_col], marker='o', color=color, linestyle='-')
        elif plot_type == 'bar':
            plt.bar(df[x_col], df[y_col], color=color)
        elif plot_type == 'scatter':
            plt.scatter(df[x_col], df[y_col], color=color)
        elif plot_type == 'pie':
            plt.pie(df[y_col], labels=df[x_col], autopct='%1.1f%%', startangle=90)
        else:
            return {"error": f"Unsupported plot type: {plot_type}. Use 'line', 'bar', 'scatter', or 'pie'."}

        # 4. Styling
        plt.title(title)
        if plot_type != 'pie':
            plt.xlabel(x_label if x_label else x_col)
            plt.ylabel(y_label if y_label else y_col)
            plt.grid(True, linestyle='--', alpha=0.7)
        
        plt.tight_layout()

        # 5. Save Image
        if not os.path.exists(UPLOAD_DIR):
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            
        filename = f"graph_{uuid.uuid4().hex[:8]}.png"
        filepath = os.path.join(UPLOAD_DIR, filename)
        
        plt.savefig(filepath)
        plt.close()

        # 6. Return Result
        # Construct the static URL. Note: The server creates '/static' mount point.
        # But we need to return a text that helps the user or agent know where it is.
        # Usually, the agent should return the markdown image syntax.
        image_url = f"/static/{filename}"
        
        return {
            "result": f"Graph created successfully.",
            "image_url": image_url,
            "file_path": filepath,
            "markdown": f"![{title}]({image_url})"
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Failed to create graph: {str(e)}"}
