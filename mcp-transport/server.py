"""Transportation MCP Server - flight/train options and local transit info."""

import os
import logging
import hashlib
from fastmcp import FastMCP
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp_server = FastMCP(name="transport-mcp")

CITY_TRANSPORT = {
    "tokyo": {
        "airports": ["Narita International (NRT) - 60min to city", "Haneda (HND) - 30min to city (preferred)"],
        "from_airport": ["Narita Express train (NEX) ~$30", "Limousine bus ~$25", "Haneda monorail ~$5"],
        "local_transit": ["JR Lines (subway/rail) - get a Suica/Pasmo card", "Tokyo Metro - extensive coverage", "Buses - supplement to rail", "Taxis - expensive ($5-50+ per ride)"],
        "tips": ["Get a 72-hour Tokyo Metro pass ($15)", "JR Pass worth it for day trips", "Last trains around midnight", "Google Maps works great for navigation"],
        "intercity": ["Shinkansen (bullet train) to Osaka: 2.5hrs/$120", "Shinkansen to Kyoto: 2hrs/$110", "Bus to Mount Fuji area: 2hrs/$25"],
    },
    "paris": {
        "airports": ["Charles de Gaulle (CDG) - 45min to city", "Orly (ORY) - 30min to city"],
        "from_airport": ["RER B train from CDG ~$12", "Orlyval + Metro ~$12", "Airport bus ~$15", "Taxi flat rate ~$55-65"],
        "local_transit": ["Metro - 16 lines, covers everywhere", "RER - suburban express", "Buses - scenic but slower", "Velib bikes - short trips"],
        "tips": ["Get a Navigo weekly pass ($25)", "Metro runs 5:30am-1am", "Uber/Bolt available", "Walk - Paris is very walkable"],
        "intercity": ["Eurostar to London: 2.5hrs/$80-200", "TGV to Lyon: 2hrs/$40-80", "TGV to Nice: 5.5hrs/$50-100"],
    },
    "new york": {
        "airports": ["JFK International - 60min to Manhattan", "LaGuardia (LGA) - 30min to Manhattan", "Newark (EWR) - 45min to Manhattan"],
        "from_airport": ["AirTrain + subway from JFK ~$10", "Taxi/Uber from JFK ~$55-75", "NJ Transit from Newark ~$15"],
        "local_transit": ["Subway - 24/7 service, $2.90/ride", "Buses - supplement subway", "Citi Bike - short trips", "Uber/Lyft - widely available"],
        "tips": ["Get an OMNY card or use contactless", "Express vs local trains matter", "Avoid rush hour if possible", "Walk between nearby attractions"],
        "intercity": ["Amtrak to Boston: 4hrs/$50-150", "Amtrak to DC: 3.5hrs/$50-120", "Bus to Philadelphia: 2hrs/$15-30"],
    },
    "london": {
        "airports": ["Heathrow (LHR) - 45min to city", "Gatwick (LGW) - 60min to city", "Stansted (STN) - 60min to city"],
        "from_airport": ["Heathrow Express ~$28 (15min)", "Piccadilly Line from Heathrow ~$6 (60min)", "Gatwick Express ~$22 (30min)"],
        "local_transit": ["Underground (Tube) - extensive network", "Buses - iconic red double-deckers", "Overground/DLR - outer areas", "Black cabs - premium taxis"],
        "tips": ["Use contactless or Oyster card", "Tube runs 5am-midnight (24hr on weekends)", "Off-peak is cheaper", "Walk along the Thames - scenic"],
        "intercity": ["Eurostar to Paris: 2.5hrs/$80-200", "Train to Edinburgh: 4.5hrs/$40-120", "Train to Bath: 1.5hrs/$20-50"],
    },
    "bangkok": {
        "airports": ["Suvarnabhumi (BKK) - main international", "Don Mueang (DMK) - budget airlines"],
        "from_airport": ["Airport Rail Link ~$2 (30min)", "Taxi ~$10-15 (45min)", "Airport bus ~$2"],
        "local_transit": ["BTS Skytrain - modern, air-conditioned", "MRT Subway - connects to BTS", "Khlong boats - river transport", "Tuk-tuks - negotiate price first!"],
        "tips": ["Get a Rabbit card for BTS", "Grab app is the local Uber", "Traffic is terrible - use rail when possible", "Motorcycle taxis for short trips"],
        "intercity": ["Train to Chiang Mai: 12hrs/$15-40", "Bus to Pattaya: 2hrs/$5", "Flight to Phuket: 1.5hrs/$30-80"],
    },
    "reykjavik": {
        "airports": ["Keflavik International (KEF) - 45min to city"],
        "from_airport": ["Flybus shuttle ~$25 (45min)", "Taxi ~$120", "Rental car (recommended for Iceland)"],
        "local_transit": ["Stranto buses - city routes", "Walking - city center is compact", "Rental car - essential for exploring beyond city"],
        "tips": ["Rent a car if visiting the Golden Circle or Ring Road", "City is very walkable", "No trains in Iceland", "Book car rental early - limited supply"],
        "intercity": ["Drive to Vik: 2.5hrs", "Drive to Akureyri: 5hrs", "Domestic flights to Akureyri: 45min/$80-150"],
    },
}


def _get_transport(city: str) -> dict:
    key = city.lower().strip()
    if key in CITY_TRANSPORT:
        return CITY_TRANSPORT[key]
    return {
        "airports": [f"Main international airport"],
        "from_airport": ["Taxi or ride-share", "Public transit if available"],
        "local_transit": ["Local bus system", "Taxis", "Ride-share apps"],
        "tips": ["Research local transit cards", "Download offline maps"],
        "intercity": ["Check local rail and bus options"],
    }


def _get_travel_options(destination: str, origin: str = "US") -> str:
    """
    Get transportation information for getting to and around a destination.

    Args:
        destination: City name
        origin: Where traveler is coming from (default: US)

    Returns:
        Comprehensive transportation guide including airports, local transit, and intercity options
    """
    logger.info(f"Getting transport info for {destination} from {origin}")
    data = _get_transport(destination)

    lines = [f"Transportation Guide: {destination.title()}", ""]

    lines.append("AIRPORTS:")
    for a in data.get("airports", []):
        lines.append(f"  - {a}")

    lines.append("")
    lines.append("GETTING FROM AIRPORT TO CITY:")
    for a in data.get("from_airport", []):
        lines.append(f"  - {a}")

    lines.append("")
    lines.append("LOCAL TRANSPORTATION:")
    for a in data.get("local_transit", []):
        lines.append(f"  - {a}")

    lines.append("")
    lines.append("TRANSPORT TIPS:")
    for a in data.get("tips", []):
        lines.append(f"  - {a}")

    lines.append("")
    lines.append("INTERCITY / DAY TRIP OPTIONS:")
    for a in data.get("intercity", []):
        lines.append(f"  - {a}")

    return "\n".join(lines)


mcp_server.tool(_get_travel_options, name="get_travel_options")


# ---- REST API ----

rest_app = FastAPI(title="Transport MCP Server")


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


TOOL_MAP = {"get_travel_options": _get_travel_options}


@rest_app.get("/health")
async def health():
    return {"status": "healthy", "server": "transport-mcp"}


@rest_app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {
                "name": "get_travel_options",
                "description": "Get transportation guide for a destination including airports, local transit, and intercity options",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "destination": {"type": "string", "description": "City name"},
                        "origin": {"type": "string", "description": "Where traveler is from", "default": "US"},
                    },
                    "required": ["destination"],
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
    title="Transport MCP Combined",
    routes=[*mcp_app.routes, *rest_app.routes],
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(combined_app, host="0.0.0.0", port=port)
