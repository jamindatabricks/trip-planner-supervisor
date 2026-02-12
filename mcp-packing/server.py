"""Packing Recommendation MCP Server - provides packing lists based on weather/destination."""

import os
import logging
import hashlib
from fastmcp import FastMCP
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp_server = FastMCP(name="packing-mcp")

# Destination tips database
DESTINATION_TIPS = {
    "tokyo": {
        "cultural": ["Remove shoes when entering homes/temples", "Carry cash - many places don't accept cards", "Bow when greeting people"],
        "practical": ["Get a Suica/Pasmo card for trains", "Power outlets are Type A (US-style), 100V", "Convenience stores (konbini) are everywhere"],
        "currency": "Japanese Yen (JPY)",
    },
    "paris": {
        "cultural": ["Greet shopkeepers with 'Bonjour'", "Dress smart-casual for restaurants", "Tipping is not required but appreciated"],
        "practical": ["Metro is the best way to get around", "Power outlets are Type C/E (EU-style), 220V", "Many museums closed on Tuesdays"],
        "currency": "Euro (EUR)",
    },
    "new york": {
        "cultural": ["Tipping 18-20% is standard", "Walk on the right side of sidewalks", "Subway runs 24/7"],
        "practical": ["Get a MetroCard or use OMNY", "Power outlets are Type A/B, 120V", "Uber/Lyft widely available"],
        "currency": "US Dollar (USD)",
    },
    "london": {
        "cultural": ["Queue politely - it matters", "Stand on the right on escalators", "Tipping 10-15% at restaurants"],
        "practical": ["Get an Oyster card or use contactless", "Power outlets are Type G (UK), 230V", "Carry an umbrella always"],
        "currency": "British Pound (GBP)",
    },
    "bangkok": {
        "cultural": ["Remove shoes at temples", "Don't touch people's heads", "Show respect to the monarchy"],
        "practical": ["BTS Skytrain is fast and air-conditioned", "Power outlets are Type A/B/C, 220V", "Bargaining is expected at markets"],
        "currency": "Thai Baht (THB)",
    },
    "sydney": {
        "cultural": ["Casual dress is accepted most places", "Tipping is not expected", "Slip, Slop, Slap - sun protection is essential"],
        "practical": ["Get an Opal card for transit", "Power outlets are Type I (Australian), 230V", "Tap water is safe to drink"],
        "currency": "Australian Dollar (AUD)",
    },
}


def _detect_weather(weather_summary: str) -> dict:
    lower = weather_summary.lower()
    return {
        "rainy": any(w in lower for w in ["rain", "shower", "precip", "thunderstorm"]),
        "cold": any(w in lower for w in ["cold", "snow", "freeze", "below"]) or _extract_temp(lower) < 10,
        "hot": any(w in lower for w in ["hot", "warm", "heat"]) or _extract_temp(lower) > 28,
        "sunny": any(w in lower for w in ["sunny", "clear", "sun"]),
        "windy": any(w in lower for w in ["wind", "gust", "breezy"]),
        "snowy": "snow" in lower,
    }


def _extract_temp(text: str) -> float:
    """Try to extract a temperature in Celsius from text."""
    import re
    matches = re.findall(r"(\-?\d+)\s*C", text, re.IGNORECASE)
    if matches:
        temps = [int(m) for m in matches]
        return max(temps)
    return 15  # default moderate


def _get_packing_list(
    destination: str,
    duration_days: int,
    weather_summary: str,
    trip_type: str = "leisure",
) -> str:
    """
    Generate a comprehensive packing recommendation list based on destination, weather, and trip type.

    Args:
        destination: Trip destination city
        duration_days: Number of days for the trip
        weather_summary: Summary of expected weather conditions (from weather forecast)
        trip_type: Type of trip - "leisure", "business", or "adventure"

    Returns:
        Categorized packing list with item recommendations and quantities
    """
    logger.info(f"Generating packing list for {destination}, {duration_days} days, {trip_type}")
    weather = _detect_weather(weather_summary)
    lines = [f"Packing List for {destination.title()} ({duration_days}-day {trip_type} trip)", ""]

    # Clothing
    lines.append("CLOTHING:")
    base_tops = max(3, duration_days // 2 + 1)
    base_bottoms = max(2, duration_days // 3 + 1)

    if weather["cold"]:
        lines.append(f"  - Warm jacket / winter coat: 1")
        lines.append(f"  - Sweaters / fleece layers: {min(base_tops, 3)}")
        lines.append(f"  - Long-sleeve shirts: {base_tops}")
        lines.append(f"  - Warm pants / jeans: {base_bottoms}")
        lines.append(f"  - Thermal underwear: 2 sets")
        lines.append(f"  - Warm socks: {base_tops + 1} pairs")
        lines.append(f"  - Scarf, gloves, warm hat: 1 each")
    elif weather["hot"]:
        lines.append(f"  - Light t-shirts / tank tops: {base_tops + 1}")
        lines.append(f"  - Shorts: {base_bottoms}")
        lines.append(f"  - Light pants / skirts: {max(2, base_bottoms - 1)}")
        lines.append(f"  - Light socks: {base_tops} pairs")
        lines.append(f"  - Sandals: 1 pair")
        lines.append(f"  - Sun hat: 1")
    else:
        lines.append(f"  - T-shirts / casual tops: {base_tops}")
        lines.append(f"  - Light jacket / cardigan: 1")
        lines.append(f"  - Pants / jeans: {base_bottoms}")
        lines.append(f"  - Socks: {base_tops} pairs")

    lines.append(f"  - Underwear: {duration_days + 1}")
    lines.append(f"  - Comfortable walking shoes: 1 pair")
    lines.append(f"  - Sleepwear: 1-2 sets")

    if weather["rainy"]:
        lines.append("")
        lines.append("RAIN GEAR:")
        lines.append("  - Waterproof jacket / rain coat: 1")
        lines.append("  - Compact umbrella: 1")
        lines.append("  - Waterproof shoes or shoe covers: 1 pair")

    if weather["snowy"]:
        lines.append("")
        lines.append("SNOW GEAR:")
        lines.append("  - Waterproof boots: 1 pair")
        lines.append("  - Hand warmers: 3-5 packs")

    if weather["sunny"]:
        lines.append("")
        lines.append("SUN PROTECTION:")
        lines.append("  - Sunscreen SPF 30+: 1 bottle")
        lines.append("  - Sunglasses: 1 pair")

    # Toiletries
    lines.append("")
    lines.append("TOILETRIES:")
    lines.append("  - Toothbrush & toothpaste")
    lines.append("  - Shampoo & conditioner (travel size)")
    lines.append("  - Deodorant")
    lines.append("  - Skincare essentials")
    if weather["hot"] or weather["sunny"]:
        lines.append("  - Lip balm with SPF")
        lines.append("  - Aloe vera gel (for sunburn)")
    if weather["cold"]:
        lines.append("  - Moisturizer (cold weather dries skin)")
        lines.append("  - Lip balm")

    # Electronics
    lines.append("")
    lines.append("ELECTRONICS:")
    lines.append("  - Phone + charger")
    lines.append("  - Power adapter (check destination plug type)")
    lines.append("  - Portable battery pack")
    lines.append("  - Camera (optional)")

    # Travel essentials
    lines.append("")
    lines.append("TRAVEL ESSENTIALS:")
    lines.append("  - Passport / ID")
    lines.append("  - Travel insurance documents")
    lines.append("  - Copies of reservations")
    lines.append("  - Local currency or travel card")
    lines.append("  - Reusable water bottle")
    lines.append("  - Day bag / backpack")

    if trip_type == "business":
        lines.append("")
        lines.append("BUSINESS:")
        lines.append("  - Formal outfit: 2-3 sets")
        lines.append("  - Dress shoes: 1 pair")
        lines.append("  - Laptop + charger")
        lines.append("  - Business cards")
        lines.append("  - Notebook & pen")
    elif trip_type == "adventure":
        lines.append("")
        lines.append("ADVENTURE GEAR:")
        lines.append("  - Hiking shoes / boots: 1 pair")
        lines.append("  - Quick-dry clothing: 2-3 sets")
        lines.append("  - First aid kit")
        lines.append("  - Headlamp / flashlight")
        lines.append("  - Dry bags for electronics")

    # Destination tips
    dest_key = destination.lower().strip()
    tips = DESTINATION_TIPS.get(dest_key)
    if tips:
        lines.append("")
        lines.append(f"DESTINATION TIPS ({destination.title()}):")
        lines.append(f"  Currency: {tips['currency']}")
        for tip in tips.get("practical", []):
            lines.append(f"  - {tip}")
        for tip in tips.get("cultural", []):
            lines.append(f"  - {tip}")

    return "\n".join(lines)


mcp_server.tool(_get_packing_list, name="get_packing_list")


def _get_destination_tips(destination: str) -> str:
    """
    Get destination-specific packing tips and cultural considerations.

    Args:
        destination: City or country name

    Returns:
        Tips about local customs, power adapters, currency, and practical advice
    """
    logger.info(f"Getting destination tips for {destination}")
    dest_key = destination.lower().strip()
    tips = DESTINATION_TIPS.get(dest_key)

    if not tips:
        h = int(hashlib.md5(dest_key.encode()).hexdigest(), 16)
        plug_types = ["Type A/B (US)", "Type C/E (EU)", "Type G (UK)", "Type I (AU)"]
        return (
            f"Destination Tips for {destination.title()}:\n"
            f"  - Check visa requirements before traveling\n"
            f"  - Power adapter: likely {plug_types[h % len(plug_types)]}\n"
            f"  - Research local tipping customs\n"
            f"  - Download offline maps\n"
            f"  - Learn a few basic phrases in the local language"
        )

    lines = [f"Destination Tips for {destination.title()}:", ""]
    lines.append(f"Currency: {tips['currency']}")
    lines.append("")
    lines.append("Cultural Tips:")
    for tip in tips.get("cultural", []):
        lines.append(f"  - {tip}")
    lines.append("")
    lines.append("Practical Tips:")
    for tip in tips.get("practical", []):
        lines.append(f"  - {tip}")
    return "\n".join(lines)


mcp_server.tool(_get_destination_tips, name="get_destination_tips")


# ---- REST API wrapper ----

rest_app = FastAPI(title="Packing MCP Server")


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


TOOL_MAP = {
    "get_packing_list": _get_packing_list,
    "get_destination_tips": _get_destination_tips,
}


@rest_app.get("/health")
async def health():
    return {"status": "healthy", "server": "packing-mcp"}


@rest_app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {
                "name": "get_packing_list",
                "description": "Generate a packing list based on destination, weather, and trip type",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "destination": {"type": "string", "description": "Trip destination city"},
                        "duration_days": {"type": "integer", "description": "Number of trip days"},
                        "weather_summary": {"type": "string", "description": "Weather forecast summary"},
                        "trip_type": {"type": "string", "description": "leisure, business, or adventure"},
                    },
                    "required": ["destination", "duration_days", "weather_summary"],
                },
            },
            {
                "name": "get_destination_tips",
                "description": "Get destination-specific tips and cultural considerations",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "destination": {"type": "string", "description": "City or country name"},
                    },
                    "required": ["destination"],
                },
            },
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


# ---- Combine MCP + REST ----

mcp_app = mcp_server.http_app()

combined_app = FastAPI(
    title="Packing MCP Combined",
    routes=[*mcp_app.routes, *rest_app.routes],
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Packing MCP server on port {port}")
    uvicorn.run(combined_app, host="0.0.0.0", port=port)
