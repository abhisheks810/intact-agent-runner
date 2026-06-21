from __future__ import annotations

import json
from pathlib import Path


REQUIRED_REPOS = {
    "map_platform",
    "intact-mcp-server",
    "intact-agent-runner",
    "deep_agent_harness",
    "host_strategy",
}

REQUIRED_BOUNDARIES = {
    "strategy-governance",
    "repository-github",
    "agent-orchestration",
    "mcp-tools",
    "execution-sandbox",
    "identity-secrets",
    "network",
    "data-privacy",
    "india-geospatial",
    "map-data-pipeline",
    "product-api",
    "verification",
    "release-deployment",
    "observability-audit",
    "review-safety",
    "sustainability",
}

REQUIRED_RUN_ARTIFACTS = {
    "task_intake",
    "preflight_result",
    "tool_transcript_summary",
    "changed_files",
    "diff_or_blocker",
    "verification_evidence",
    "review_outcome",
    "final_disposition",
}


def load_and_validate_boundary_policy(config) -> dict:
    path = Path(config.boundary_policy_path)
    results: list[str] = [f"Boundary policy path: {path}"]
    blockers: list[str] = []

    if not path.exists():
        return {
            "ok": False,
            "results": results,
            "blockers": [f"Boundary policy file does not exist: {path}"],
            "policy": None,
        }

    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        return {
            "ok": False,
            "results": [*results, f"Boundary policy JSON parse failed: {error}"],
            "blockers": [f"Boundary policy JSON parse failed: {error}"],
            "policy": None,
        }

    if not isinstance(policy.get("core_rule"), str) or not policy["core_rule"].strip():
        blockers.append("Boundary policy is missing core_rule.")

    repos = {
        repo.get("name"): repo
        for repo in policy.get("repositories", [])
        if isinstance(repo, dict) and isinstance(repo.get("name"), str)
    }
    missing_repos = sorted(REQUIRED_REPOS - set(repos))
    if missing_repos:
        blockers.append("Boundary policy missing repositories: " + ", ".join(missing_repos))

    expected_paths = {
        "map_platform": config.map_platform_root,
        "intact-mcp-server": config.mcp_server_root,
        "intact-agent-runner": config.agent_runner_root,
        "deep_agent_harness": config.deep_agent_harness_root,
        "host_strategy": config.host_strategy_root,
    }
    for name, expected in expected_paths.items():
        repo = repos.get(name)
        if not repo:
            continue
        actual = repo.get("path")
        if actual != expected:
            blockers.append(f"Boundary policy path mismatch for {name}: expected {expected}, found {actual}")

    boundaries = {
        boundary.get("id")
        for boundary in policy.get("boundaries", [])
        if isinstance(boundary, dict) and isinstance(boundary.get("id"), str)
    }
    missing_boundaries = sorted(REQUIRED_BOUNDARIES - boundaries)
    if missing_boundaries:
        blockers.append("Boundary policy missing boundaries: " + ", ".join(missing_boundaries))

    run_artifacts = set(policy.get("required_run_artifacts", []))
    missing_artifacts = sorted(REQUIRED_RUN_ARTIFACTS - run_artifacts)
    if missing_artifacts:
        blockers.append("Boundary policy missing required run artifacts: " + ", ".join(missing_artifacts))

    daily_loop = policy.get("daily_agent_loop")
    if not isinstance(daily_loop, dict):
        blockers.append("Boundary policy missing daily_agent_loop.")
    else:
        if daily_loop.get("schedule_minutes") != [0, 20, 40]:
            blockers.append("Boundary policy daily_agent_loop.schedule_minutes must be [0, 20, 40].")
        if daily_loop.get("boundary_policy_path") != str(path):
            blockers.append("Boundary policy daily_agent_loop.boundary_policy_path does not match loaded policy path.")

    if not isinstance(policy.get("approval_rules"), dict) or not policy["approval_rules"]:
        blockers.append("Boundary policy missing approval_rules.")

    if blockers:
        results.extend(blockers)
    else:
        results.append(
            "Boundary policy validation passed for repos, boundaries, run artifacts, daily loop, and approval rules."
        )

    return {
        "ok": not blockers,
        "results": results,
        "blockers": blockers,
        "policy": policy,
    }
