"""
Concrete tool implementations for the tool_loop example.

Two simple tools:
  - get_weather: returns canned weather data (no external API)
  - get_time:    returns real current time via stdlib datetime
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from flatagents import Tool, ToolResult


_WEATHER_DATA: Dict[str, Dict[str, Any]] = {
    "tokyo": {"temp_f": 68, "condition": "partly cloudy"},
    "new york": {"temp_f": 55, "condition": "overcast"},
    "london": {"temp_f": 50, "condition": "rainy"},
    "san francisco": {"temp_f": 62, "condition": "foggy"},
    "paris": {"temp_f": 58, "condition": "sunny"},
    "sydney": {"temp_f": 75, "condition": "clear skies"},
}


async def _get_weather(tool_call_id: str, args: Dict[str, Any]) -> ToolResult:
    city = args.get("city", "").strip().lower()
    data = _WEATHER_DATA.get(city)
    if data is None:
        known = ", ".join(sorted(_WEATHER_DATA))
        return ToolResult(
            content=f"No weather data for '{city}'. Known cities: {known}",
            is_error=True,
        )

    return ToolResult(content=f"{data['temp_f']}°F and {data['condition']} in {city.title()}")


weather_tool = Tool(
    name="get_weather",
    description="Get the current weather for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name, e.g. 'Tokyo' or 'New York'",
            }
        },
        "required": ["city"],
    },
    execute=_get_weather,
)


_TIMEZONE_OFFSETS: Dict[str, int] = {
    "utc": 0,
    "us/eastern": -5,
    "us/central": -6,
    "us/mountain": -7,
    "us/pacific": -8,
    "europe/london": 0,
    "europe/paris": 1,
    "europe/berlin": 1,
    "asia/tokyo": 9,
    "asia/shanghai": 8,
    "australia/sydney": 11,
}


async def _get_time(tool_call_id: str, args: Dict[str, Any]) -> ToolResult:
    tz_name = args.get("timezone", "utc").strip().lower()
    offset_hours = _TIMEZONE_OFFSETS.get(tz_name)
    if offset_hours is None:
        known = ", ".join(sorted(_TIMEZONE_OFFSETS))
        return ToolResult(
            content=f"Unknown timezone '{tz_name}'. Known timezones: {known}",
            is_error=True,
        )

    tz = timezone(timedelta(hours=offset_hours))
    now = datetime.now(tz)
    return ToolResult(content=f"{now.strftime('%Y-%m-%d %H:%M:%S %Z')} ({tz_name})")


time_tool = Tool(
    name="get_time",
    description="Get the current time in a given timezone.",
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": "Timezone identifier, e.g. 'UTC', 'US/Pacific', 'Asia/Tokyo', 'Europe/London'",
            }
        },
        "required": ["timezone"],
    },
    execute=_get_time,
)


ALL_TOOLS = [weather_tool, time_tool]
