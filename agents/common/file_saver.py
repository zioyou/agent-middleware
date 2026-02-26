import base64
import os
import uuid
from langchain_core.messages import HumanMessage, BaseMessage
from typing import List, Dict, Any, Union
from langchain_core.runnables import RunnableConfig

def save_file_from_base64(data: str, filename: str, mime_type: str = None) -> str:
    """Decodes base64 data and saves it to the uploads directory. Returns the absolute file path."""
    upload_dir = "/app/uploads"
    # Ensure directory exists
    if not os.path.exists(upload_dir):
        try:
            os.makedirs(upload_dir, exist_ok=True)
            # Make sure it's writable
            os.chmod(upload_dir, 0o777) 
        except Exception as e:
            # Fallback to /tmp if permission denied
            print(f"Failed to create/access {upload_dir}: {e}. Falling back to /tmp")
            upload_dir = "/tmp"

    # Generate unique filename
    unique_id = uuid.uuid4().hex[:8]
    safe_filename = os.path.basename(filename).replace(" ", "_")
    final_filename = f"{unique_id}_{safe_filename}"
    file_path = os.path.join(upload_dir, final_filename)
    
    try:
        file_bytes = base64.b64decode(data)
        with open(file_path, "wb") as f:
            f.write(file_bytes)
        print(f"Saved file to {file_path}")
    except Exception as e:
        print(f"Error writing file {file_path}: {e}")
        raise e
        
    return file_path

def process_file_uploads(messages: List[BaseMessage]) -> List[BaseMessage]:
    """
    Scans messages for file blocks (type: 'file'), saves them to disk, 
    and replaces the block with a text block containing the file path.
    Returns a list of MODIFIED messages.
    """
    updated_messages = []
    
    for m in messages:
        # Only process HumanMessages with content list
        if isinstance(m, HumanMessage) and isinstance(m.content, list):
            new_content = []
            modified = False
            for block in m.content:
                if isinstance(block, dict) and block.get("type") == "file":
                    # Detected file block
                    try:
                        b64_data = block.get("data")
                        metadata = block.get("metadata", {})
                        filename = metadata.get("filename") or "unknown_file"
                        mime_type = block.get("mimeType")
                        
                        if b64_data:
                            file_path = save_file_from_base64(b64_data, filename, mime_type)
                            
                            # Replace with text block indicating readiness
                            # "File uploaded: {path}"
                            # We deliberately use a format that the LLM can understand.
                            new_content.append({
                                "type": "text",
                                "text": f"\n[System] File '{filename}' has been saved to the server at: {file_path}\n"
                                        f"IMPORTANT: You have explicit PERMISSION to access this path. It is within your sandbox.\n"
                                        f"To analyze this file, use the 'analyze_document' tool with the path '{file_path}'.\n"
                                        f"Do NOT use 'ls', 'glob', or 'bash' commands to read it. Use 'analyze_document' ONLY.\n"
                            })
                            modified = True
                        else:
                            # No data?
                            new_content.append(block)
                            
                    except Exception as e:
                        print(f"Error saving file: {e}")
                        new_content.append({
                            "type": "text", 
                            "text": f"\n[System] Failed to save uploaded file '{filename}': {str(e)}\n"
                        })
                        modified = True
                else:
                    new_content.append(block)
            
            if modified:
                # Create a NEW message with the same ID to allow replacement in state
                new_msg = HumanMessage(content=new_content, id=m.id)
                # Helper: copy other attributes if needed (response_metadata etc)
                new_msg.additional_kwargs = m.additional_kwargs
                new_msg.response_metadata = m.response_metadata
                updated_messages.append(new_msg)
            
    return updated_messages


async def file_saver_node(state: Dict[str, Any], config: RunnableConfig) -> Dict[str, Any]:
    """Checks for file uploads in messages and saves them to disk.
    
    This is a reusable node that can be added to any agent's graph.
    """
    messages = state["messages"]
    # Only check the last message(s) to avoid full history scan overhead if possible,
    # but process_file_uploads filters safely.
    # To be safe against race conditions or multiples, pass full list or just the new ones?
    # Since we are modifying state in place, full list is okay as long as process_file_uploads is efficient.
    updated_messages = process_file_uploads(messages)
    if updated_messages:
        return {"messages": updated_messages}
    return {}

