from __future__ import annotations

from .mcp_stdio import McpStdioClient, tool_json

MAX_MCP_FILE_ROWS = 180
MAX_MCP_MATCH_ROWS = 40
MAX_MCP_SNIPPET_CHARS = 2200

SOURCE_FILES = [
    "backend/main.py",
    "backend/routers/route.py",
    "frontend/src/components/SearchBar.jsx",
    "frontend/src/components/MapView.jsx",
    "custom_router/app.py",
    "tests/test_route_contracts.py",
]

SEARCH_QUERIES = [
    "Get Route",
    "${API_BASE}/route",
    "include_router(route.router",
    "@router.get",
    "accessibility",
]


def build_mcp_tool_context(config) -> dict:
    try:
        with McpStdioClient(config) as client:
            listed_tools = tool_json(client.request("tools/list", {}))
            return {
                "status": "ok",
                "server": "intact-mcp-server stdio",
                "toolsAvailable": summarize_tools(listed_tools),
                "mapPlatformGitStatus": tool_json(client.call_tool("map_platform_git_status", {})),
                "mapPlatformFiles": trim_files(tool_json(client.call_tool("list_map_platform_files", {}))),
                "mapPlatformSearch": run_searches(client),
                "mapPlatformSource": read_sources(client),
                "doctors": {
                    "verify": tool_json(client.call_tool("doctor_map_platform_verify", {"dry_run": True, "timeout_ms": 1500})),
                    "devInterface": tool_json(client.call_tool("doctor_map_platform_dev_interface", {"dry_run": True, "timeout_ms": 1500})),
                    "placeContract": tool_json(client.call_tool("doctor_map_platform_place_contract", {"dry_run": True, "timeout_ms": 1500})),
                },
            }
    except Exception as error:
        return {
            "status": "unavailable",
            "server": "intact-mcp-server stdio",
            "error": str(error),
            "note": "Runner will continue with direct filesystem context; MCP stdio should be fixed before relying on tool-only context.",
        }


def summarize_tools(listed_tools) -> list[str]:
    if not isinstance(listed_tools, dict):
        return []
    tools = listed_tools.get("tools")
    if not isinstance(tools, list):
        return []
    return [str(tool.get("name")) for tool in tools if isinstance(tool, dict) and tool.get("name")]


def trim_files(payload) -> dict:
    if not isinstance(payload, dict):
        return {"raw": payload}
    files = payload.get("files")
    if isinstance(files, list):
        payload = dict(payload)
        payload["files"] = files[:MAX_MCP_FILE_ROWS]
        payload["truncated"] = len(files) > MAX_MCP_FILE_ROWS
        payload["total_files"] = len(files)
    return payload


def run_searches(client: McpStdioClient) -> list[dict]:
    results = []
    for query in SEARCH_QUERIES:
        payload = tool_json(client.call_tool("search_map_platform", {"query": query, "limit": MAX_MCP_MATCH_ROWS}))
        if isinstance(payload, dict) and isinstance(payload.get("matches"), list):
            payload = dict(payload)
            payload["matches"] = payload["matches"][:MAX_MCP_MATCH_ROWS]
        results.append({"query": query, "result": payload})
    return results


def read_sources(client: McpStdioClient) -> list[dict]:
    sources = []
    for path in SOURCE_FILES:
        try:
            text = tool_json(client.call_tool("read_map_platform_file", {"path": path}))
            if not isinstance(text, str):
                text = str(text)
            sources.append({"path": path, "text": trim_text(text, MAX_MCP_SNIPPET_CHARS)})
        except Exception as error:
            sources.append({"path": path, "error": str(error)})
    return sources


def trim_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... [truncated]"
