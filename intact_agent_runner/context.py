from __future__ import annotations

from pathlib import Path

from .commands import git_status
from .files import latest_markdown, read_text


def snippets(files: list[dict], max_chars: int = 600) -> list[str]:
    output = []
    for file in files:
        try:
            text = read_text(file["absolute"])
            output.append(f"{file['relative']}\n{text[:max_chars]}")
        except Exception:
            output.append(f"{file['relative']}\nUnavailable")
    return output


def load_map_platform_context(config) -> dict:
    data_root = Path(config.mcp_server_root) / "data"
    tasks = latest_markdown(data_root / "map-platform-tasks", 8)
    proposals = latest_markdown(data_root / "map-platform-patch-proposals", 8)
    implementation_results = latest_markdown(data_root / "map-platform-implementation-results", 8)
    agent_runs = latest_markdown(data_root / "agent-runs", 8)
    feedback_files = latest_markdown(data_root / "user-feedback", 3)
    daily_reports = latest_markdown(data_root / "daily-reports", 3)
    strategy_files = latest_markdown(Path(config.host_strategy_root) / "docs", 8)

    return {
        "dataRoot": str(data_root),
        "tasks": tasks,
        "proposals": proposals,
        "implementationResults": implementation_results,
        "agentRuns": agent_runs,
        "feedbackFiles": feedback_files,
        "dailyReports": daily_reports,
        "strategyFiles": strategy_files,
        "feedbackSnippets": snippets(feedback_files),
        "strategySnippets": [
            *snippets([{
                "absolute": str(Path(config.host_strategy_root) / "README.md"),
                "relative": "README.md",
            }], 1000),
            *snippets(strategy_files, 800),
        ],
        "gitStatus": {
            "map_platform": git_status(config.map_platform_root),
            "intact-mcp-server": git_status(config.mcp_server_root),
            "intact-agent-runner": git_status(config.agent_runner_root),
        },
    }
