
import os
import pandas as pd
import json
from typing import Any, Optional, Dict
import pypdf
from docx import Document
import olefile
import zlib
import asyncio

def _read_excel_csv(file_path: str) -> pd.DataFrame:
    try:
        if file_path.endswith('.csv'):
            return pd.read_csv(file_path)
        else:
            return pd.read_excel(file_path)
    except Exception as e:
        raise ValueError(f"Failed to read Excel/CSV: {str(e)}")

def _read_pdf(file_path: str) -> str:
    try:
        reader = pypdf.PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error reading PDF: {str(e)}"

def _read_docx(file_path: str) -> str:
    try:
        doc = Document(file_path)
        text = []
        for para in doc.paragraphs:
            text.append(para.text)
        return "\n".join(text)
    except Exception as e:
        return f"Error reading DOCX: {str(e)}"

def _read_hwp(file_path: str) -> str:
    # Basic HWP text extraction (Experimental)
    try:
        f = olefile.OleFileIO(file_path)
        dirs = f.listdir()
        
        # Check if it is HWP 5.0
        if ["FileHeader"] not in dirs and ["\x05HwpSummaryInformation"] not in dirs:
            return "Reference: Not a valid HWP file."

        # BodyText sections
        text = ""
        sections = [d for d in dirs if d[0] == "BodyText"]
        for section in sections:
            stream = f.openstream(section)
            data = stream.read()
            # Decompress (HWP uses Deflate)
            try:
                uncompressed = zlib.decompress(data, -15)
                # HWP text is UTF-16LE
                # But it's mixed with control characters. 
                # This is a very rough extraction and might need a proper parser.
                # For now, let's look for valid unicode strings.
                decoded = uncompressed.decode('utf-16le', errors='ignore')
                text += decoded
            except Exception:
                pass
                
        return text
    except Exception as e:
        return f"Error reading HWP: {str(e)}"

async def analyze_document(file_path: str, query: str = "") -> Dict[str, Any]:
    """
    Reads a file and returns its content or a summary/preview if it's large.
    
    Args:
        file_path (str): Absolute path to the file.
        query (str): Optional query to guide the analysis.
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    
    ext = os.path.splitext(file_path)[1].lower()
    
    try:
        # Run blocking I/O in thread pool to avoid blocking async loop
        loop = asyncio.get_running_loop()

        # 1. Structured Data (Excel, CSV, JSON)
        if ext in ['.xlsx', '.xls', '.csv', '.json']:
            if ext == '.json':
                def _load_json():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                data = await loop.run_in_executor(None, _load_json)

                # If JSON is a list of dicts, treat as DataFrame
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    df = pd.DataFrame(data)
                else:
                    return {"content": json.dumps(data, indent=2, ensure_ascii=False)}
            else:
                df = await loop.run_in_executor(None, _read_excel_csv, file_path)
            
            # Check size
            if len(df) <= 50:
                return {
                    "type": "structured",
                    "content": df.to_markdown(index=False),
                    "rows": len(df)
                }
            else:
                # Save to processed CSV
                filename = f"processed_{os.path.basename(file_path)}.csv"
                save_path = os.path.join("/tmp", filename)
                await loop.run_in_executor(None, lambda: df.to_csv(save_path, index=False))
                
                return {
                    "type": "structured_large",
                    "file_path": save_path,
                    "preview": df.head(5).to_markdown(index=False),
                    "columns": list(df.columns),
                    "rows": len(df),
                    "message": f"Data is too large ({len(df)} rows). Saved to {save_path}. Use this path for visualization."
                }

        # 2. Unstructured Data (PDF, DOCX, HWP, TXT, MD)
        elif ext in ['.pdf', '.docx', '.hwp', '.txt', '.md']:
            text = ""
            if ext == '.pdf':
                text = await loop.run_in_executor(None, _read_pdf, file_path)
            elif ext == '.docx':
                text = await loop.run_in_executor(None, _read_docx, file_path)
            elif ext == '.hwp':
                text = await loop.run_in_executor(None, _read_hwp, file_path)
            else: # txt, md
                def _read_text():
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return f.read()
                text = await loop.run_in_executor(None, _read_text)
            
            # Limit text return
            if len(text) > 10000:
                return {
                    "type": "text_large",
                    "content": text[:5000] + "\n...[truncated]...",
                    "length": len(text)
                }
            else:
                return {
                    "type": "text",
                    "content": text
                }
        
        else:
            return {"error": f"Unsupported file extension: {ext}"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": f"Failed to analyze file: {str(e)}"}
