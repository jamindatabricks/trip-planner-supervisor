"""Weather Forecast MCP Server - provides mock weather data via MCP tools."""

import os
import logging
import hashlib
from datetime import datetime, timedelta
from fastmcp import FastMCP
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp_server = FastMCP(name="weather-mcp")

# Weather condition templates
CONDITIONS = ["Sunny", "Partly Cloudy", "Cloudy", "Light Rain", "Rain", "Thunderstorms", "Snow", "Foggy", "Windy", "Clear"]

# City climate profiles (base temps in Celsius for mid-February)
CITY_CLIMATES = {
    "tokyo": {"base_high": 10, "base_low": 2, "conditions_bias": [0, 1, 2, 3, 4, 9]},
    "paris": {"base_high": 8, "base_low": 2, "conditions_bias": [1, 2, 3, 4, 9]},
    "new york": {"base_high": 5, "base_low": -2, "conditions_bias": [1, 2, 5, 6, 9]},
    "london": {"base_high": 9, "base_low": 3, "conditions_bias": [1, 2, 3, 4, 7]},
    "sydney": {"base_high": 27, "base_low": 20, "conditions_bias": [0, 1, 0, 3, 9]},
    "bangkok": {"base_high": 34, "base_low": 25, "conditions_bias": [0, 0, 1, 3, 4]},
    "dubai": {"base_high": 26, "base_low": 16, "conditions_bias": [0, 0, 9, 1, 0]},
    "rome": {"base_high": 13, "base_low": 4, "conditions_bias": [0, 1, 2, 3, 9]},
    "cancun": {"base_high": 30, "base_low": 22, "conditions_bias": [0, 0, 1, 3, 9]},
    "reykjavik": {"base_high": 2, "base_low": -3, "conditions_bias": [2, 6, 8, 7, 9]},
}


def _city_hash(city: str, salt: str = "") -> int:
    return int(hashlib.md5((city.lower().strip() + salt).encode()).hexdigest(), 16)


def _get_climate(city: str) -> dict:
    key = city.lower().strip()
    if key in CITY_CLIMATES:
        return CITY_CLIMATES[key]
    h = _city_hash(city)
    return {
        "base_high": (h % 30) + 5,
        "base_low": (h % 20) - 5,
        "conditions_bias": [h % 10, (h >> 4) % 10, (h >> 8) % 10, (h >> 12) % 10, (h >> 16) % 10],
    }


def _get_weather_forecast(city: str, days: int = 7) -> str:
    """
    Get a multi-day weather forecast for a city.

    Args:
        city: City name (e.g., "Tokyo", "Paris", "New York")
        days: Number of days to forecast (1-14, default 7)

    Returns:
        Formatted weather forecast with daily high/low temps, conditions, and precipitation chance
    """
    logger.info(f"Getting weather forecast for {city}, {days} days")
    days = max(1, min(days, 14))
    climate = _get_climate(city)
    today = datetime.now()

    lines = [f"Weather Forecast for {city.title()} ({days} days):", ""]
    for i in range(days):
        day = today + timedelta(days=i)
        day_hash = _city_hash(city, str(i))
        temp_var = (day_hash % 7) - 3
        high_c = climate["base_high"] + temp_var
        low_c = climate["base_low"] + temp_var
        high_f = round(high_c * 9 / 5 + 32)
        low_f = round(low_c * 9 / 5 + 32)
        cond_idx = climate["conditions_bias"][day_hash % len(climate["conditions_bias"])]
        condition = CONDITIONS[cond_idx % len(CONDITIONS)]
        precip = 0
        if condition in ("Light Rain", "Rain", "Thunderstorms", "Snow"):
            precip = 40 + (day_hash % 50)
        elif condition in ("Cloudy", "Foggy"):
            precip = 10 + (day_hash % 30)
        else:
            precip = day_hash % 15
        humidity = 40 + (day_hash % 40)
        wind_kph = 5 + (day_hash % 25)

        day_name = day.strftime("%a %b %d")
        lines.append(
            f"  {day_name}: High {high_c}C/{high_f}F, Low {low_c}C/{low_f}F, "
            f"{condition}, Precip: {precip}%, Humidity: {humidity}%, Wind: {wind_kph} km/h"
        )

    avg_high = climate["base_high"]
    avg_low = climate["base_low"]
    lines.append("")
    lines.append(f"Average Temperature Range: {avg_low}C to {avg_high}C ({round(avg_low*9/5+32)}F to {round(avg_high*9/5+32)}F)")
    return "\n".join(lines)


mcp_server.tool(_get_weather_forecast, name="get_weather_forecast")


def _get_current_conditions(city: str) -> str:
    """
    Get current weather conditions for a city.

    Args:
        city: City name

    Returns:
        Current temperature, humidity, wind speed, and conditions
    """
    logger.info(f"Getting current conditions for {city}")
    climate = _get_climate(city)
    h = _city_hash(city, "current")
    temp_c = climate["base_high"] - (h % 5)
    temp_f = round(temp_c * 9 / 5 + 32)
    humidity = 45 + (h % 35)
    wind_kph = 5 + (h % 20)
    wind_dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    wind_dir = wind_dirs[h % len(wind_dirs)]
    cond_idx = climate["conditions_bias"][0]
    condition = CONDITIONS[cond_idx % len(CONDITIONS)]

    return (
        f"Current conditions for {city.title()}:\n"
        f"  Temperature: {temp_c}C / {temp_f}F\n"
        f"  Conditions: {condition}\n"
        f"  Humidity: {humidity}%\n"
        f"  Wind: {wind_kph} km/h {wind_dir}\n"
        f"  Updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}"
    )


mcp_server.tool(_get_current_conditions, name="get_current_conditions")


# ---- REST API wrapper for easy agent consumption ----

rest_app = FastAPI(title="Weather MCP Server")


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


TOOL_MAP = {
    "get_weather_forecast": _get_weather_forecast,
    "get_current_conditions": _get_current_conditions,
}


@rest_app.get("/health")
async def health():
    return {"status": "healthy", "server": "weather-mcp"}


@rest_app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {
                "name": "get_weather_forecast",
                "description": "Get a multi-day weather forecast for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name (e.g., Tokyo, Paris)"},
                        "days": {"type": "integer", "description": "Number of days to forecast (1-14, default 7)"},
                    },
                    "required": ["city"],
                },
            },
            {
                "name": "get_current_conditions",
                "description": "Get current weather conditions for a city",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "City name"},
                    },
                    "required": ["city"],
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
    title="Weather MCP Combined",
    routes=[*mcp_app.routes, *rest_app.routes],
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"Starting Weather MCP server on port {port}")
    uvicorn.run(combined_app, host="0.0.0.0", port=port)
