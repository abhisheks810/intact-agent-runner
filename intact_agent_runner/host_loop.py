from __future__ import annotations

from .commands import command_summary, git_status, run_command
from .development_agent import (
    apply_agent_patch,
    build_development_prompt,
    development_instructions,
    finalize_repos,
    parse_agent_decision,
    run_verification,
)
from .llm import get_provider
from .runner import plan_map_platform
from .run_log import write_agent_run, write_implementation_result


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
    completion = provider.complete(
        instructions=development_instructions(),
        prompt=build_development_prompt(plan, config),
    )
    if provider.name == "none":
        decision = {
            "agentRole": plan["selectedAgent"],
            "selectedTask": plan["recommendedFocus"],
            "targetRepo": "map_platform",
            "summary": "Dry-run provider selected the next task but did not propose a patch.",
            "unifiedDiff": "",
            "changedFiles": [],
            "verification": ["Plan generation completed"],
            "commitMessage": "agent-run: map-platform host iteration",
            "deferred": ["Enable LLM_PROVIDER=openai for implementation patches"],
            "blockers": ["No LLM provider configured; no development patch was generated"],
        }
    else:
        decision = parse_agent_decision(completion["text"])

    patch = apply_agent_patch(config, decision)
    verification = (
        run_verification(config, decision)
        if patch["applied"]
        else {"ok": not bool(decision["unifiedDiff"].strip()), "results": [patch["summary"]]}
    )
    target_finalization = (
        finalize_repos(config, decision["commitMessage"], only=[decision["targetRepo"]])
        if patch["applied"] and verification["ok"]
        else {"ok": True, "results": ["No finalization attempted because no verified patch was applied."]}
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
        ],
        "tasksConsidered": [task["relative"] for task in plan["context"]["tasks"]],
        "changesMade": decision["changedFiles"] if patch["applied"] else ["No repository files changed"],
        "artifactsWritten": ["Agent-run artifact pending", "Implementation-result artifact pending"],
        "verification": [
            command_summary(preflight),
            *patch.get("commands", []),
            *verification["results"],
            *target_finalization["results"],
        ],
        "deferred": decision["deferred"],
        "blockers": [
            *decision["blockers"],
            *([] if patch["applied"] else [patch["summary"]]),
            *([] if verification["ok"] else ["Verification failed"]),
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
