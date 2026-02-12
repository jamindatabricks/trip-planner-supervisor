"""Configuration for Supervisor - auth, FMAPI, and all agent URLs."""

import os
from databricks.sdk import WorkspaceClient

FMAPI_MODEL = os.environ.get("FMAPI_MODEL", "databricks-claude-sonnet-4-5")

AGENT_URLS = {
    "weather": os.environ.get("AGENT_WEATHER_URL", "http://localhost:8003"),
    "packing": os.environ.get("AGENT_PACKING_URL", "http://localhost:8004"),
    "activities": os.environ.get("AGENT_ACTIVITIES_URL", "http://localhost:8005"),
    "budget": os.environ.get("AGENT_BUDGET_URL", "http://localhost:8006"),
    "transport": os.environ.get("AGENT_TRANSPORT_URL", "http://localhost:8007"),
}


def get_workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


def get_workspace_host() -> str:
    host = os.environ.get("DATABRICKS_HOST", "")
    if host and not host.startswith("http"):
        host = f"https://{host}"
    return host


def get_auth_headers() -> dict:
    client = get_workspace_client()
    return client.config.authenticate()


def get_oauth_token() -> str:
    headers = get_auth_headers()
    auth = headers.get("Authorization", "")
    return auth.replace("Bearer ", "") if auth else ""
