"""Budget Agent FastAPI server - exposes POST /task for supervisor."""

import os
import logging
from fastapi import FastAPI
from pydantic import BaseModel
from agent import run_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Budget Agent")


class TaskRequest(BaseModel):
    task: str
    context: str = ""


class TaskResponse(BaseModel):
    status: str
    result: str
    tools_called: list


@app.post("/task", response_model=TaskResponse)
async def handle_task(req: TaskRequest):
    full_task = req.task
    if req.context:
        full_task += f"\n\nAdditional context:\n{req.context}"

    logger.info(f"Budget Agent received task: {req.task[:100]}...")
    result = await run_task(full_task)
    logger.info(f"Budget Agent completed with status: {result['status']}")
    return TaskResponse(**result)


@app.get("/health")
async def health():
    return {"status": "healthy", "agent": "budget-agent"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Budget Agent on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
