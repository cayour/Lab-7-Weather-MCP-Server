import asyncio
import httpx
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server

# Create and initialize the server object
server = Server("weather-server")

# NWS requires a User-Agent header to identify your app
NWS_HEADERS = {
    "User-Agent": "weather-mcp-server/1.0",
    "Accept": "application/geo+json"
}

# --- 1. Define the Logic ---

async def get_forecast(latitude, longitude):
    """
    Fetches the weather forecast for a specific location from the NWS API.

    Args:
        latitude (float): The latitude of the location.
        longitude (float): The longitude of the location.

    Returns:
        str: A formatted string containing the forecast for the next few periods.
    """
    async with httpx.AsyncClient() as client:
        # Step 1: Get the Grid Point (NWS requires converting Lat/Long to a Grid ID)
        # We round coordinates to 4 decimal places to avoid API errors
        lat_clean = f"{float(latitude):.4f}"
        long_clean = f"{float(longitude):.4f}"
        points_url = f"https://api.weather.gov/points/{lat_clean},{long_clean}"
        
        response = await client.get(points_url, headers=NWS_HEADERS)
        response.raise_for_status()
        points_data = response.json()

        # Extract the forecast URL from the metadata
        forecast_url = points_data["properties"]["forecast"]

        # Step 2: Get the actual Forecast
        response = await client.get(forecast_url, headers=NWS_HEADERS)
        response.raise_for_status()
        forecast_data = response.json()

        # Format the next few periods into a readable string
        periods = forecast_data["properties"]["periods"]
        text = []
        for p in periods[:3]:  # Just show the next 3 periods
            text.append(f"{p['name']}: {p['detailedForecast']}")
        
        return "\n".join(text)

async def get_alerts(state):
    """
    Fetches active weather alerts for a specific US state.

    Args:
        state (str): Two-letter state code (e.g., 'CA', 'TX').

    Returns:
        str: A formatted string listing active alerts or a message indicating none.
    """
    # NWS requires uppercase state codes (e.g., "TX")
    state = state.upper()
    url = f"https://api.weather.gov/alerts/active?area={state}"
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=NWS_HEADERS)
        response.raise_for_status()
        data = response.json()

        if not data.get("features"):
            return f"No active alerts for {state}."

        alerts = []
        for feature in data["features"][:5]: # Limit to 5 alerts
            props = feature["properties"]
            alerts.append(f"• {props['event']}: {props['headline']}")
        
        return "\n".join(alerts)

# --- 2. Register Tools ---

@server.list_tools()
async def handle_list_tools():
    """
    Defines the tools available to the client (LLM).

    Returns:
        list[types.Tool]: A list of tool definitions including their names,
                          descriptions, and input schemas (JSON Schema).
    """
    return [
        types.Tool(
            name="get-forecast",
            description="Get weather forecast for a location",
            inputSchema={
                "type": "object",
                "properties": {
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"},
                },
                "required": ["latitude", "longitude"],
            },
        ),
        types.Tool(
            name="get-alerts",
            description="Get weather alerts for a state",
            inputSchema={
                "type": "object",
                "properties": {
                    "state": {"type": "string", "description": "Two-letter state code (e.g. CA, NY)"},
                },
                "required": ["state"],
            },
        ),
    ]

@server.call_tool()
async def handle_call_tool(name, arguments):
    """
    Executes a tool call requested by the client.

    Args:
        name (str): The name of the tool to execute.
        arguments (dict | None): The arguments provided by the client.

    Returns:
        list[types.TextContent]: The output of the tool execution wrapped in an MCP text content object.
    
    Raises:
        ValueError: If the tool name is unknown.
    """
    try:
        if name == "get-forecast":
            result = await get_forecast(arguments["latitude"], arguments["longitude"])
            return [types.TextContent(type="text", text=result)]
        
        elif name == "get-alerts":
            result = await get_alerts(arguments["state"])
            return [types.TextContent(type="text", text=result)]
        
        raise ValueError(f"Unknown tool: {name}")

    except httpx.HTTPStatusError as e:
        # Handle API errors gracefully
        return [types.TextContent(type="text", text=f"API Error: {e}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error: {str(e)}")]

# --- 3. Run the Server ---

async def main():
    """
    Main entry point for the MCP server.
    
    Sets up the standard input/output (stdio) streams and runs the server
    loop to handle incoming requests from the client.
    """
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="weather",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

if __name__ == "__main__":
    asyncio.run(main())