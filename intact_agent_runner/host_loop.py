from __future__ import annotations

from .boundary_policy import load_and_validate_boundary_policy
from .commands import command_summary, git_status, run_command
from .development_agent import (
    finalize_repo_paths,
    finalize_repos,
)
from .llm import get_provider
from .runner import plan_map_platform
from .run_log import write_agent_run, write_implementation_result
from .tool_loop import run_tool_loop_implementation


def dirty_lines(status_output: str) -> list[str]:
    return [line for line in status_output.split("\n") if line and not line.startswith("##")]


def all_repos_clean(config) -> dict:
    results = []
    blockers = []
    for name, root in config.allowed_repo_roots.items():
        result = git_status(root)
        results.append(f"{name}\n{result.stdout or result.stderr}")
        dirty = dirty_lines(result.stdout)
        if not result.ok:
            blockers.append(f"{name}: git status failed")
        if dirty:
            blockers.append(f"{name}: repo is not clean\n" + "\n".join(dirty))
    return {"clean": len(blockers) == 0, "results": results, "blockers": blockers}


def run_host_map_platform_loop(config) -> dict:
    boundary_policy = load_and_validate_boundary_policy(config)
    if not boundary_policy["ok"]:
        return write_failure(config, {
            "agent": "platform-infra-agent",
            "status": "failed",
            "summary": "Host runner stopped before repository preflight because the deep-agent boundary policy did not validate.",
            "inputsRead": [
                config.boundary_policy_path,
            ],
            "verification": boundary_policy["results"],
            "blockers": boundary_policy["blockers"],
        })

    status_check = all_repos_clean(config)
    if not status_check["clean"]:
        return write_failure(config, {
            "agent": "platform-infra-agent",
            "status": "failed",
            "summary": "Host runner stopped before preflight because one or more repos were dirty.",
            "inputsRead": ["git status for all allowed repos"],
            "verification": status_check["results"],
            "blockers": status_check["blockers"],
        })

    preflight = run_command(
        "bash",
        ["./scripts/loop-preflight.sh", "--require-clean"],
        cwd=config.map_platform_root,
        timeout_ms=120000,
    )
    if not preflight.ok:
        return write_failure(config, {
            "agent": "platform-infra-agent",
            "status": "failed",
            "summary": "Host runner stopped at the mandatory map-platform preflight gate.",
            "inputsRead": [
                "git status for all allowed repos",
                "/Users/abhisheksrivastava/map_platform/scripts/loop-preflight.sh",
            ],
            "verification": [command_summary(preflight)],
            "blockers": [
                "Mandatory loop preflight failed; no development work was attempted.",
                "Recovery: verify host DNS/network for github.com, rerun preflight, then rerun this host loop.",
            ],
        })

    plan = plan_map_platform(config)
    provider = get_provider(config)
    implementation = run_tool_loop_implementation(config, provider, plan)
    decision = implementation["decision"]
    patch = implementation["patch"]
    verification = implementation["verification"]
    rollback = implementation["rollback"]
    target_finalization = (
        finalize_repo_paths(config, decision["targetRepo"], decision["commitMessage"], patch.get("changedPaths", decision["changedFiles"]))
        if patch["applied"] and verification["ok"]
        else {"ok": True, "results": ["No finalization attempted because no verified patch was applied.", rollback["summary"]]}
    )

    status = (
        "completed"
        if patch["applied"] and verification["ok"] and target_finalization["ok"] and len(decision["blockers"]) == 0
        else "completed_with_blockers"
    )
    run = {
        "agent": decision["agentRole"],
        "automationId": config.automation_id,
        "product": "map-platform",
        "status": status,
        "nextRecommendedAgent": decision["agentRole"],
        "summary": decision["summary"],
        "inputsRead": [
            "host_strategy README.md and docs/",
            "data/agent-specs/map-platform/",
            "data/map-platform-tasks/",
            "data/map-platform-patch-proposals/",
            "data/map-platform-implementation-results/",
            "data/agent-runs/",
            "data/user-feedback/",
            "git status for all allowed repos",
            "canonical loop preflight",
            "deep_agent_harness boundary policy",
            "intact-mcp-server stdio tools",
        ],
        "tasksConsidered": [task["relative"] for task in plan["context"]["tasks"]],
        "changesMade": decision["changedFiles"] if patch["applied"] else ["No repository files changed"],
        "artifactsWritten": ["Agent-run artifact pending", "Implementation-result artifact pending"],
        "verification": [
            *boundary_policy["results"],
            command_summary(preflight),
            *implementation["inspectResults"],
            *implementation["repairResults"],
            *patch.get("commands", []),
            *verification["results"],
            *target_finalization["results"],
        ],
        "deferred": decision["deferred"],
        "blockers": [
            *decision["blockers"],
            *([] if patch["applied"] else [patch["summary"]]),
            *([] if verification["ok"] else ["Verification failed"]),
            *([] if rollback["ok"] else ["Rollback failed after unverified implementation"]),
            *([] if target_finalization["ok"] else ["Target repository Git finalization failed"]),
        ],
    }
    run["blockers"] = [item for item in run["blockers"] if item]
    run_path = write_agent_run(config, run)
    result_path = write_implementation_result(config, {
        "slug": "host-map-platform-loop",
        "agent": decision["agentRole"],
        "title": "host map-platform loop",
        "status": status,
        "summary": decision["summary"],
        "verification": run["verification"],
        "gitFinalization": target_finalization["results"],
        "blockers": run["blockers"],
    })
    artifact_finalization = finalize_repos(
        config,
        f"agent-run: record {decision['agentRole']} host loop artifacts",
        skip=[decision["targetRepo"]],
    )
    return {
        **run,
        "runPath": run_path,
        "resultPath": result_path,
        "artifactFinalization": artifact_finalization,
    }

def write_failure(config, partial: dict) -> dict:
    run = {
        "automationId": config.automation_id,
        "product": "map-platform",
        "nextRecommendedAgent": partial["agent"],
        "tasksConsidered": [],
        "changesMade": ["None"],
        "artifactsWritten": [],
        "deferred": ["Development work deferred until host-runner gate passes"],
        **partial,
    }
    run_path = write_agent_run(config, run)
    result_path = write_implementation_result(config, {
        "slug": "host-map-platform-loop-failed",
        "agent": run["agent"],
        "title": "host map-platform loop failed",
        "status": run["status"],
        "summary": run["summary"],
        "verification": run["verification"],
        "gitFinalization": ["Not attempted"],
        "blockers": run["blockers"],
    })
    artifact_finalization = finalize_repos(
        config,
        f"agent-run: record failed {run['agent']} host loop artifacts",
        only=["intact-mcp-server"],
    )
    return {
        **run,
        "runPath": run_path,
        "resultPath": result_path,
        "artifactFinalization": artifact_finalization,
    }
