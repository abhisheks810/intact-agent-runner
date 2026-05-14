from __future__ import annotations

from pathlib import Path

from .agents import choose_agent, load_map_platform_agents
from .context import load_map_platform_context
from .llm import get_provider
from .run_log import write_agent_run


def plan_map_platform(config) -> dict:
    agents = load_map_platform_agents(config)
    context = load_map_platform_context(config)
    selected_agent = choose_agent(context)
    selected_spec = next((agent for agent in agents if agent["slug"] == selected_agent), None)
    return {
        "product": "map-platform",
        "selectedAgent": selected_agent,
        "selectedSpec": selected_spec,
        "agents": agents,
        "context": context,
        "recommendedFocus": recommend_focus(selected_agent, context),
    }


def recommend_focus(selected_agent: str, context: dict) -> str:
    if selected_agent == "routing-tiles-agent":
        return "Continue custom router work with graph artifact format, OSM extract parsing, or route QA."
    if selected_agent == "frontend-ux-agent":
        return "Implement or refine the Place Detail Panel so the dev UI reflects local discovery progress."
    if selected_agent == "qa-evaluation-agent":
        return "Verify current dev services, test artifacts, and blocked scheduled iterations."
    return "Select the highest-value unblocked task from the task/proposal queue."


def run_map_platform(config, *, dry_run: bool = False) -> dict:
    plan = plan_map_platform(config)
    provider = get_provider(config)
    completion = provider.complete(plan=plan)
    inputs_read = [
        "data/agent-specs/map-platform/",
        "data/map-platform-tasks/",
        "data/map-platform-patch-proposals/",
        "data/map-platform-implementation-results/",
        "data/agent-runs/",
        "data/user-feedback/",
        "map_platform git/repo context",
    ]
    run = {
        "agent": plan["selectedAgent"],
        "automationId": config.automation_id,
        "product": "map-platform",
        "status": "completed",
        "nextRecommendedAgent": plan["selectedAgent"],
        "summary": (
            f"Planned next map-platform run for {plan['selectedAgent']}: {plan['recommendedFocus']}"
            if dry_run
            else f"Ran {plan['selectedAgent']} in {provider.name} mode. {completion['text']}"
        ),
        "inputsRead": inputs_read,
        "tasksConsidered": [
            str(Path(task["absolute"]).relative_to(config.mcp_server_root))
            for task in plan["context"]["tasks"]
        ],
        "changesMade": ["None; plan-only run"] if dry_run else ["None; provider mode did not modify repository files"],
        "artifactsWritten": [],
        "verification": ["Plan generation completed"] if dry_run else ["Agent runner completed without throwing"],
        "deferred": [
            "Direct MCP stdio tool-calling from runner",
            "LLM-backed code implementation provider",
            "Dashboard UI for agent run inspection",
        ],
        "blockers": ["No LLM provider configured; running deterministic local orchestration only"] if provider.name == "none" else [],
    }
    run_path = write_agent_run(config, run)
    return {**run, "runPath": run_path}
