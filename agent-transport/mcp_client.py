"""HTTP client for calling the Transport MCP server's REST API."""

import logging
import httpx
from config import MCP_SERVER_URL, get_auth_headers

logger = logging.getLogger(__name__)


class MCPClient:
    """Simple HTTP client for MCP server REST endpoints."""

    def __init__(self, base_url: str = MCP_SERVER_URL):
        self.base_url = base_url.rstrip("/")
        self._tools_cache: list[dict] | None = None

    async def list_tools(self) -> list[dict]:
        if self._tools_cache is not None:
            return self._tools_cache

        headers = get_auth_headers()
        async with httpx.AsyncClient(verify=False, timeout=30) as client:
            resp = await client.get(f"{self.base_url}/api/tools", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            tools = data.get("tools", [])
            logger.info(f"Discovered {len(tools)} MCP tools: {[t['name'] for t in tools]}")
            self._tools_cache = tools
            return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        headers = get_auth_headers()
        headers["Content-Type"] = "application/json"
        logger.info(f"Calling MCP tool: {name} with args: {arguments}")

        async with httpx.AsyncClient(verify=False, timeout=60) as client:
            resp = await client.post(
                f"{self.base_url}/api/call",
                headers=headers,
                json={"name": name, "arguments": arguments},
            )
            resp.raise_for_status()
            result = resp.json()
            if result.get("isError"):
                logger.error(f"MCP tool error: {result}")
            return result
