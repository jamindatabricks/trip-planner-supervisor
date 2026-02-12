"""Budget & Cost Estimation MCP Server - estimates trip costs."""

import os
import logging
import hashlib
from fastmcp import FastMCP
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp_server = FastMCP(name="budget-mcp")

# Cost profiles per city (daily averages in USD)
CITY_COSTS = {
    "tokyo": {"hotel_budget": 80, "hotel_mid": 180, "hotel_luxury": 400, "food": 50, "transport_local": 15, "activities": 30, "flight_from_us": 900, "currency": "JPY", "exchange_rate": 150.5},
    "paris": {"hotel_budget": 100, "hotel_mid": 220, "hotel_luxury": 500, "food": 60, "transport_local": 12, "activities": 35, "flight_from_us": 700, "currency": "EUR", "exchange_rate": 0.92},
    "new york": {"hotel_budget": 150, "hotel_mid": 300, "hotel_luxury": 600, "food": 65, "transport_local": 10, "activities": 40, "flight_from_us": 300, "currency": "USD", "exchange_rate": 1.0},
    "london": {"hotel_budget": 120, "hotel_mid": 250, "hotel_luxury": 550, "food": 55, "transport_local": 15, "activities": 35, "flight_from_us": 650, "currency": "GBP", "exchange_rate": 0.79},
    "bangkok": {"hotel_budget": 30, "hotel_mid": 80, "hotel_luxury": 200, "food": 15, "transport_local": 5, "activities": 15, "flight_from_us": 800, "currency": "THB", "exchange_rate": 35.2},
    "sydney": {"hotel_budget": 90, "hotel_mid": 200, "hotel_luxury": 450, "food": 50, "transport_local": 12, "activities": 30, "flight_from_us": 1100, "currency": "AUD", "exchange_rate": 1.55},
    "dubai": {"hotel_budget": 70, "hotel_mid": 180, "hotel_luxury": 500, "food": 40, "transport_local": 10, "activities": 45, "flight_from_us": 850, "currency": "AED", "exchange_rate": 3.67},
    "rome": {"hotel_budget": 80, "hotel_mid": 180, "hotel_luxury": 400, "food": 45, "transport_local": 8, "activities": 25, "flight_from_us": 650, "currency": "EUR", "exchange_rate": 0.92},
    "cancun": {"hotel_budget": 60, "hotel_mid": 150, "hotel_luxury": 350, "food": 30, "transport_local": 8, "activities": 35, "flight_from_us": 400, "currency": "MXN", "exchange_rate": 17.2},
    "reykjavik": {"hotel_budget": 120, "hotel_mid": 250, "hotel_luxury": 450, "food": 70, "transport_local": 20, "activities": 80, "flight_from_us": 600, "currency": "ISK", "exchange_rate": 137.5},
}


def _get_costs(city: str) -> dict:
    key = city.lower().strip()
    if key in CITY_COSTS:
        return CITY_COSTS[key]
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return {
        "hotel_budget": 50 + (h % 80), "hotel_mid": 120 + (h % 150),
        "hotel_luxury": 300 + (h % 300), "food": 25 + (h % 45),
        "transport_local": 5 + (h % 15), "activities": 15 + (h % 40),
        "flight_from_us": 400 + (h % 800), "currency": "USD", "exchange_rate": 1.0,
    }


def _estimate_trip_cost(
    destination: str,
    duration_days: int,
    budget_level: str = "mid",
    num_travelers: int = 1,
    include_flights: bool = True,
) -> str:
    """
    Estimate total trip cost for a destination.

    Args:
        destination: City name
        duration_days: Number of days
        budget_level: "budget", "mid", or "luxury"
        num_travelers: Number of people traveling
        include_flights: Whether to include round-trip flight estimates

    Returns:
        Detailed cost breakdown with daily and total estimates
    """
    logger.info(f"Estimating cost for {destination}, {duration_days} days, {budget_level}")
    costs = _get_costs(destination)
    budget_level = budget_level.lower()
    if budget_level not in ("budget", "mid", "luxury"):
        budget_level = "mid"

    hotel_key = f"hotel_{budget_level}"
    hotel_per_night = costs[hotel_key]
    food_daily = costs["food"]
    transport_daily = costs["transport_local"]
    activities_daily = costs["activities"]

    if budget_level == "budget":
        food_daily = int(food_daily * 0.6)
        activities_daily = int(activities_daily * 0.5)
    elif budget_level == "luxury":
        food_daily = int(food_daily * 1.8)
        activities_daily = int(activities_daily * 1.5)

    daily_total = hotel_per_night + food_daily + transport_daily + activities_daily
    trip_subtotal = daily_total * duration_days
    flight_cost = costs["flight_from_us"] if include_flights else 0
    flight_total = flight_cost * num_travelers
    total_per_person = trip_subtotal + flight_cost
    grand_total = (trip_subtotal * num_travelers) + flight_total

    # Note: hotel cost is per room, not per person (assume shared)
    hotel_total = hotel_per_night * duration_days
    grand_total = hotel_total + ((food_daily + transport_daily + activities_daily) * duration_days * num_travelers) + flight_total

    lines = [
        f"Trip Cost Estimate: {destination.title()} ({duration_days} days, {budget_level} level)",
        f"Travelers: {num_travelers}",
        f"Local currency: {costs['currency']} (1 USD = {costs['exchange_rate']} {costs['currency']})",
        "",
        "DAILY COST BREAKDOWN (per person):",
        f"  Accommodation ({budget_level}): ${hotel_per_night}/night",
        f"  Food & dining:     ${food_daily}/day",
        f"  Local transport:   ${transport_daily}/day",
        f"  Activities:        ${activities_daily}/day",
        f"  Daily total:       ${daily_total}/day",
        "",
        f"TRIP TOTAL ({duration_days} days):",
        f"  Accommodation:     ${hotel_per_night * duration_days}",
        f"  Food ({num_travelers}x):     ${food_daily * duration_days * num_travelers}",
        f"  Transport ({num_travelers}x): ${transport_daily * duration_days * num_travelers}",
        f"  Activities ({num_travelers}x):${activities_daily * duration_days * num_travelers}",
    ]
    if include_flights:
        lines.append(f"  Flights ({num_travelers}x RT):  ${flight_total}")
    lines.append(f"  ---")
    lines.append(f"  GRAND TOTAL:       ${grand_total}")
    lines.append("")

    if budget_level == "budget":
        lines.append("BUDGET TIPS:")
        lines.append("  - Stay in hostels or budget hotels")
        lines.append("  - Eat at local street food stalls and markets")
        lines.append("  - Use public transport and walk")
        lines.append("  - Visit free attractions and parks")
    elif budget_level == "luxury":
        lines.append("LUXURY PERKS:")
        lines.append("  - 4-5 star hotels with premium amenities")
        lines.append("  - Fine dining and exclusive restaurants")
        lines.append("  - Private tours and premium experiences")

    return "\n".join(lines)


mcp_server.tool(_estimate_trip_cost, name="estimate_trip_cost")


# ---- REST API ----

rest_app = FastAPI(title="Budget MCP Server")


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


TOOL_MAP = {"estimate_trip_cost": _estimate_trip_cost}


@rest_app.get("/health")
async def health():
    return {"status": "healthy", "server": "budget-mcp"}


@rest_app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {
                "name": "estimate_trip_cost",
                "description": "Estimate total trip cost with breakdown by accommodation, food, transport, activities, and flights",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "destination": {"type": "string", "description": "City name"},
                        "duration_days": {"type": "integer", "description": "Number of days"},
                        "budget_level": {"type": "string", "description": "budget, mid, or luxury", "default": "mid"},
                        "num_travelers": {"type": "integer", "description": "Number of travelers", "default": 1},
                        "include_flights": {"type": "boolean", "description": "Include flight estimates", "default": True},
                    },
                    "required": ["destination", "duration_days"],
                },
            }
        ]
    }


@rest_app.post("/api/call")
async def call_tool(request: ToolCallRequest):
    fn = TOOL_MAP.get(request.name)
    if not fn:
        return {"result": f"Unknown tool: {request.name}", "isError": True}
    try:
        result = fn(**request.arguments)
        return {"result": result, "isError": False}
    except Exception as e:
        logger.error(f"Tool call error: {e}")
        return {"result": str(e), "isError": True}


mcp_app = mcp_server.http_app()
combined_app = FastAPI(
    title="Budget MCP Combined",
    routes=[*mcp_app.routes, *rest_app.routes],
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(combined_app, host="0.0.0.0", port=port)
