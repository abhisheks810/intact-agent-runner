from __future__ import annotations

from .commands import command_summary, git_status, run_command
from .development_agent import (
    apply_agent_patch,
    build_development_prompt,
    build_inspection_followup_prompt,
    build_patch_repair_prompt,
    build_verification_repair_prompt,
    check_agent_patch,
    current_repo_diff,
    development_instructions,
    finalize_repos,
    parse_agent_decision,
    rollback_uncommitted_changes,
    run_inspect_commands,
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
    patch_validation_attempts = []
    try:
        decision, pre_patch_inspect_results = request_decision_after_inspection(config, provider, plan)
        decision, patch_validation_attempts = repair_until_patch_checks(config, provider, plan, decision)
    except Exception as error:
        return write_failure(config, {
            "agent": plan["selectedAgent"],
            "status": "failed",
            "summary": "Host runner stopped while requesting or parsing the development-agent decision.",
            "inputsRead": [
                "host_strategy README.md and docs/",
                "data/agent-specs/map-platform/",
                "data/map-platform-tasks/",
                "data/map-platform-implementation-results/",
                "git status for all allowed repos",
                "canonical loop preflight",
                "intact-mcp-server stdio tools when available",
            ],
            "verification": [command_summary(preflight)],
            "blockers": [str(error)],
        })

    implementation = run_implementation_until_verified(config, provider, plan, decision, pre_patch_inspect_results)
    decision = implementation["decision"]
    patch = implementation["patch"]
    verification = implementation["verification"]
    rollback = implementation["rollback"]
    target_finalization = (
        finalize_repos(config, decision["commitMessage"], only=[decision["targetRepo"]])
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
            "intact-mcp-server stdio tools",
        ],
        "tasksConsidered": [task["relative"] for task in plan["context"]["tasks"]],
        "changesMade": decision["changedFiles"] if patch["applied"] else ["No repository files changed"],
        "artifactsWritten": ["Agent-run artifact pending", "Implementation-result artifact pending"],
        "verification": [
            command_summary(preflight),
            *patch_validation_attempts,
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



def request_initial_decision(config, provider, plan: dict) -> dict:
    if provider.name == "none":
        return {
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
    completion = provider.complete(
        instructions=development_instructions(),
        prompt=build_development_prompt(plan, config),
    )
    return parse_agent_decision(completion["text"])



def request_decision_after_inspection(config, provider, plan: dict, max_rounds: int = 2) -> tuple[dict, list[str]]:
    decision = request_initial_decision(config, provider, plan)
    inspect_results: list[str] = []
    if provider.name == "none":
        return decision, inspect_results

    for _ in range(max_rounds):
        if not decision.get("inspectCommands"):
            return decision, inspect_results
        round_results = run_inspect_commands(config, decision)
        inspect_results.extend(round_results)
        completion = provider.complete(
            instructions=development_instructions(),
            prompt=build_inspection_followup_prompt(plan, decision, round_results),
        )
        decision = parse_agent_decision(completion["text"])
    if decision.get("inspectCommands"):
        decision = dict(decision)
        decision["blockers"] = [
            *decision.get("blockers", []),
            "Inspection request budget exhausted; runner proceeded with latest decision.",
        ]
    return decision, inspect_results

def repair_until_patch_checks(config, provider, plan: dict, decision: dict, max_repairs: int = 2) -> tuple[dict, list[str]]:
    attempts = []
    if provider.name == "none" or not decision["unifiedDiff"].strip():
        return decision, attempts

    current = decision
    for attempt in range(max_repairs + 1):
        check = check_agent_patch(config, current)
        attempts.extend([f"Patch validation attempt {attempt + 1}: {check['summary']}", *check.get("commands", [])])
        if check["ok"]:
            return current, attempts
        if attempt >= max_repairs or not check.get("repairable"):
            current = dict(current)
            current["blockers"] = [
                *current.get("blockers", []),
                f"Patch validation failed after {attempt + 1} attempt(s): {check['summary']}",
            ]
            return current, attempts
        completion = provider.complete(
            instructions=development_instructions(),
            prompt=build_patch_repair_prompt(plan, current, check),
        )
        repaired = parse_agent_decision(completion["text"])
        if repaired["targetRepo"] != current["targetRepo"]:
            repaired["targetRepo"] = current["targetRepo"]
            repaired["blockers"] = [
                *repaired.get("blockers", []),
                "Repair response attempted to change target_repo; runner restored original target_repo.",
            ]
        current = repaired
    return current, attempts


def run_implementation_until_verified(config, provider, plan: dict, decision: dict, inspect_results: list[str] | None = None, max_verification_repairs: int = 2) -> dict:
    inspect_results = inspect_results or []
    current = decision
    repair_results = []
    cumulative_patch = {"applied": False, "summary": "No patch attempted.", "commands": []}
    verification = {"ok": not bool(current["unifiedDiff"].strip()), "results": ["No patch proposed by agent."]}

    for attempt in range(max_verification_repairs + 1):
        patch = apply_agent_patch(config, current)
        cumulative_patch = {
            "applied": cumulative_patch["applied"] or patch["applied"],
            "summary": patch["summary"],
            "commands": [*cumulative_patch.get("commands", []), *patch.get("commands", [])],
        }
        if not patch["applied"]:
            verification = {"ok": not bool(current["unifiedDiff"].strip()), "results": [patch["summary"]]}
            return finish_implementation(config, current, cumulative_patch, verification, inspect_results, repair_results)

        verification = run_verification(config, current)
        if verification["ok"]:
            return {
                "decision": current,
                "patch": cumulative_patch,
                "verification": verification,
                "rollback": {"ok": True, "summary": "Verified patch retained for finalization."},
                "inspectResults": inspect_results,
                "repairResults": repair_results,
            }

        if provider.name == "none" or attempt >= max_verification_repairs:
            current = dict(current)
            current["blockers"] = [
                *current.get("blockers", []),
                f"Verification failed after {attempt + 1} implementation attempt(s).",
            ]
            return finish_implementation(config, current, cumulative_patch, verification, inspect_results, repair_results)

        diff = current_repo_diff(config, current["targetRepo"])
        completion = provider.complete(
            instructions=development_instructions(),
            prompt=build_verification_repair_prompt(plan, current, verification, diff),
        )
        repaired = parse_agent_decision(completion["text"])
        repaired, patch_checks = repair_until_patch_checks(config, provider, plan, repaired)
        repair_results.extend([
            f"Verification repair attempt {attempt + 1}: requested corrected implementation after failed verification.",
            *patch_checks,
        ])
        if repaired["targetRepo"] != current["targetRepo"]:
            repaired["targetRepo"] = current["targetRepo"]
            repaired["blockers"] = [
                *repaired.get("blockers", []),
                "Verification repair attempted to change target_repo; runner restored original target_repo.",
            ]
        if repaired.get("inspectCommands"):
            extra_inspect = run_inspect_commands(config, repaired)
            inspect_results.extend(extra_inspect)
            completion = provider.complete(
                instructions=development_instructions(),
                prompt=build_inspection_followup_prompt(plan, repaired, extra_inspect),
            )
            repaired = parse_agent_decision(completion["text"])
            repaired, patch_checks = repair_until_patch_checks(config, provider, plan, repaired)
            repair_results.extend(patch_checks)
        current = repaired

    return finish_implementation(config, current, cumulative_patch, verification, inspect_results, repair_results)


def finish_implementation(config, decision: dict, patch: dict, verification: dict, inspect_results: list[str], repair_results: list[str]) -> dict:
    rollback = {"ok": True, "summary": "No rollback needed."}
    if patch.get("applied") and not verification.get("ok"):
        rollback = rollback_uncommitted_changes(config, decision["targetRepo"])
    return {
        "decision": decision,
        "patch": patch,
        "verification": verification,
        "rollback": rollback,
        "inspectResults": inspect_results,
        "repairResults": repair_results,
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
