from __future__ import annotations

import json

from .commands import command_summary, run_command


ALLOWED_TARGET_REPOS = {"map_platform", "intact-mcp-server", "intact-agent-runner"}


def build_development_prompt(plan: dict, config) -> str:
    shape = {
        "agent_role": plan["selectedAgent"],
        "selected_task": "short task name",
        "target_repo": "map_platform",
        "summary": "what the run should do",
        "unified_diff": "",
        "changed_files": [],
        "verification": [],
        "commit_message": "agent-run: map-platform host iteration",
        "deferred": [],
        "blockers": [],
    }
    git_status = "\n---\n".join(
        f"{name}\n{result.stdout or result.stderr}"
        for name, result in plan["context"]["gitStatus"].items()
    )
    return "\n".join([
        "You are the bounded map-platform host-runner development agent.",
        "Pick one small, high-value unblocked task aligned to the org strategy.",
        "Priority order: dev-interface reliability, place detail/local discovery, accessibility metadata, QA/evaluation, custom routing, documentation.",
        "Do not propose production deploys, secrets access, destructive Git operations, or unrelated repo rewrites.",
        "Return only JSON with this shape:",
        json.dumps(shape, indent=2),
        "",
        "Allowed target_repo values: map_platform, intact-mcp-server, intact-agent-runner.",
        "If no safe implementation is available, set unified_diff to an empty string and explain the blocker.",
        "",
        "Selected agent spec:",
        (plan.get("selectedSpec") or {}).get("spec") or "Unavailable",
        "",
        "Recommended focus:",
        plan["recommendedFocus"],
        "",
        "Strategy context:",
        "\n\n---\n\n".join(plan["context"]["strategySnippets"]),
        "",
        "Feedback context:",
        "\n\n---\n\n".join(plan["context"]["feedbackSnippets"]),
        "",
        "Recent tasks:",
        "\n".join(task["relative"] for task in plan["context"]["tasks"]),
        "",
        "Recent implementation results:",
        "\n".join(result["relative"] for result in plan["context"]["implementationResults"]),
        "",
        "Git status:",
        git_status,
        "",
        f"Commit-and-push finalization is {'enabled' if config.commit_and_push else 'disabled'}.",
    ])


def development_instructions() -> str:
    return "\n".join([
        "You are a senior development agent operating under a host-runner policy.",
        "You may propose a unified diff only for allowlisted repositories and only for the selected small task.",
        "Keep patches minimal and reviewable.",
        "Do not include markdown fences around JSON.",
    ])


def parse_agent_decision(text: str) -> dict:
    try:
        return normalize_decision(load_decision_json(text))
    except Exception as error:
        raise RuntimeError(f"Agent response was not valid JSON: {error}\n{text[:1200]}") from error


def load_decision_json(text: str) -> dict:
    decoder = json.JSONDecoder()
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(stripped):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise json.JSONDecodeError("No JSON object found", stripped, 0)


def normalize_decision(decision: dict) -> dict:
    target_repo = decision.get("target_repo") or "map_platform"
    if target_repo not in ALLOWED_TARGET_REPOS:
        raise RuntimeError(f"Agent selected unsupported target_repo: {target_repo}")
    return {
        "agentRole": decision.get("agent_role") or "qa-evaluation-agent",
        "selectedTask": decision.get("selected_task") or "Unspecified task",
        "targetRepo": target_repo,
        "summary": decision.get("summary") or "No summary returned by agent.",
        "unifiedDiff": decision.get("unified_diff") or "",
        "changedFiles": decision.get("changed_files") if isinstance(decision.get("changed_files"), list) else [],
        "verification": decision.get("verification") if isinstance(decision.get("verification"), list) else [],
        "commitMessage": decision.get("commit_message") or "agent-run: map-platform host iteration",
        "deferred": decision.get("deferred") if isinstance(decision.get("deferred"), list) else [],
        "blockers": decision.get("blockers") if isinstance(decision.get("blockers"), list) else [],
    }


def apply_agent_patch(config, decision: dict) -> dict:
    if not decision["unifiedDiff"].strip():
        return {"applied": False, "summary": "No patch proposed by agent.", "commands": []}
    repo_root = config.allowed_repo_roots[decision["targetRepo"]]
    check = run_command(
        "git",
        ["apply", "--check", "--whitespace=nowarn", "-"],
        cwd=repo_root,
        input_text=decision["unifiedDiff"],
        timeout_ms=60000,
    )
    if not check.ok:
        return {
            "applied": False,
            "summary": f"Patch check failed.\n{command_summary(check)}",
            "commands": [command_summary(check)],
        }
    apply = run_command(
        "git",
        ["apply", "--whitespace=nowarn", "-"],
        cwd=repo_root,
        input_text=decision["unifiedDiff"],
        timeout_ms=60000,
    )
    return {
        "applied": apply.ok,
        "summary": "Patch applied." if apply.ok else f"Patch apply failed.\n{command_summary(apply)}",
        "commands": [command_summary(check), command_summary(apply)],
    }


def run_verification(config, decision: dict) -> dict:
    repo_root = config.allowed_repo_roots[decision["targetRepo"]]
    if decision["targetRepo"] == "map_platform":
        commands = [{
            "command": "bash",
            "args": ["./scripts/verify.sh"],
            "cwd": repo_root,
            "env": {"PYTHONPYCACHEPREFIX": "/tmp/map_platform_pycache"},
        }]
    elif decision["targetRepo"] == "intact-agent-runner":
        commands = [{"command": "python3", "args": ["test/smoke_test.py"], "cwd": repo_root, "env": {}}]
    else:
        commands = [{"command": "git", "args": ["diff", "--check"], "cwd": repo_root, "env": {}}]

    results = []
    for item in commands:
        result = run_command(
            item["command"],
            item["args"],
            cwd=item["cwd"],
            env=item.get("env"),
            timeout_ms=300000,
        )
        results.append(command_summary(result))
        if not result.ok:
            return {"ok": False, "results": results}
    return {"ok": True, "results": results}


def finalize_repos(config, commit_message: str, *, only: list[str] | None = None, skip: list[str] | None = None) -> dict:
    skip = skip or []
    results = []
    for name, repo_root in config.allowed_repo_roots.items():
        if only and name not in only:
            continue
        if name in skip:
            continue
        status = run_command("git", ["status", "--porcelain"], cwd=repo_root, timeout_ms=30000)
        if not status.ok:
            results.append(f"{name}: status failed\n{command_summary(status)}")
            continue
        if not status.stdout.strip():
            results.append(f"{name}: no changes")
            continue
        add = run_command("git", ["add", "--all"], cwd=repo_root, timeout_ms=30000)
        results.append(f"{name}: {command_summary(add)}")
        if not add.ok:
            continue
        check = run_command("git", ["diff", "--cached", "--check"], cwd=repo_root, timeout_ms=30000)
        results.append(f"{name}: {command_summary(check)}")
        if not check.ok:
            continue
        commit = run_command("git", ["commit", "-m", commit_message], cwd=repo_root, timeout_ms=60000)
        results.append(f"{name}: {command_summary(commit)}")
        if not commit.ok:
            continue
        if config.commit_and_push:
            push = run_command("git", ["push", "origin", "main"], cwd=repo_root, timeout_ms=120000)
            results.append(f"{name}: {command_summary(push)}")
            if not push.ok:
                return {"ok": False, "results": results}
    return {"ok": True, "results": results}
