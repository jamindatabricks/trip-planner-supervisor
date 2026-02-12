"""Activities Agent - LangGraph ReAct agent with MCP tools via Databricks FMAPI."""

import logging
import httpx
from langchain_core.tools import tool
from langchain_core.messages import AIMessage
from databricks_langchain import ChatDatabricks
from langgraph.prebuilt import create_react_agent
from config import FMAPI_MODEL, MCP_SERVER_URL, get_auth_headers

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an activities and attractions advisor. When given a task about things to do at a trip destination, use your available tools to find recommended activities, restaurants, sightseeing spots, and entertainment. If weather context is provided, adjust your recommendations accordingly (prefer indoor activities for rainy weather). Return well-organized activity recommendations grouped by category."""


async def _call_mcp(name: str, arguments: dict) -> str:
    """Call an MCP tool via the REST API."""
    headers = get_auth_headers()
    headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(verify=False, timeout=60) as client:
        resp = await client.post(
            f"{MCP_SERVER_URL.rstrip('/')}/api/call",
            headers=headers,
            json={"name": name, "arguments": arguments},
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("isError"):
            return f"Error: {result.get('result', 'Unknown error')}"
        return result.get("result", "No result")


@tool
async def get_activities(city: str, weather_conditions: str = "", category: str = "all") -> str:
    """Get recommended activities and attractions for a city. Can filter by category (all/outdoor/indoor/food/nightlife/day_trips) and adjust for weather conditions."""
    return await _call_mcp("get_activities", {
        "city": city, "weather_conditions": weather_conditions, "category": category,
    })


# Build the LangGraph ReAct agent
model = ChatDatabricks(endpoint=FMAPI_MODEL)
agent = create_react_agent(model, [get_activities], prompt=SYSTEM_PROMPT)


async def run_task(task_description: str) -> dict:
    """Run the activities agent on a task."""
    tools_called = []
    try:
        result = await agent.ainvoke({"messages": [("user", task_description)]})

        for msg in result["messages"]:
            if isinstance(msg, AIMessage) and msg.tool_calls:
                for tc in msg.tool_calls:
                    tools_called.append({"tool": tc["name"], "arguments": tc.get("args", {})})

        final_text = result["messages"][-1].content
        logger.info(f"Agent completed with {len(tools_called)} tool calls")
        return {"status": "success", "result": final_text, "tools_called": tools_called}
    except Exception as e:
        logger.error(f"Agent error: {e}")
        return {"status": "error", "result": f"Agent error: {e}", "tools_called": tools_called}
