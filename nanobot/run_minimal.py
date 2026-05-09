"""
Minimal run entrypoint for the lightweight Vertex+Lark setup.
- Wires up: DB init, Lark WS channel, simple in-process async task queue and workers.
- Keeps implementation minimal so it can be integrated into existing nanobot runner/MessageBus later.
"""

import asyncio
import json
import os
import time
from typing import Any

from nanobot.config.minimal_settings import settings
from nanobot.channels.lark_ws_async import LarkWSChannel
from nanobot.agent.memory_minimal import ensure_db, add_message, get_recent, get_similar_async, add_file_record, get_file_content
from nanobot.providers.vertex_adapter_minimal import generate_text, embed_text

TASK_QUEUE: asyncio.Queue = asyncio.Queue()

async def worker_loop(worker_id: int):
    print(f"Worker {worker_id} started")
    while True:
        task = await TASK_QUEUE.get()
        try:
            typ = task.get("type")
            if typ == "generate":
                prompt = task["prompt"]
                reply_to = task.get("reply_to")
                # call vertex
                text = await generate_text(prompt)
                # store assistant reply
                await add_message("assistant", text, compute_embedding=True)
                # send back via channel
                channel = task.get("channel")
                if channel:
                    await channel.send({"type": "message", "text": text, "to": reply_to})
            elif typ == "embed":
                # embed-only task
                _ = await embed_text(task.get("text", ""))
            else:
                print("Unknown task type", typ)
        except Exception as e:
            print("Worker error:", e)
        finally:
            TASK_QUEUE.task_done()

async def on_incoming(msg: dict, channel: LarkWSChannel):
    # normalize message
    t = msg.get("type")
    if t == "message":
        text = msg.get("text", "")
        user = msg.get("user", "unknown")
        # store user message
        await add_message("user", text, compute_embedding=True)
        # build context
        recent = await get_recent(6)
        similar = await get_similar_async(text, k=3)
        prompt_parts = ["You are a helpful assistant."]
        prompt_parts.append("Context (recent):")
        for m in recent:
            prompt_parts.append(f"{m['role']}: {m['content']}")
        if similar:
            prompt_parts.append("\nRelevant past memories:")
            for score, content in similar:
                prompt_parts.append(f"- {content}")
        prompt_parts.append("\nUser: " + text)
        prompt = "\n".join(prompt_parts)
        # enqueue generate task
        await TASK_QUEUE.put({"type": "generate", "prompt": prompt, "reply_to": user, "channel": channel})
    elif t == "file_uploaded":
        # ack to user
        fid = msg.get("file_id")
        filename = msg.get("filename")
        await channel.send({"type": "message", "text": f"File received: {filename} (id={fid})"})
    elif t == "file_data":
        # user requested file content; forward the content
        file_info = msg.get("content")
        if file_info:
            await channel.send({"type": "message", "text": f"File {file_info.get('filename')} content:\n{file_info.get('content')[:2000]}"})
    else:
        # unknown event - just log
        print("Unhandled incoming event:", msg)

async def main():
    await ensure_db()
    channel = LarkWSChannel(settings.lark_ws_url, lambda m: on_incoming(m, channel_instance))
    # small wrapper to adapt callback which needs channel reference
    async def cb(m):
        await on_incoming(m, channel)
    # restart channel with proper callback
    channel = LarkWSChannel(settings.lark_ws_url, cb)
    ch_task = channel.start()
    # start workers
    workers = [asyncio.create_task(worker_loop(i)) for i in range(max(1, settings.worker_concurrency))]
    print("Minimal nanobot running")
    try:
        await asyncio.gather(ch_task, *workers)
    except asyncio.CancelledError:
        print("Shutting down")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted")
