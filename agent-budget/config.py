"""Configuration for Budget Agent - auth, FMAPI, and MCP server URL."""

import os
from databricks.sdk import WorkspaceClient

FMAPI_MODEL = os.environ.get("FMAPI_MODEL", "databricks-claude-sonnet-4-5")
MCP_SERVER_URL = os.environ.get("MCP_BUDGET_URL", "http://localhost:8001")


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
