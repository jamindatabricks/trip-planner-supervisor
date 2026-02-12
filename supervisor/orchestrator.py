"""LangGraph supervisor orchestrator - uses a StateGraph with ChatDatabricks to coordinate agents."""

import asyncio
import json
import logging
from typing import AsyncGenerator, Annotated, TypedDict

from langchain_core.tools import tool
from langchain_core.messages import AIMessage, ToolMessage, SystemMessage, HumanMessage
from databricks_langchain import ChatDatabricks
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from config import FMAPI_MODEL
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


# --- Tool definitions ---

class PlanStep(BaseModel):
    agent: str = Field(description="Agent to call: weather, packing, activities, budget, or transport")
    reason: str = Field(description="Brief reason for calling this agent")


class CreatePlanInput(BaseModel):
    steps: list[PlanStep] = Field(description="Ordered list of agents to call with reasons")


@tool(args_schema=CreatePlanInput)
async def create_plan(steps: list[PlanStep]) -> str:
    """Announce which agents you will call and in what order. ALWAYS call this first before calling any agent tools."""
    agent_names = [s.agent for s in steps]
    return f"Plan confirmed. Proceeding with agents: {', '.join(agent_names)}. Remember to call independent agents in parallel by issuing multiple tool calls in a single response."


@tool
async def call_weather_agent(task: str) -> str:
    """Get weather forecast for a destination. Call when the question involves weather, outdoor plans, or when packing/activities agents need weather context."""
    result = await agents["weather"].send_task(task)
    return json.dumps({"text": result.get("result", "No result"), "tools_called": result.get("tools_called", []), "is_error": result.get("status") == "error"})


@tool
async def call_packing_agent(task: str, context: str = "") -> str:
    """Get packing recommendations. Best when given weather context. Call after weather agent if both are needed."""
    result = await agents["packing"].send_task(task, context)
    return json.dumps({"text": result.get("result", "No result"), "tools_called": result.get("tools_called", []), "is_error": result.get("status") == "error"})


@tool
async def call_activities_agent(task: str, context: str = "") -> str:
    """Get activity and sightseeing recommendations. Can adjust for weather if context is provided."""
    result = await agents["activities"].send_task(task, context)
    return json.dumps({"text": result.get("result", "No result"), "tools_called": result.get("tools_called", []), "is_error": result.get("status") == "error"})


@tool
async def call_budget_agent(task: str) -> str:
    """Get trip cost estimates. Independent - does not need weather context. Can be called in parallel with other agents."""
    result = await agents["budget"].send_task(task)
    return json.dumps({"text": result.get("result", "No result"), "tools_called": result.get("tools_called", []), "is_error": result.get("status") == "error"})


@tool
async def call_transport_agent(task: str) -> str:
    """Get transportation information (flights, local transit, getting around). Independent - does not need weather context. Can be called in parallel with other agents."""
    result = await agents["transport"].send_task(task)
    return json.dumps({"text": result.get("result", "No result"), "tools_called": result.get("tools_called", []), "is_error": result.get("status") == "error"})


# --- LangGraph State and Graph ---

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

ALL_TOOLS = [create_plan, call_weather_agent, call_packing_agent, call_activities_agent, call_budget_agent, call_transport_agent]


class SupervisorState(TypedDict):
    messages: Annotated[list, add_messages]


# Build the LangGraph state graph
model = ChatDatabricks(endpoint=FMAPI_MODEL)
model_with_tools = model.bind_tools(ALL_TOOLS)


async def supervisor_node(state):
    """LLM decides next action - which agents to call or synthesize final answer."""
    response = await model_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}


def should_continue(state):
    """Route: if the LLM made tool calls, go to tools node. Otherwise, end."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ToolNode handles parallel execution of multiple tool calls automatically
tool_node = ToolNode(ALL_TOOLS)

graph_builder = StateGraph(SupervisorState)
graph_builder.add_node("supervisor", supervisor_node)
graph_builder.add_node("tools", tool_node)
graph_builder.add_edge(START, "supervisor")
graph_builder.add_conditional_edges("supervisor", should_continue, {"tools": "tools", END: END})
graph_builder.add_edge("tools", "supervisor")

supervisor_graph = graph_builder.compile()


# --- SSE Orchestration ---

async def orchestrate(user_message: str) -> AsyncGenerator[dict, None]:
    """
    Run the LangGraph supervisor and yield SSE events for the frontend.
    Uses astream with stream_mode='updates' to intercept each node's output.
    """
    yield {"type": "status", "message": "Planning which agents to use..."}

    initial_messages = [
        SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]

    planned_agents = []
    completed_agents = []

    try:
        async for chunk in supervisor_graph.astream(
            {"messages": initial_messages},
            stream_mode="updates",
        ):
            for node_name, state_update in chunk.items():
                new_messages = state_update.get("messages", [])

                if node_name == "supervisor":
                    for msg in new_messages:
                        if not isinstance(msg, AIMessage):
                            continue

                        if msg.tool_calls:
                            # Separate plan calls from agent calls
                            plan_calls = [tc for tc in msg.tool_calls if tc["name"] == "create_plan"]
                            agent_calls = [tc for tc in msg.tool_calls if tc["name"] in TOOL_TO_AGENT]

                            # Handle plan
                            for tc in plan_calls:
                                steps = tc.get("args", {}).get("steps", [])
                                # Steps may be PlanStep objects or dicts
                                step_dicts = []
                                for s in steps:
                                    if isinstance(s, dict):
                                        step_dicts.append(s)
                                    else:
                                        step_dicts.append({"agent": s.agent, "reason": s.reason})
                                planned_agents = [s["agent"] for s in step_dicts]
                                logger.info(f"Plan: {planned_agents}")
                                yield {
                                    "type": "plan",
                                    "steps": step_dicts,
                                    "agents": planned_agents,
                                }

                            # Handle agent calls - emit round_start + agent_start
                            if agent_calls:
                                agent_keys = [TOOL_TO_AGENT[tc["name"]] for tc in agent_calls]

                                # Check for unplanned agents
                                for ak in agent_keys:
                                    if ak not in planned_agents:
                                        planned_agents.append(ak)
                                        yield {
                                            "type": "plan_update",
                                            "agents": planned_agents,
                                            "added": ak,
                                            "reason": f"Supervisor decided to also consult {AGENT_DISPLAY_NAMES[ak]}",
                                        }

                                is_parallel = len(agent_calls) > 1
                                yield {
                                    "type": "round_start",
                                    "agents": agent_keys,
                                    "parallel": is_parallel,
                                }

                                for tc in agent_calls:
                                    ak = TOOL_TO_AGENT[tc["name"]]
                                    task_text = tc.get("args", {}).get("task", "")
                                    yield {
                                        "type": "agent_start",
                                        "agent": ak,
                                        "task": task_text[:150],
                                    }

                        elif msg.content:
                            # Final synthesis response (no tool calls)
                            yield {"type": "synthesis_start"}
                            yield {"type": "response", "text": msg.content}

                elif node_name == "tools":
                    # Tool results - emit agent_result for each agent tool
                    for msg in new_messages:
                        if not isinstance(msg, ToolMessage):
                            continue

                        # Find which tool this result is for
                        tool_name = msg.name if hasattr(msg, "name") else ""
                        if tool_name not in TOOL_TO_AGENT:
                            continue

                        ak = TOOL_TO_AGENT[tool_name]
                        completed_agents.append(ak)

                        # Parse the JSON result from our tool functions
                        try:
                            result_data = json.loads(msg.content)
                            result_text = result_data.get("text", msg.content)
                            tools_called = result_data.get("tools_called", [])
                            is_error = result_data.get("is_error", False)
                        except (json.JSONDecodeError, AttributeError):
                            result_text = str(msg.content)
                            tools_called = []
                            is_error = False

                        yield {
                            "type": "agent_result",
                            "agent": ak,
                            "result": result_text,
                            "tools_called": tools_called if not is_error else [],
                            "is_error": is_error,
                        }

    except Exception as e:
        logger.error(f"Orchestration error: {e}")
        yield {"type": "error", "error": f"Orchestration error: {e}"}
        return

    if not any(ak in completed_agents for ak in TOOL_TO_AGENT.values()):
        # No agents were called - might be a direct response
        pass
