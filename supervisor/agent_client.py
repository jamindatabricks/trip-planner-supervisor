"""HTTP client for calling all agent /task endpoints."""

import logging
import httpx
from config import get_auth_headers, AGENT_URLS

logger = logging.getLogger(__name__)


class AgentClient:
    def __init__(self, agent_url: str, agent_name: str):
        self.agent_url = agent_url.rstrip("/")
        self.agent_name = agent_name

    async def send_task(self, task: str, context: str = "") -> dict:
        headers = get_auth_headers()
        headers["Content-Type"] = "application/json"
        logger.info(f"Sending task to {self.agent_name}: {task[:100]}...")
        try:
            async with httpx.AsyncClient(verify=False, timeout=120) as client:
                resp = await client.post(
                    f"{self.agent_url}/task",
                    headers=headers,
                    json={"task": task, "context": context},
                )
                if resp.status_code != 200:
                    return {"status": "error", "result": f"HTTP {resp.status_code}: {resp.text[:200]}", "tools_called": []}
                result = resp.json()
                logger.info(f"{self.agent_name} completed: {result.get('status')}")
                return result
        except Exception as e:
            logger.error(f"Failed to reach {self.agent_name}: {e}")
            return {"status": "error", "result": f"Failed to reach {self.agent_name}: {e}", "tools_called": []}


# Registry of all agent clients
agents = {
    name: AgentClient(url, f"{name.title()} Agent")
    for name, url in AGENT_URLS.items()
}
