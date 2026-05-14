from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .files import write_text


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z").replace(":", "-").replace(".", "-")


def markdown_list(items, fallback: str = "None") -> str:
    if isinstance(items, list) and items:
        return "\n".join(f"- {item}" for item in items)
    return f"- {fallback}"


def sanitize_markdown(content: str) -> str:
    return "\n".join(line.rstrip() for line in content.splitlines()) + "\n"


def is_write_permission_error(error: Exception) -> bool:
    return isinstance(error, OSError) and error.errno in {1, 13, 30}


def write_agent_run(config, run: dict) -> str:
    file_name = f"{stamp()}-{run['agent']}.md"
    primary_path = Path(config.mcp_server_root) / "data" / "agent-runs" / file_name
    fallback_path = Path(config.agent_runner_root) / "data" / "agent-runs" / file_name
    content = sanitize_markdown("\n".join([
        f"# Agent Run: {run['agent']}",
        "",
        f"Created: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        f"Agent: {run['agent']}",
        f"Automation: {run['automationId']}",
        f"Product: {run['product']}",
        f"Status: {run['status']}",
        f"Next recommended agent: {run.get('nextRecommendedAgent') or 'TBD'}",
        "",
        "## Summary",
        "",
        run["summary"],
        "",
        "## Inputs Read",
        "",
        markdown_list(run.get("inputsRead")),
        "",
        "## Tasks Considered",
        "",
        markdown_list(run.get("tasksConsidered")),
        "",
        "## Changes Made",
        "",
        markdown_list(run.get("changesMade")),
        "",
        "## Artifacts Written",
        "",
        markdown_list(run.get("artifactsWritten")),
        "",
        "## Verification",
        "",
        markdown_list(run.get("verification"), "Not run"),
        "",
        "## Deferred",
        "",
        markdown_list(run.get("deferred")),
        "",
        "## Blockers",
        "",
        markdown_list(run.get("blockers")),
        "",
    ]))
    try:
        write_text(primary_path, content)
        return str(primary_path)
    except Exception as error:
        if not is_write_permission_error(error):
            raise
    write_text(fallback_path, content)
    return str(fallback_path)


def write_implementation_result(config, result: dict) -> str:
    file_name = f"{stamp()}-{result.get('slug') or result.get('agent') or 'map-platform-host-runner'}.md"
    primary_path = Path(config.mcp_server_root) / "data" / "map-platform-implementation-results" / file_name
    fallback_path = Path(config.agent_runner_root) / "data" / "map-platform-implementation-results" / file_name
    content = sanitize_markdown("\n".join([
        f"# Implementation Result: {result.get('title') or result.get('agent') or 'map-platform host runner'}",
        "",
        f"Created: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        f"Status: {result['status']}",
        "",
        "## Summary",
        "",
        result.get("summary") or "No summary recorded.",
        "",
        "## Verification",
        "",
        markdown_list(result.get("verification"), "Not run"),
        "",
        "## Git Finalization",
        "",
        markdown_list(result.get("gitFinalization"), "Not attempted"),
        "",
        "## Blockers",
        "",
        markdown_list(result.get("blockers")),
        "",
    ]))
    try:
        write_text(primary_path, content)
        return str(primary_path)
    except Exception as error:
        if not is_write_permission_error(error):
            raise
    write_text(fallback_path, content)
    return str(fallback_path)
