"""Supervisor FastAPI server - serves chat UI and orchestration SSE endpoint."""

import os
import json
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from orchestrator import orchestrate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Trip Planner Supervisor")


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest):
    """SSE endpoint that streams orchestration events to the frontend."""

    async def event_stream():
        async for event in orchestrate(req.message):
            yield f"data: {json.dumps(event)}\n\n"
        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/health")
async def health():
    return {"status": "healthy", "app": "trip-planner-supervisor"}


# Serve static frontend
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(static_dir, "index.html"))


if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Trip Planner Supervisor on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
