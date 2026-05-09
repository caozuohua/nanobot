"""
Minimal settings for lightweight Vertex+Lark mode.
Import or merge into your existing configuration loader as needed.
"""

import os
from pydantic import BaseSettings

class MinimalSettings(BaseSettings):
    minimal_mode: bool = True
    sqlite_path: str = os.getenv("SQLITE_PATH", "nanobot_memory_minimal.db")
    files_dir: str = os.getenv("FILES_DIR", "./nanobot_files")
    vertex_project_id: str = os.getenv("VERTEX_PROJECT_ID", "")
    vertex_location: str = os.getenv("VERTEX_LOCATION", "us-central1")
    # default generation model choices; override via env
    vertex_gen_model: str = os.getenv("VERTEX_GEN_MODEL", "gemini-2.5-flash")
    # embedding model (default keep a lightweight embedding model)
    vertex_emb_model: str = os.getenv("VERTEX_EMB_MODEL", "textembedding-gecko@001")
    lark_ws_url: str = os.getenv("LARK_WS_URL", "")
    worker_concurrency: int = int(os.getenv("WORKER_CONCURRENCY", "1"))

settings = MinimalSettings()
