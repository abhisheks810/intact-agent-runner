from __future__ import annotations

import json

from .commands import command_summary, run_command
from .development_agent import load_decision_json
from .edit_session import EditSession
from .worktree import (
    TemporaryWorktree,
    apply_verified_diff,
    run_repo_verification,
    validate_generated_diff,
    worktree_changed_paths,
    worktree_diff,
)


MAX_ACTION_ROUNDS = 12

ALLOWED_TOOLS = [
    "list_files",
    "list_dir",
    "read_file",
    "search",
    "git_status",
    "git_diff",
    "write_file_full",
    "add_file",
    "run_verify",
    "run_tests",
    "run_readonly_command",
    "finish",
]

READONLY_COMMANDS = {
    "git": {"status", "diff", "show", "log", "ls-files"},
    "rg": None,
    "sed": None,
    "find": None,
    "python3": {"-m"},
    "bash": {"./scripts/verify.sh", "./scripts/loop-preflight.sh"},
    "npm": {"test", "run"},
}


def tool_loop_instructions() -> str:
    return "\n".join([
        "You are a senior development agent operating through a structured host-runner tool loop.",
        "Return exactly one JSON object per response. Do not include markdown fences or text outside JSON.",
        "Do not return unified diffs. The runner generates diffs from tool writes.",
        "Use tools for inspection and edits. Prefer one small, commit-worthy map_platform task.",
        "Existing files must be read before write, and write_file_full must include the sha256 returned by read_file.",
        "No production deploys, secrets changes, destructive Git commands, broad rewrites, or generated output edits.",
    ])


def initial_tool_prompt(plan: dict) -> str:
    shape = {
        "tool": "read_file",
        "args": {"path": "README.md"},
        "reason": "why this action is needed",
    }
    finish = {
        "tool": "finish",
        "args": {
            "summary": "what changed",
            "changed_files": [],
            "verification": [],
            "commit_message": "agent-run: map-platform host iteration",
            "deferred": [],
            "blockers": [],
        },
        "reason": "finish after edits and verification are complete, or when blocked",
    }
    return "\n".join([
        "Choose the next tool action for a bounded map-platform development run.",
        "Priority order: dev-interface reliability, place detail/local discovery, accessibility metadata, QA/evaluation, custom routing, documentation.",
        "Allowed tools: " + ", ".join(ALLOWED_TOOLS),
        "Use list_dir for a single directory and list_files for a repository-wide file list.",
        "",
        "Action shape:",
        json.dumps(shape, indent=2),
        "",
        "Finish shape:",
        json.dumps(finish, indent=2),
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
    ])


def followup_tool_prompt(action_log: list[dict]) -> str:
    return "\n".join([
        "Continue the same development run. Return exactly one next JSON tool action.",
        "If the task is complete or blocked, return the finish action.",
        "Recent tool/action log:",
        json.dumps(action_log[-16:], indent=2),
    ])


def parse_tool_action(text: str) -> dict:
    parsed = load_decision_json(text)
    tool = parsed.get("tool")
    args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
    if tool not in ALLOWED_TOOLS:
        raise RuntimeError(f"Unsupported tool action: {tool}")
    return {"tool": tool, "args": args, "reason": parsed.get("reason") or ""}


def run_tool_loop_implementation(config, provider, plan: dict) -> dict:
    if provider.name == "none":
        return no_tool_loop_patch(plan, "No LLM provider configured; no development patch was generated")

    target_repo = "map_platform"
    source_root = config.allowed_repo_roots[target_repo]
    raw_responses: list[str] = []
    action_log: list[dict] = []
    verification = {"ok": False, "results": ["Verification not run."]}
    final_args = None
    cleanup_results: list[str] = []

    try:
        with TemporaryWorktree(source_root=source_root) as worktree:
            session = EditSession(repo_root=worktree.path, repo_name="map_platform")
            prompt = initial_tool_prompt(plan)

            for _ in range(MAX_ACTION_ROUNDS):
                completion = provider.complete(instructions=tool_loop_instructions(), prompt=prompt)
                raw_text = completion["text"]
                raw_responses.append(raw_text)
                action = parse_tool_action(raw_text)
                action_log.append({"action": action})

                if action["tool"] == "finish":
                    final_args = normalize_finish_args(action["args"])
                    break

                result = execute_tool_action(config, session, action, target_repo)
                action_log.append({"tool_result": {"tool": action["tool"], "ok": result.ok, "output": result.output, "data": result.data}})
                if action["tool"] in {"run_verify", "run_tests"}:
                    verification = {"ok": result.ok, "results": [result.output]}
                prompt = followup_tool_prompt(action_log)

            if final_args is None:
                final_args = normalize_finish_args({
                    "summary": "Tool loop action budget exhausted before a final response.",
                    "blockers": ["Tool loop action budget exhausted."],
                })

            generated_diff = worktree_diff(worktree.path)
            changed_paths = worktree_changed_paths(worktree.path)
            if not generated_diff.strip():
                cleanup = worktree.cleanup()
                cleanup_results = cleanup.commands
                return finish_tool_loop(
                    plan=plan,
                    target_repo=target_repo,
                    final_args=final_args,
                    changed_paths=[],
                    generated_diff="",
                    action_log=action_log,
                    raw_responses=raw_responses,
                    patch_applied=False,
                    patch_summary="No repository files changed.",
                    patch_commands=[*worktree.commands, *cleanup_results],
                    verification={"ok": True, "results": ["No patch generated."]},
                    blockers=final_args["blockers"],
                )

            diff_check = run_command("git", ["diff", "--check"], cwd=worktree.path, timeout_ms=60000)
            diff_validation = validate_generated_diff(source_root=source_root, diff_text=generated_diff)
            validation_results = [command_summary(diff_check), *diff_validation["results"]]
            if not diff_check.ok or not diff_validation["ok"]:
                cleanup = worktree.cleanup()
                cleanup_results = cleanup.commands
                return finish_tool_loop(
                    plan=plan,
                    target_repo=target_repo,
                    final_args=final_args,
                    changed_paths=changed_paths,
                    generated_diff=generated_diff,
                    action_log=action_log,
                    raw_responses=raw_responses,
                    patch_applied=False,
                    patch_summary="Generated diff failed deterministic validation.",
                    patch_commands=[*worktree.commands, *validation_results, *cleanup_results],
                    verification={"ok": False, "results": validation_results},
                    blockers=["Generated diff failed deterministic validation."],
                )

            if not verification["ok"]:
                verification = run_repo_verification(worktree.path, target_repo)
            if not verification["ok"]:
                cleanup = worktree.cleanup()
                cleanup_results = cleanup.commands
                return finish_tool_loop(
                    plan=plan,
                    target_repo=target_repo,
                    final_args=final_args,
                    changed_paths=changed_paths,
                    generated_diff=generated_diff,
                    action_log=action_log,
                    raw_responses=raw_responses,
                    patch_applied=False,
                    patch_summary="Verification failed in temporary worktree; canonical repo left unchanged.",
                    patch_commands=[*worktree.commands, *validation_results, *cleanup_results],
                    verification=verification,
                    blockers=["Verification failed in temporary worktree."],
                )

            apply_result = apply_verified_diff(source_root=source_root, diff_text=generated_diff)
            cleanup = worktree.cleanup()
            cleanup_results = cleanup.commands
            return finish_tool_loop(
                plan=plan,
                target_repo=target_repo,
                final_args=final_args,
                changed_paths=changed_paths,
                generated_diff=generated_diff,
                action_log=action_log,
                raw_responses=raw_responses,
                patch_applied=apply_result["ok"],
                patch_summary="Verified generated diff applied to canonical repo." if apply_result["ok"] else "Verified generated diff failed to apply to canonical repo.",
                patch_commands=[*worktree.commands, *validation_results, *verification["results"], *apply_result["results"], *cleanup_results],
                verification=verification,
                blockers=[] if apply_result["ok"] else ["Verified generated diff failed to apply to canonical repo."],
            )
    except Exception as error:
        return no_tool_loop_patch(plan, str(error), raw_responses=raw_responses, action_log=action_log, verification=verification, cleanup_results=cleanup_results)


def execute_tool_action(config, session: EditSession, action: dict, target_repo: str):
    tool = action["tool"]
    args = action["args"]
    if tool == "list_files":
        return session.list_files(limit=int(args.get("limit") or 220))
    if tool == "list_dir":
        return session.list_dir(str(args.get("path") or "."), limit=int(args.get("limit") or 120))
    if tool == "read_file":
        return session.read_file(str(args.get("path") or ""))
    if tool == "search":
        return session.search(str(args.get("query") or ""))
    if tool == "git_status":
        return session.git_status()
    if tool == "git_diff":
        return session.git_diff()
    if tool == "write_file_full":
        return session.write_file_full(
            str(args.get("path") or ""),
            args.get("content") if isinstance(args.get("content"), str) else "",
            args.get("expected_sha256"),
        )
    if tool == "add_file":
        return session.add_file(
            str(args.get("path") or ""),
            args.get("content") if isinstance(args.get("content"), str) else "",
        )
    if tool == "run_verify":
        result = run_repo_verification(str(session.repo_root), target_repo)
        return session.record("run_verify", result["ok"], "\n".join(result["results"]))
    if tool == "run_tests":
        result = run_repo_verification(str(session.repo_root), target_repo)
        return session.record("run_tests", result["ok"], "\n".join(result["results"]))
    if tool == "run_readonly_command":
        return run_readonly_command(session, str(args.get("command") or ""))
    return session.record(tool, False, f"tool not implemented: {tool}")


def run_readonly_command(session: EditSession, raw: str):
    import shlex

    try:
        parts = shlex.split(raw)
    except ValueError as error:
        return session.record("run_readonly_command", False, str(error))
    if not parts:
        return session.record("run_readonly_command", False, "empty command")
    if any(token in raw for token in [";", "&&", "||", "|", ">", "<", "`", "$("]):
        return session.record("run_readonly_command", False, "shell operators are not allowed")
    command, args = parts[0], parts[1:]
    allowed = READONLY_COMMANDS.get(command)
    if command not in READONLY_COMMANDS:
        return session.record("run_readonly_command", False, f"command not allowlisted: {command}")
    if allowed is not None:
        first = args[0] if args else ""
        if first not in allowed:
            return session.record("run_readonly_command", False, f"subcommand not allowlisted for {command}: {first}")
    blocked = {"add", "commit", "push", "pull", "fetch", "checkout", "reset", "clean", "apply", "rm", "mv", "install"}
    if any(arg in blocked for arg in args):
        return session.record("run_readonly_command", False, "write or network subcommand is not allowed")
    result = run_command(command, args, cwd=str(session.repo_root), timeout_ms=120000)
    return session.record("run_readonly_command", result.ok, command_summary(result), {"exit": result.code})


def normalize_finish_args(args: dict) -> dict:
    return {
        "summary": args.get("summary") or "Tool-loop run finished.",
        "changed_files": args.get("changed_files") if isinstance(args.get("changed_files"), list) else [],
        "verification": args.get("verification") if isinstance(args.get("verification"), list) else [],
        "commit_message": args.get("commit_message") or "agent-run: map-platform host iteration",
        "deferred": args.get("deferred") if isinstance(args.get("deferred"), list) else [],
        "blockers": args.get("blockers") if isinstance(args.get("blockers"), list) else [],
    }


def finish_tool_loop(
    *,
    plan: dict,
    target_repo: str,
    final_args: dict,
    changed_paths: list[str],
    generated_diff: str,
    action_log: list[dict],
    raw_responses: list[str],
    patch_applied: bool,
    patch_summary: str,
    patch_commands: list[str],
    verification: dict,
    blockers: list[str],
) -> dict:
    decision = {
        "agentRole": plan["selectedAgent"],
        "selectedTask": plan["recommendedFocus"],
        "targetRepo": target_repo,
        "summary": final_args["summary"],
        "changedFiles": changed_paths or final_args["changed_files"],
        "commitMessage": final_args["commit_message"],
        "deferred": final_args["deferred"],
        "blockers": [*final_args["blockers"], *blockers],
    }
    diagnostics = [
        "Tool-loop actions:",
        json.dumps(action_log, indent=2)[:20000],
        "Generated diff:",
        generated_diff[:30000] if generated_diff else "None",
        "Raw model responses:",
        "\n---\n".join(raw_responses)[-20000:] if raw_responses else "None",
    ]
    return {
        "decision": decision,
        "patch": {
            "applied": patch_applied,
            "summary": patch_summary,
            "commands": patch_commands,
            "generatedDiff": generated_diff,
            "changedPaths": changed_paths,
        },
        "verification": verification,
        "rollback": {"ok": True, "summary": "Canonical repo was not modified until generated diff passed validation and verification."},
        "inspectResults": diagnostics,
        "repairResults": [],
    }


def no_tool_loop_patch(plan: dict, blocker: str, *, raw_responses=None, action_log=None, verification=None, cleanup_results=None) -> dict:
    verification = verification or {"ok": False, "results": ["No verification run."]}
    return finish_tool_loop(
        plan=plan,
        target_repo="map_platform",
        final_args=normalize_finish_args({
            "summary": "Tool-loop implementation did not produce a patch.",
            "blockers": [blocker],
        }),
        changed_paths=[],
        generated_diff="",
        action_log=action_log or [],
        raw_responses=raw_responses or [],
        patch_applied=False,
        patch_summary="No repository files changed.",
        patch_commands=cleanup_results or [],
        verification=verification,
        blockers=[],
    )
