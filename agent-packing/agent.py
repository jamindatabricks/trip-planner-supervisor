"""Packing Agent - FMAPI-powered agent loop with MCP tool calling."""

import json
import logging
from openai import AsyncOpenAI
from config import get_workspace_host, get_oauth_token, FMAPI_MODEL
from mcp_client import MCPClient

logger = logging.getLogger(__name__)
mcp = MCPClient()

SYSTEM_PROMPT = """You are a packing advisor assistant. When given a task about what to pack for a trip, use your available tools to generate comprehensive packing recommendations.

Consider:
- Weather conditions provided in the context
- Trip duration
- Destination-specific needs (cultural, practical)
- Trip type (leisure, business, adventure)

Always use the tools to generate the packing list - do not make up recommendations without using the tools first. Pass the weather information from the context into the tool's weather_summary parameter.

Return a well-organized response summarizing the packing recommendations."""


def _mcp_tools_to_openai(mcp_tools: list[dict]) -> list[dict]:
    """Convert MCP REST tool definitions to OpenAI function-calling format."""
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return openai_tools


async def run_task(task_description: str) -> dict:
    """
    Run the packing agent on a task.

    Args:
        task_description: Natural language description of packing needs + weather context

    Returns:
        {"status": "success"|"error", "result": "...", "tools_called": [...]}
    """
    tools_called = []

    try:
        mcp_tools = await mcp.list_tools()
    except Exception as e:
        logger.error(f"Failed to connect to Packing MCP: {e}")
        return {"status": "error", "result": f"Failed to connect to Packing MCP server: {e}", "tools_called": []}

    openai_tools = _mcp_tools_to_openai(mcp_tools)
    logger.info(f"Tools available: {[t['function']['name'] for t in openai_tools]}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task_description},
    ]

    client = AsyncOpenAI(
        api_key=get_oauth_token(),
        base_url=f"{get_workspace_host()}/serving-endpoints",
    )

    max_turns = 8
    for turn in range(max_turns):
        try:
            response = await client.chat.completions.create(
                model=FMAPI_MODEL,
                messages=messages,
                tools=openai_tools if openai_tools else None,
                max_tokens=4096,
            )
        except Exception as e:
            logger.error(f"FMAPI call failed: {e}")
            return {"status": "error", "result": f"Model API error: {e}", "tools_called": tools_called}

        choice = response.choices[0]
        msg = choice.message

        if msg.tool_calls:
            assistant_msg = {"role": "assistant", "content": msg.content or None, "tool_calls": []}
            for tc in msg.tool_calls:
                assistant_msg["tool_calls"].append({
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                })
            messages.append(assistant_msg)

            for tc in msg.tool_calls:
                tc_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tools_called.append({"tool": tc.function.name, "arguments": tc_args})
                logger.info(f"Calling tool: {tc.function.name}({tc_args})")

                try:
                    mcp_result = await mcp.call_tool(tc.function.name, tc_args)
                    result_text = mcp_result.get("result", "No result")
                    is_error = mcp_result.get("isError", False)
                except Exception as e:
                    logger.error(f"MCP tool call failed: {e}")
                    result_text = f"Tool execution error: {e}"
                    is_error = True

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })

                if is_error:
                    logger.warning(f"Tool {tc.function.name} returned error: {result_text}")
            continue
        else:
            final_text = msg.content or ""
            logger.info(f"Agent completed after {turn + 1} turns, {len(tools_called)} tool calls")
            return {"status": "success", "result": final_text, "tools_called": tools_called}

    return {"status": "error", "result": "Agent reached maximum turns without final answer", "tools_called": tools_called}
