"""Transport Agent - FMAPI-powered agent loop with MCP tool calling."""

import json
import logging
from openai import AsyncOpenAI
from config import get_workspace_host, get_oauth_token, FMAPI_MODEL
from mcp_client import MCPClient

logger = logging.getLogger(__name__)
mcp = MCPClient()

SYSTEM_PROMPT = """You are a transportation advisor. When given a task about getting to or around a destination, use your available tools to provide comprehensive transportation information including flights, airport transfers, local transit, and intercity options. Return practical, actionable transportation advice."""


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
    Run the transport agent on a task.

    Args:
        task_description: Natural language description of what transport info to gather

    Returns:
        {"status": "success"|"error", "result": "...", "tools_called": [...]}
    """
    tools_called = []

    try:
        mcp_tools = await mcp.list_tools()
    except Exception as e:
        logger.error(f"Failed to connect to Transport MCP: {e}")
        return {"status": "error", "result": f"Failed to connect to Transport MCP server: {e}", "tools_called": []}

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
            # Build assistant message with tool_calls
            assistant_msg = {"role": "assistant", "content": msg.content or None, "tool_calls": []}
            for tc in msg.tool_calls:
                tc_id = tc.id
                tc_name = tc.function.name
                tc_args_str = tc.function.arguments
                assistant_msg["tool_calls"].append({
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": tc_name, "arguments": tc_args_str},
                })
            messages.append(assistant_msg)

            # Execute each tool call
            for tc in msg.tool_calls:
                tc_id = tc.id
                tc_name = tc.function.name
                tc_args_str = tc.function.arguments
                tc_args = json.loads(tc_args_str) if tc_args_str else {}

                tools_called.append({"tool": tc_name, "arguments": tc_args})
                logger.info(f"Calling tool: {tc_name}({tc_args})")

                try:
                    mcp_result = await mcp.call_tool(tc_name, tc_args)
                    result_text = mcp_result.get("result", "No result")
                    is_error = mcp_result.get("isError", False)
                except Exception as e:
                    logger.error(f"MCP tool call failed: {e}")
                    result_text = f"Tool execution error: {e}"
                    is_error = True

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_text,
                })

                if is_error:
                    logger.warning(f"Tool {tc_name} returned error: {result_text}")
            continue
        else:
            # Final text response
            final_text = msg.content or ""
            logger.info(f"Agent completed after {turn + 1} turns, {len(tools_called)} tool calls")
            return {"status": "success", "result": final_text, "tools_called": tools_called}

    return {"status": "error", "result": "Agent reached maximum turns without final answer", "tools_called": tools_called}
