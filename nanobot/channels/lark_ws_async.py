"""
Async Lark WebSocket channel.
- Uses `websockets` library.
- Minimal message handling: text messages trigger normal flow.
- Supports a simple file upload/download protocol over WS:
  - Upload from user: send JSON {"type":"file_upload","filename":"a.txt","content":"..."} where content is plain text; channel will store file on server filesystem and create a file_id.
  - Download request: {"type":"file_download","file_id":"..."} -> channel will return a message with type file_data and content.
- This implementation uses a generic envelope; adapt to your Lark WS envelope as needed.
"""

import asyncio
import json
import traceback
import websockets
from typing import Callable, Any
from nanobot.config.minimal_settings import settings
from nanobot.agent.memory_minimal import add_file_record, get_file_content


class LarkWSChannel:
    def __init__(self, url: str, on_message: Callable[[dict], Any]):
        self.url = url
        self.on_message = on_message
        self._ws = None
        self._stop = False

    async def _handle_message(self, raw: str):
        try:
            obj = json.loads(raw)
        except Exception:
            # If raw not JSON, wrap as text message
            obj = {"type": "message", "text": raw}
        # Handle file upload/download locally
        t = obj.get("type")
        if t == "file_upload":
            filename = obj.get("filename", "unnamed.txt")
            content = obj.get("content", "")
            # store file on filesystem and return file_id
            file_id = await add_file_record(filename, content)
            # send ack via on_message callback (so Agent can route response)
            await self.on_message({"type":"file_uploaded", "file_id": file_id, "filename": filename, "orig": obj})
            return
        if t == "file_download":
            file_id = obj.get("file_id")
            content = await get_file_content(file_id)
            await self.on_message({"type":"file_data", "file_id": file_id, "content": content})
            return
        # default: pass to agent
        await self.on_message(obj)

    async def _connect_loop(self):
        backoff = 1
        while not self._stop:
            try:
                async with websockets.connect(self.url, ping_interval=30) as ws:
                    self._ws = ws
                    backoff = 1
                    async for message in ws:
                        await self._handle_message(message)
            except Exception as e:
                traceback.print_exc()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
        self._ws = None

    def start(self):
        # returns the running task
        return asyncio.create_task(self._connect_loop())

    async def send(self, obj: dict):
        if self._ws and self._ws.open:
            await self._ws.send(json.dumps(obj))
        else:
            # best-effort: call on_message with error or queue for later
            print("WS not connected, cannot send", obj)
