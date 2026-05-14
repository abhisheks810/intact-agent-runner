from __future__ import annotations

import json
from pathlib import PurePosixPath

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
        "inspect_commands": [],
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
        "Repository intelligence packet:",
        json.dumps(plan["context"].get("repoIntelligence", {}), indent=2),
        "",
        "MCP stdio tool context:",
        json.dumps(plan["context"].get("mcpToolContext", {}), indent=2),
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
        "Before returning a patch, mentally validate that it is a complete unified diff accepted by git apply --check.",
        "You may request bounded read-only inspect commands in inspect_commands when source context is insufficient.",
        "Do not request write commands; all edits must be returned as unified_diff.",
        "Keep patches minimal and reviewable.",
        "Do not include markdown fences around JSON.",
    ])


def build_patch_repair_prompt(plan: dict, decision: dict, patch_result: dict) -> str:
    shape = {
        "agent_role": decision["agentRole"],
        "selected_task": decision["selectedTask"],
        "target_repo": decision["targetRepo"],
        "summary": decision["summary"],
        "unified_diff": "complete corrected unified diff, or empty string if no safe fix is possible",
        "changed_files": decision["changedFiles"],
        "inspect_commands": [],
        "verification": decision["verification"],
        "commit_message": decision["commitMessage"],
        "deferred": decision["deferred"],
        "blockers": [],
    }
    return "\n".join([
        "The previous development-agent response proposed a patch that failed deterministic validation.",
        "Return only corrected JSON with the same shape. Do not include markdown fences or explanatory text outside JSON.",
        "The unified_diff must be a complete repo-relative unified diff that would pass git apply --check.",
        "If you cannot produce a valid patch, set unified_diff to an empty string and put the reason in blockers.",
        "",
        "Required JSON shape:",
        json.dumps(shape, indent=2),
        "",
        "Selected agent spec:",
        (plan.get("selectedSpec") or {}).get("spec") or "Unavailable",
        "",
        "Repository intelligence packet:",
        json.dumps(plan["context"].get("repoIntelligence", {}), indent=2),
        "",
        "MCP stdio tool context:",
        json.dumps(plan["context"].get("mcpToolContext", {}), indent=2),
        "",
        "Patch validation failure:",
        patch_result.get("summary", "Unknown patch failure"),
        "",
        "Previous invalid unified_diff:",
        decision.get("unifiedDiff", ""),
    ])




def build_inspection_followup_prompt(plan: dict, decision: dict, inspect_results: list[str]) -> str:
    shape = {
        "agent_role": decision["agentRole"],
        "selected_task": decision["selectedTask"],
        "target_repo": decision["targetRepo"],
        "summary": decision["summary"],
        "unified_diff": "complete repo-relative unified diff, or empty string if no safe implementation is possible",
        "changed_files": decision["changedFiles"],
        "inspect_commands": [],
        "verification": decision["verification"],
        "commit_message": decision["commitMessage"],
        "deferred": decision["deferred"],
        "blockers": [],
    }
    return "\n".join([
        "You requested read-only CLI inspection before implementation.",
        "Use the command outputs below to return a concrete implementation patch.",
        "Return only JSON. Do not include markdown fences or text outside JSON.",
        "All edits must be in unified_diff; do not request write commands.",
        "If no safe implementation is possible, set unified_diff to an empty string and explain the blocker.",
        "",
        "Required JSON shape:",
        json.dumps(shape, indent=2),
        "",
        "Selected agent spec:",
        (plan.get("selectedSpec") or {}).get("spec") or "Unavailable",
        "",
        "Repository intelligence packet:",
        json.dumps(plan["context"].get("repoIntelligence", {}), indent=2),
        "",
        "MCP stdio tool context:",
        json.dumps(plan["context"].get("mcpToolContext", {}), indent=2),
        "",
        "Inspection command outputs:",
        "\n\n---\n\n".join(inspect_results),
    ])

def build_verification_repair_prompt(plan: dict, decision: dict, verification: dict, current_diff: str) -> str:
    shape = {
        "agent_role": decision["agentRole"],
        "selected_task": decision["selectedTask"],
        "target_repo": decision["targetRepo"],
        "summary": decision["summary"],
        "unified_diff": "incremental unified diff to fix verification, or empty string if no safe fix is possible",
        "changed_files": decision["changedFiles"],
        "inspect_commands": [],
        "verification": decision["verification"],
        "commit_message": decision["commitMessage"],
        "deferred": decision["deferred"],
        "blockers": [],
    }
    return "\n".join([
        "A previous patch applied, but repository verification failed.",
        "Return only JSON with an incremental repo-relative unified_diff that fixes the failure on top of the current working tree.",
        "You may request read-only inspect_commands if the failure needs more source context.",
        "If no safe fix is possible, set unified_diff to an empty string and explain the blocker.",
        "",
        "Required JSON shape:",
        json.dumps(shape, indent=2),
        "",
        "Selected agent spec:",
        (plan.get("selectedSpec") or {}).get("spec") or "Unavailable",
        "",
        "Repository intelligence packet:",
        json.dumps(plan["context"].get("repoIntelligence", {}), indent=2),
        "",
        "MCP stdio tool context:",
        json.dumps(plan["context"].get("mcpToolContext", {}), indent=2),
        "",
        "Verification failure:",
        "\n\n".join(verification.get("results", [])),
        "",
        "Current uncommitted diff:",
        current_diff,
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
        "inspectCommands": decision.get("inspect_commands") if isinstance(decision.get("inspect_commands"), list) else [],
        "verification": decision.get("verification") if isinstance(decision.get("verification"), list) else [],
        "commitMessage": decision.get("commit_message") or "agent-run: map-platform host iteration",
        "deferred": decision.get("deferred") if isinstance(decision.get("deferred"), list) else [],
        "blockers": decision.get("blockers") if isinstance(decision.get("blockers"), list) else [],
    }



BLOCKED_PATH_PARTS = {".git", "node_modules", "dist", "build", ".venv", "__pycache__"}


def validate_patch_paths(config, decision: dict) -> list[str]:
    repo_root = config.allowed_repo_roots[decision["targetRepo"]]
    repo_dir_name = PurePosixPath(repo_root).name
    blocked: list[str] = []
    for path in changed_paths_from_diff(decision["unifiedDiff"]):
        if path == "/dev/null":
            continue
        pure = PurePosixPath(path)
        if pure.is_absolute():
            blocked.append(f"absolute patch path is not allowed: {path}")
            continue
        if ".." in pure.parts:
            blocked.append(f"parent-directory traversal is not allowed: {path}")
        if pure.parts and pure.parts[0] == repo_dir_name:
            blocked.append(
                f"patch path must be repo-relative and must not start with `{repo_dir_name}/`: {path}"
            )
        if any(part in BLOCKED_PATH_PARTS for part in pure.parts):
            blocked.append(f"generated or unsafe patch path is not allowed: {path}")
    return blocked


def changed_paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            tokens = line.split()
            if len(tokens) >= 4:
                paths.append(strip_diff_prefix(tokens[2]))
                paths.append(strip_diff_prefix(tokens[3]))
        elif line.startswith("--- ") or line.startswith("+++ "):
            token = line.split(maxsplit=1)[1]
            paths.append(strip_diff_prefix(token.split("\t", 1)[0]))
    unique: list[str] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


def strip_diff_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path

def check_agent_patch(config, decision: dict) -> dict:
    if not decision["unifiedDiff"].strip():
        return {"ok": False, "summary": "No patch proposed by agent.", "commands": [], "repairable": False}
    path_errors = validate_patch_paths(config, decision)
    if path_errors:
        return {
            "ok": False,
            "summary": "Patch path validation failed.\n" + "\n".join(path_errors),
            "commands": [],
            "repairable": True,
        }
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
            "ok": False,
            "summary": f"Patch check failed.\n{command_summary(check)}",
            "commands": [command_summary(check)],
            "repairable": True,
        }
    return {"ok": True, "summary": "Patch check passed.", "commands": [command_summary(check)], "repairable": False}


def apply_agent_patch(config, decision: dict) -> dict:
    check = check_agent_patch(config, decision)
    if not check["ok"]:
        return {"applied": False, "summary": check["summary"], "commands": check["commands"]}
    repo_root = config.allowed_repo_roots[decision["targetRepo"]]
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
        "commands": [*check["commands"], command_summary(apply)],
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



READ_ONLY_COMMANDS = {
    "git": {"status", "diff", "show", "log", "ls-files"},
    "rg": None,
    "sed": None,
    "find": None,
    "python3": {"-m"},
    "bash": {"./scripts/verify.sh", "./scripts/loop-preflight.sh"},
    "npm": {"test", "run"},
}


def run_inspect_commands(config, decision: dict, limit: int = 5) -> list[str]:
    outputs = []
    repo_root = config.allowed_repo_roots[decision["targetRepo"]]
    for raw in decision.get("inspectCommands", [])[:limit]:
        if not isinstance(raw, str) or not raw.strip():
            continue
        parsed = parse_inspect_command(raw)
        if not parsed["ok"]:
            outputs.append(f"$ {raw}\nblocked: {parsed['error']}")
            continue
        result = run_command(parsed["command"], parsed["args"], cwd=repo_root, timeout_ms=120000)
        outputs.append(command_summary(result))
    return outputs


def parse_inspect_command(raw: str) -> dict:
    import shlex

    try:
        parts = shlex.split(raw)
    except ValueError as error:
        return {"ok": False, "error": str(error)}
    if not parts:
        return {"ok": False, "error": "empty command"}
    if any(token in raw for token in [";", "&&", "||", "|", ">", "<", "`", "$("]):
        return {"ok": False, "error": "shell operators are not allowed"}
    command, args = parts[0], parts[1:]
    allowed = READ_ONLY_COMMANDS.get(command)
    if command not in READ_ONLY_COMMANDS:
        return {"ok": False, "error": f"command not allowlisted: {command}"}
    if allowed is not None:
        first = args[0] if args else ""
        if first not in allowed:
            return {"ok": False, "error": f"subcommand not allowlisted for {command}: {first}"}
    blocked_tokens = {"add", "commit", "push", "pull", "fetch", "checkout", "reset", "clean", "apply", "rm", "mv", "install"}
    if any(arg in blocked_tokens for arg in args):
        return {"ok": False, "error": "write or network subcommand is not allowed"}
    return {"ok": True, "command": command, "args": args}


def current_repo_diff(config, target_repo: str) -> str:
    result = run_command("git", ["diff", "--binary"], cwd=config.allowed_repo_roots[target_repo], timeout_ms=60000)
    return result.stdout if result.ok else command_summary(result)


def rollback_uncommitted_changes(config, target_repo: str) -> dict:
    repo_root = config.allowed_repo_roots[target_repo]
    diff = run_command("git", ["diff", "--binary"], cwd=repo_root, timeout_ms=60000)
    if not diff.ok:
        return {"ok": False, "summary": f"Failed to capture rollback diff.\n{command_summary(diff)}"}
    if not diff.stdout.strip():
        return {"ok": True, "summary": "No uncommitted diff to roll back."}
    reverse = run_command("git", ["apply", "-R", "--whitespace=nowarn", "-"], cwd=repo_root, input_text=diff.stdout, timeout_ms=60000)
    return {
        "ok": reverse.ok,
        "summary": "Rolled back unverified patch." if reverse.ok else f"Rollback failed.\n{command_summary(reverse)}",
    }

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


def finalize_repo_paths(config, target_repo: str, commit_message: str, changed_paths: list[str]) -> dict:
    repo_root = config.allowed_repo_roots[target_repo]
    results = []
    scoped_paths = [path for path in changed_paths if isinstance(path, str) and path.strip()]
    if not scoped_paths:
        return {"ok": True, "results": [f"{target_repo}: no scoped paths to finalize"]}

    status = run_command("git", ["status", "--porcelain", "--", *scoped_paths], cwd=repo_root, timeout_ms=30000)
    results.append(f"{target_repo}: {command_summary(status)}")
    if not status.ok:
        return {"ok": False, "results": results}
    if not status.stdout.strip():
        return {"ok": True, "results": [*results, f"{target_repo}: no changes in scoped paths"]}

    add = run_command("git", ["add", "--", *scoped_paths], cwd=repo_root, timeout_ms=30000)
    results.append(f"{target_repo}: {command_summary(add)}")
    if not add.ok:
        return {"ok": False, "results": results}

    check = run_command("git", ["diff", "--cached", "--check"], cwd=repo_root, timeout_ms=30000)
    results.append(f"{target_repo}: {command_summary(check)}")
    if not check.ok:
        return {"ok": False, "results": results}

    commit = run_command("git", ["commit", "-m", commit_message], cwd=repo_root, timeout_ms=60000)
    results.append(f"{target_repo}: {command_summary(commit)}")
    if not commit.ok:
        return {"ok": False, "results": results}

    if config.commit_and_push:
        push = run_command("git", ["push", "origin", "main"], cwd=repo_root, timeout_ms=120000)
        results.append(f"{target_repo}: {command_summary(push)}")
        if not push.ok:
            return {"ok": False, "results": results}
    return {"ok": True, "results": results}
