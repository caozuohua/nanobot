"""
Lightweight Vertex AI adapter.
- Uses google-auth.default() to get token (sync), runs network calls in asyncio.to_thread to avoid blocking.
- Exposes async functions: generate_text(...) and embed_text(...)
- Designed to be used by an async worker (task queue) or called directly with await.
"""

import asyncio
import json
from typing import Any, List
from google.auth import default
from google.auth.transport.requests import Request
import requests

from nanobot.config.minimal_settings import settings


def _get_bearer_sync():
    creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not creds.valid:
        creds.refresh(Request())
    return creds.token


async def _get_bearer() -> str:
    return await asyncio.to_thread(_get_bearer_sync)


def _endpoint(project: str, location: str, model: str) -> str:
    # Vertex predict endpoint (REST)
    return f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}/locations/{location}/models/{model}:predict"


async def generate_text(prompt: str, *,
                        max_tokens: int = 512,
                        temperature: float = 0.2,
                        timeout: int = 60) -> str:
    token = await _get_bearer()
    url = _endpoint(settings.vertex_project_id, settings.vertex_location, settings.vertex_gen_model)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "instances": [{"content": prompt}],
        "parameters": {"maxOutputTokens": max_tokens, "temperature": temperature}
    }
    resp = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # Flexible extraction: adapt if your model returns different shape
    if "predictions" in data and len(data["predictions"]) > 0:
        p = data["predictions"][0]
        for key in ("content", "output", "text", "generated_text"):
            if key in p:
                return p[key]
        # sometimes prediction itself is a string/list
        if isinstance(p, str):
            return p
    # Last resort
    return json.dumps(data)


async def embed_text(text: str, *, timeout: int = 30) -> List[float]:
    token = await _get_bearer()
    url = _endpoint(settings.vertex_project_id, settings.vertex_location, settings.vertex_emb_model)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"instances": [{"content": text}]}
    resp = await asyncio.to_thread(requests.post, url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "predictions" in data and len(data["predictions"]) > 0:
        p = data["predictions"][0]
        for k in ("embedding", "embeddings", "vector"):
            if k in p:
                return p[k]
        # fallback: if prediction is a list
        if isinstance(p, list):
            return p
    raise RuntimeError("Unexpected embedding response: " + json.dumps(data))
