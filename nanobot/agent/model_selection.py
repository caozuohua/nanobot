"""Persistent global model preset selection."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_model_selection(path: Path) -> str | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("preset")
    except (OSError, ValueError, AttributeError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


def save_model_selection(path: Path, preset: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"preset": preset}) + "\n", encoding="utf-8")
    os.replace(temp, path)
