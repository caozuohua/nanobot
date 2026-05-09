name=docs/deploy-minimal-lark-vertex.md
# Deploy nanobot (minimal Vertex + Lark WS)

Prereqs:
- Python 3.11+
- Service account JSON with Vertex access; set GOOGLE_APPLICATION_CREDENTIALS
- Environment variables:
  - VERTEX_PROJECT_ID, VERTEX_LOCATION, VERTEX_GEN_MODEL (e.g. gemini-2.5-pro/gemini-2.5-flash/gemini-2.5-flash-lite), VERTEX_EMB_MODEL
  - LARK_WS_URL
  - SQLITE_PATH (optional)
  - FILES_DIR (optional, default ./nanobot_files)
  - WORKER_CONCURRENCY (default 1)

Install:
  python -m pip install -r requirements-minimal.txt

Run:
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
  export VERTEX_PROJECT_ID=your-project
  export LARK_WS_URL=wss://...
  python -m nanobot.run_minimal

Notes:
- This minimal setup uses SQLite for messages and a local filesystem folder for uploaded files. It keeps memory usage low by batching and using a single-process async worker model.
- Adjust WORKER_CONCURRENCY to 1-2 on E2-micro.
