"""Dynamic supervisor orchestrator - uses FMAPI tool calling to decide which agents to invoke."""

import asyncio
import json
import logging
from typing import AsyncGenerator
from openai import AsyncOpenAI
from config import get_workspace_host, get_oauth_token, FMAPI_MODEL
from agent_client import agents

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_PROMPT = """You are a trip planning supervisor that coordinates specialized agents to help users with travel questions. You have 5 agents available:

1. **Weather Agent** - Gets weather forecasts and current conditions for destinations
2. **Packing Agent** - Recommends what to pack (best results when given weather context)
3. **Activities Agent** - Suggests things to do, restaurants, sightseeing (can adjust for weather)
4. **Budget Agent** - Estimates trip costs (flights, hotels, food, activities)
5. **Transportation Agent** - Provides flight options, airport transfers, local transit info

## How to work:

1. FIRST, call `create_plan` to announce which agents you'll use and why. Only include agents relevant to the user's question.
2. THEN, call the agent tools to gather information. **Call independent agents in parallel** by making multiple tool calls in a single response:
   - Budget and Transportation agents NEVER need weather context - always call them in parallel with each other and with Weather if applicable.
   - If Weather is needed: call Weather (plus any independent agents like Budget/Transport) in the FIRST round. Then after getting weather results, call Packing and/or Activities in a SECOND round (in parallel if both are needed).
   - If Weather is NOT needed: call all relevant agents in parallel in a single round.
3. FINALLY, after all agent calls complete, synthesize a comprehensive response using markdown formatting.

## Important rules:
- Only call agents that are relevant to the question. "How much does Tokyo cost?" needs only Budget Agent.
- If the user asks about packing, always get weather first since packing depends on weather.
- If the user asks about activities AND weather matters (outdoor vs indoor), get weather first.
- Budget and Transportation agents are independent - they don't need weather context. ALWAYS call them in parallel with other independent agents.
- Be efficient - call independent agents simultaneously in a single response to minimize wait time.
- After receiving agent results, write a well-structured final answer with markdown headers and bullet points."""

AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_plan",
            "description": "Announce which agents you will call and in what order. ALWAYS call this first before calling any agent tools.",
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "description": "Ordered list of agents to call. Group parallel agents together.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agent": {"type": "string", "enum": ["weather", "packing", "activities", "budget", "transport"]},
                                "reason": {"type": "string", "description": "Brief reason for calling this agent"},
                            },
                            "required": ["agent", "reason"],
                        },
                    }
                },
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_weather_agent",
            "description": "Get weather forecast for a destination. Call when the question involves weather, outdoor plans, or when packing/activities agents need weather context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What weather information to gather"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_packing_agent",
            "description": "Get packing recommendations. Best when given weather context. Call after weather agent if both are needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What packing advice is needed"},
                    "context": {"type": "string", "description": "Weather or other context to inform packing recommendations"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_activities_agent",
            "description": "Get activity and sightseeing recommendations. Can adjust for weather if context is provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What activity recommendations are needed"},
                    "context": {"type": "string", "description": "Weather or other context to adjust recommendations"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_budget_agent",
            "description": "Get trip cost estimates. Independent - does not need weather context. Can be called in parallel with other agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What cost information is needed"},
                },
                "required": ["task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_transport_agent",
            "description": "Get transportation information (flights, local transit, getting around). Independent - does not need weather context. Can be called in parallel with other agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "What transportation information is needed"},
                },
                "required": ["task"],
            },
        },
    },
]

# Map tool names to agent keys
TOOL_TO_AGENT = {
    "call_weather_agent": "weather",
    "call_packing_agent": "packing",
    "call_activities_agent": "activities",
    "call_budget_agent": "budget",
    "call_transport_agent": "transport",
}

AGENT_DISPLAY_NAMES = {
    "weather": "Weather Agent",
    "packing": "Packing Agent",
    "activities": "Activities Agent",
    "budget": "Budget Agent",
    "transport": "Transport Agent",
}


async def orchestrate(user_message: str) -> AsyncGenerator[dict, None]:
    """
    Dynamic orchestration loop using FMAPI tool calling.
    Supports parallel agent execution when the LLM issues multiple tool calls.
    Yields SSE events for the frontend to display progress.
    """
    yield {"type": "status", "message": "Planning which agents to use..."}

    client = AsyncOpenAI(
        api_key=get_oauth_token(),
        base_url=f"{get_workspace_host()}/serving-endpoints",
    )

    messages = [
        {"role": "system", "content": SUPERVISOR_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    planned_agents = []
    completed_agents = []

    max_turns = 15
    for turn in range(max_turns):
        try:
            response = await client.chat.completions.create(
                model=FMAPI_MODEL,
                messages=messages,
                tools=AGENT_TOOLS,
                max_tokens=4096,
            )
        except Exception as e:
            logger.error(f"FMAPI call failed: {e}")
            yield {"type": "error", "error": f"Model API error: {e}"}
            return

        choice = response.choices[0]
        msg = choice.message

        if msg.tool_calls:
            # Build assistant message
            assistant_msg = {"role": "assistant", "content": msg.content or None, "tool_calls": []}
            for tc in msg.tool_calls:
                assistant_msg["tool_calls"].append({
                    "id": tc.id, "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                })
            messages.append(assistant_msg)

            # Categorize tool calls
            plan_calls = []
            agent_calls = []
            unknown_calls = []
            for tc in msg.tool_calls:
                if tc.function.name == "create_plan":
                    plan_calls.append(tc)
                elif tc.function.name in TOOL_TO_AGENT:
                    agent_calls.append(tc)
                else:
                    unknown_calls.append(tc)

            # Handle plan calls
            for tc in plan_calls:
                tc_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                steps = tc_args.get("steps", [])
                planned_agents = [s["agent"] for s in steps]
                logger.info(f"Plan: {planned_agents}")
                yield {
                    "type": "plan",
                    "steps": steps,
                    "agents": planned_agents,
                }
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Plan confirmed. Proceeding with agents: {', '.join(planned_agents)}. Remember to call independent agents in parallel by issuing multiple tool calls in a single response.",
                })

            # Handle unknown calls
            for tc in unknown_calls:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Unknown tool: {tc.function.name}",
                })

            # Handle agent calls
            if not agent_calls:
                continue

            agent_keys = []
            for tc in agent_calls:
                agent_key = TOOL_TO_AGENT[tc.function.name]
                agent_keys.append(agent_key)
                if agent_key not in planned_agents:
                    planned_agents.append(agent_key)
                    yield {
                        "type": "plan_update",
                        "agents": planned_agents,
                        "added": agent_key,
                        "reason": f"Supervisor decided to also consult {AGENT_DISPLAY_NAMES[agent_key]}",
                    }

            is_parallel = len(agent_calls) > 1

            # Emit round start so frontend knows the grouping
            yield {
                "type": "round_start",
                "agents": agent_keys,
                "parallel": is_parallel,
            }

            # Emit agent_start for each agent in this round
            for tc in agent_calls:
                agent_key = TOOL_TO_AGENT[tc.function.name]
                tc_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                task = tc_args.get("task", "")
                yield {
                    "type": "agent_start",
                    "agent": agent_key,
                    "task": task[:150],
                }

            if is_parallel:
                # Run agents concurrently
                logger.info(f"Running {len(agent_calls)} agents in parallel: {agent_keys}")

                async def _call_agent(tc_inner):
                    ak = TOOL_TO_AGENT[tc_inner.function.name]
                    args = json.loads(tc_inner.function.arguments) if tc_inner.function.arguments else {}
                    task_text = args.get("task", "")
                    context_text = args.get("context", "")
                    ac = agents.get(ak)
                    if not ac:
                        return (tc_inner, ak, f"Agent '{ak}' not available", True, [])
                    res = await ac.send_task(task_text, context_text)
                    return (
                        tc_inner,
                        ak,
                        res.get("result", "No result"),
                        res.get("status") == "error",
                        res.get("tools_called", []),
                    )

                results = await asyncio.gather(*[_call_agent(tc) for tc in agent_calls])

                for (tc_r, ak, result_text, is_error, tools_called) in results:
                    completed_agents.append(ak)
                    yield {
                        "type": "agent_result",
                        "agent": ak,
                        "result": result_text,
                        "tools_called": tools_called if not is_error else [],
                        "is_error": is_error,
                    }
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_r.id,
                        "content": result_text if not is_error else f"ERROR: {result_text}",
                    })
            else:
                # Single agent - run sequentially
                tc = agent_calls[0]
                agent_key = TOOL_TO_AGENT[tc.function.name]
                tc_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                task = tc_args.get("task", "")
                context = tc_args.get("context", "")

                agent_client = agents.get(agent_key)
                if not agent_client:
                    result_text = f"Agent '{agent_key}' not available"
                    is_error = True
                    tools_called = []
                else:
                    result = await agent_client.send_task(task, context)
                    result_text = result.get("result", "No result")
                    is_error = result.get("status") == "error"
                    tools_called = result.get("tools_called", [])

                completed_agents.append(agent_key)
                yield {
                    "type": "agent_result",
                    "agent": agent_key,
                    "result": result_text,
                    "tools_called": tools_called if not is_error else [],
                    "is_error": is_error,
                }
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text if not is_error else f"ERROR: {result_text}",
                })

            continue

        else:
            # Final text response from the model
            final_text = msg.content or ""
            yield {"type": "synthesis_start"}
            yield {"type": "response", "text": final_text}
            return

    yield {"type": "error", "error": "Supervisor reached maximum turns without completing."}
