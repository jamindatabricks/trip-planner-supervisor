"""Packing Agent - LangGraph ReAct agent with MCP tools via Databricks FMAPI."""

import logging
import httpx
from langchain_core.tools import tool
from langchain_core.messages import AIMessage
from databricks_langchain import ChatDatabricks
from langgraph.prebuilt import create_react_agent
from config import FMAPI_MODEL, MCP_SERVER_URL, get_auth_headers

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a packing advisor assistant. When given a task about what to pack for a trip, use your available tools to generate comprehensive packing recommendations.

Consider:
- Weather conditions provided in the context
- Trip duration
- Destination-specific needs (cultural, practical)
- Trip type (leisure, business, adventure)

Always use the tools to generate the packing list - do not make up recommendations without using the tools first. Pass the weather information from the context into the tool's weather_summary parameter.

Return a well-organized response summarizing the packing recommendations."""


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
async def get_packing_list(destination: str, duration_days: int, weather_summary: str, trip_type: str = "leisure") -> str:
    """Generate a comprehensive packing list based on destination, trip duration, weather conditions, and trip type (leisure/business/adventure)."""
    return await _call_mcp("get_packing_list", {
        "destination": destination, "duration_days": duration_days,
        "weather_summary": weather_summary, "trip_type": trip_type,
    })


@tool
async def get_destination_tips(destination: str) -> str:
    """Get destination-specific packing tips and cultural considerations."""
    return await _call_mcp("get_destination_tips", {"destination": destination})


# Build the LangGraph ReAct agent
model = ChatDatabricks(endpoint=FMAPI_MODEL)
agent = create_react_agent(model, [get_packing_list, get_destination_tips], prompt=SYSTEM_PROMPT)


async def run_task(task_description: str) -> dict:
    """Run the packing agent on a task."""
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
