"""Activities & Attractions MCP Server - suggests things to do at destinations."""

import os
import logging
import hashlib
from fastmcp import FastMCP
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp_server = FastMCP(name="activities-mcp")

CITY_ACTIVITIES = {
    "tokyo": {
        "outdoor": ["Meiji Shrine & Yoyogi Park", "Senso-ji Temple in Asakusa", "Ueno Park & Zoo", "Imperial Palace East Gardens", "Odaiba seaside"],
        "indoor": ["TeamLab Borderless digital art", "Tsukiji Outer Market food tour", "Akihabara electronics & anime shops", "Tokyo National Museum", "Robot Restaurant in Shinjuku"],
        "food": ["Ramen at Ichiran Shibuya", "Sushi at Tsukiji Outer Market", "Yakitori in Yurakucho", "Tempura at Tsunahachi", "Matcha desserts in Asakusa"],
        "nightlife": ["Shibuya crossing & nightlife", "Golden Gai bar district", "Roppongi entertainment", "Shinjuku Kabukicho"],
        "day_trips": ["Mount Fuji (Hakone)", "Kamakura temples", "Nikko shrines", "Yokohama Chinatown"],
    },
    "paris": {
        "outdoor": ["Eiffel Tower & Champ de Mars", "Luxembourg Gardens", "Seine River walk", "Montmartre & Sacre-Coeur", "Tuileries Garden"],
        "indoor": ["Louvre Museum", "Musee d'Orsay", "Centre Pompidou", "Sainte-Chapelle", "Palais Garnier opera house"],
        "food": ["Croissants at Du Pain et des Idees", "Crepes in Montmartre", "Wine & cheese at Le Comptoir", "Macarons at Laduree", "Bistro dinner at Le Bouillon Chartier"],
        "nightlife": ["Le Marais cocktail bars", "Moulin Rouge show", "Jazz at Caveau de la Huchette", "Canal Saint-Martin evening"],
        "day_trips": ["Versailles Palace", "Giverny (Monet's gardens)", "Champagne region", "Loire Valley castles"],
    },
    "new york": {
        "outdoor": ["Central Park", "Brooklyn Bridge walk", "High Line elevated park", "Statue of Liberty & Ellis Island", "Times Square"],
        "indoor": ["Metropolitan Museum of Art", "MoMA", "Broadway show", "American Museum of Natural History", "One World Observatory"],
        "food": ["Pizza at Joe's", "Bagels at Russ & Daughters", "Dim sum in Chinatown", "Smorgasburg food market", "Steakhouse at Peter Luger"],
        "nightlife": ["Rooftop bars in Manhattan", "Jazz at Blue Note", "Comedy cellar in Greenwich Village", "Brooklyn nightlife"],
        "day_trips": ["Hudson Valley", "The Hamptons", "Bear Mountain hike", "Philadelphia"],
    },
    "london": {
        "outdoor": ["Hyde Park & Kensington Gardens", "Tower of London", "Borough Market", "Camden Market", "Thames South Bank walk"],
        "indoor": ["British Museum (free)", "Tate Modern (free)", "Natural History Museum (free)", "West End theatre show", "Churchill War Rooms"],
        "food": ["Fish & chips at Poppies", "Sunday roast at a pub", "Afternoon tea at The Ritz", "Brick Lane curry", "Full English breakfast"],
        "nightlife": ["Soho pub crawl", "Shoreditch bars", "Jazz at Ronnie Scott's", "Notting Hill wine bars"],
        "day_trips": ["Stonehenge & Bath", "Oxford", "Cambridge", "Windsor Castle"],
    },
    "bangkok": {
        "outdoor": ["Grand Palace & Wat Phra Kaew", "Wat Arun at sunset", "Chatuchak Weekend Market", "Lumpini Park", "Khlong boat tour"],
        "indoor": ["Jim Thompson House", "MOCA Bangkok", "Siam Paragon mall", "Thai cooking class", "Thai massage at Wat Pho"],
        "food": ["Street food on Yaowarat (Chinatown)", "Pad Thai at Thip Samai", "Som Tum at Som Tam Nua", "Mango sticky rice at Mae Varee", "Rooftop dinner at Vertigo"],
        "nightlife": ["Khao San Road", "Rooftop bars (Sky Bar, Octave)", "Thonglor nightlife", "Asiatique night market"],
        "day_trips": ["Ayutthaya ancient ruins", "Floating markets", "Erawan Falls", "Pattaya beaches"],
    },
    "reykjavik": {
        "outdoor": ["Golden Circle tour (Geysir, Gullfoss, Thingvellir)", "Blue Lagoon geothermal spa", "Northern Lights viewing", "Whale watching", "Hallgrimskirkja church viewpoint"],
        "indoor": ["Harpa Concert Hall", "National Museum of Iceland", "Perlan Museum", "Reykjavik Art Museum", "Kolaportid flea market"],
        "food": ["Hot dogs at Baejarins Beztu", "Lamb soup at Svarta Kaffid", "Fresh seafood at Grillid", "Skyr desserts", "Rye bread ice cream"],
        "nightlife": ["Laugavegur bar crawl", "Craft beer at Microbar", "Live music at Kex Hostel", "Cocktails at Slippbarinn"],
        "day_trips": ["Vik black sand beach", "Jokulsarlon glacier lagoon", "Snaefellsnes peninsula", "Ice cave tour"],
    },
}


def _get_city_data(city: str) -> dict:
    key = city.lower().strip()
    if key in CITY_ACTIVITIES:
        return CITY_ACTIVITIES[key]
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    return {
        "outdoor": [f"City park & gardens", f"Historic old town walk", f"Local market visit"],
        "indoor": [f"National museum", f"Art gallery", f"Cultural center"],
        "food": [f"Local cuisine restaurant", f"Street food market", f"Traditional cafe"],
        "nightlife": [f"Local bar district", f"Live music venue"],
        "day_trips": [f"Nearby historic site", f"Natural landmark"],
    }


def _get_activities(city: str, weather_conditions: str = "", category: str = "all") -> str:
    data = _get_city_data(city)
    weather_lower = weather_conditions.lower()
    is_rainy = any(w in weather_lower for w in ["rain", "shower", "storm"])
    is_cold = any(w in weather_lower for w in ["cold", "snow", "freez"]) or ("0c" in weather_lower or "-" in weather_lower)

    lines = [f"Recommended Activities for {city.title()}"]
    if weather_conditions:
        lines.append(f"(Adjusted for weather: {weather_conditions[:80]})")
    lines.append("")

    if category in ("all", "outdoor") and not is_rainy:
        lines.append("OUTDOOR ACTIVITIES:")
        for a in data.get("outdoor", []):
            lines.append(f"  - {a}")
        lines.append("")

    if category in ("all", "indoor") or is_rainy:
        label = "INDOOR ACTIVITIES (recommended due to weather):" if is_rainy else "INDOOR ACTIVITIES:"
        lines.append(label)
        for a in data.get("indoor", []):
            lines.append(f"  - {a}")
        lines.append("")

    if category in ("all", "food"):
        lines.append("FOOD & DINING:")
        for a in data.get("food", []):
            lines.append(f"  - {a}")
        lines.append("")

    if category in ("all", "nightlife"):
        lines.append("NIGHTLIFE & ENTERTAINMENT:")
        for a in data.get("nightlife", []):
            lines.append(f"  - {a}")
        lines.append("")

    if category in ("all", "day_trips"):
        lines.append("DAY TRIPS:")
        for a in data.get("day_trips", []):
            lines.append(f"  - {a}")

    if is_rainy:
        lines.append("")
        lines.append("TIP: Rain expected - prioritize indoor activities and covered markets.")
    if is_cold:
        lines.append("TIP: Cold weather - warm up at cafes and indoor attractions between outdoor visits.")

    return "\n".join(lines)


mcp_server.tool(_get_activities, name="get_activities")


# ---- REST API ----

rest_app = FastAPI(title="Activities MCP Server")


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


TOOL_MAP = {"get_activities": _get_activities}


@rest_app.get("/health")
async def health():
    return {"status": "healthy", "server": "activities-mcp"}


@rest_app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {
                "name": "get_activities",
                "description": "Get recommended activities, restaurants, and things to do at a destination. Can filter by category and adjust for weather.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "Destination city"},
                        "weather_conditions": {"type": "string", "description": "Optional weather summary to adjust recommendations"},
                        "category": {"type": "string", "description": "Filter: all, outdoor, indoor, food, nightlife, day_trips", "default": "all"},
                    },
                    "required": ["city"],
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
    title="Activities MCP Combined",
    routes=[*mcp_app.routes, *rest_app.routes],
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(combined_app, host="0.0.0.0", port=port)
