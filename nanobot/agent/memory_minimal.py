"""
Minimal async SQLite-backed memory + server file store.
- messages: store role/content/embedding/ts
- files: stored on server filesystem under settings.files_dir; functions return file_id references
- embedding stored as JSON text
- get_similar_async uses pure-Python cosine similarity (no numpy)
"""

import aiosqlite
import json
import time
import uuid
import os
import math
from typing import Any, List, Optional, Tuple

from nanobot.config.minimal_settings import settings
from nanobot.providers.vertex_adapter_minimal import embed_text

DB_PATH = settings.sqlite_path
FILES_DIR = settings.files_dir

async def _init_db():
    os.makedirs(FILES_DIR, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT,
            content TEXT,
            embedding TEXT,
            ts INTEGER
        );
        """)
        await db.commit()

# call this at startup
async def ensure_db():
    await _init_db()

async def add_message(role: str, content: str, compute_embedding: bool = True) -> int:
    emb = None
    if compute_embedding:
        emb = await embed_text(content)
    ts = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("INSERT INTO messages(role, content, embedding, ts) VALUES (?, ?, ?, ?)",
                          (role, content, json.dumps(emb) if emb is not None else None, ts))
        await db.commit()
        return cur.lastrowid

async def get_recent(n: int = 10) -> List[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, role, content, embedding, ts FROM messages ORDER BY ts DESC LIMIT ?", (n,))
        rows = await cur.fetchall()
    results = []
    for r in reversed(rows):
        results.append({"id": r[0], "role": r[1], "content": r[2], "embedding": json.loads(r[3]) if r[3] else None, "ts": r[4]})
    return results

# pure-Python cosine similarity
def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))

async def get_similar_async(query: str, k: int = 5, batch_size: int = 500) -> List[Tuple[float, str]]:
    # compute query embedding
    q_emb = await embed_text(query)
    best: List[Tuple[float, str]] = []
    offset = 0
    async with aiosqlite.connect(DB_PATH) as db:
        while True:
            cur = await db.execute("SELECT id, content, embedding FROM messages WHERE embedding IS NOT NULL LIMIT ? OFFSET ?", (batch_size, offset))
            rows = await cur.fetchall()
            if not rows:
                break
            for r in rows:
                try:
                    emb = json.loads(r[2])
                    score = _cosine(q_emb, emb)
                except Exception:
                    score = 0.0
                best.append((score, r[1]))
            offset += batch_size
    best.sort(key=lambda x: x[0], reverse=True)
    return best[:k]

# file helpers (store files on server filesystem)
async def add_file_record(filename: str, content: str) -> str:
    fid = str(uuid.uuid4())
    safe_name = f"{fid}_{filename}"
    path = os.path.join(FILES_DIR, safe_name)
    # write file (assume text content)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return fid

async def get_file_content(file_id: str) -> Optional[dict]:
    # find file by prefix in FILES_DIR
    for name in os.listdir(FILES_DIR):
        if name.startswith(file_id + "_"):
            path = os.path.join(FILES_DIR, name)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            filename = name.split("_", 1)[1]
            ts = int(os.path.getmtime(path))
            return {"file_id": file_id, "filename": filename, "content": content, "ts": ts}
    return None
