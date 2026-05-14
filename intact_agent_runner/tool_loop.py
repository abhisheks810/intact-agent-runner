from __future__ import annotations

import json

from .commands import command_summary, run_command
from .development_agent import load_decision_json
from .mcp_stdio import McpStdioClient, tool_json, tool_text
from .worktree import (
    TemporaryWorktree,
    apply_verified_diff,
    validate_generated_diff,
    worktree_changed_paths,
    worktree_diff,
)


MAX_ACTION_ROUNDS = 12
RUNNER_FINISH_TOOL = "finish"
AGENT_MCP_TOOL_PREFIXES = (
    "list_map_platform_",
    "read_map_platform_",
    "search_map_platform",
    "get_map_platform_",
    "write_map_platform_",
    "map_platform_git_",
    "run_map_platform_",
    "create_map_platform_change_request",
    "record_map_platform_implementation_result",
)


def tool_loop_instructions() -> str:
    return "\n".join([
        "You are a senior development agent operating through a structured host-runner tool loop.",
        "Return exactly one JSON object per response. Do not include markdown fences or text outside JSON.",
        "Do not return unified diffs. The runner generates diffs from tool writes.",
        "Use only the MCP tool names and schemas provided in the prompt, or finish.",
        "Prefer one small, commit-worthy map_platform task.",
        "Existing files must use get_map_platform_file_metadata before write_map_platform_file.",
        "Use create_map_platform_change_request yourself before write_map_platform_file; do not stop because no prior change request exists.",
        "Do not finish without either writing a scoped file change or recording a concrete external blocker.",
        "No production deploys, secrets changes, destructive Git commands, broad rewrites, or generated output edits.",
    ])


def initial_tool_prompt(plan: dict, tools: list[dict]) -> str:
    shape = {
        "tool": "read_map_platform_file",
        "args": {"path": "README.md"},
        "reason": "why this action is needed",
    }
    finish = {
        "tool": RUNNER_FINISH_TOOL,
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
        "Use only these MCP tools plus finish:",
        json.dumps(summarize_tools_for_prompt(tools), indent=2),
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


def followup_tool_prompt(action_log: list[dict], tools: list[dict]) -> str:
    return "\n".join([
        "Continue the same development run. Return exactly one next JSON tool action.",
        "If the task is complete or blocked, return the finish action.",
        "Available MCP tools are still:",
        json.dumps(summarize_tools_for_prompt(tools), indent=2),
        "Recent tool/action log:",
        json.dumps(action_log[-16:], indent=2),
    ])


def corrective_tool_prompt(action: dict, tools: list[dict], action_log: list[dict]) -> str:
    return "\n".join([
        f"The requested tool `{action.get('tool')}` is not available.",
        "Choose exactly one of the MCP tool names below, or finish. Do not invent aliases.",
        json.dumps(summarize_tools_for_prompt(tools), indent=2),
        "Recent tool/action log:",
        json.dumps(action_log[-12:], indent=2),
    ])


def parse_tool_action(text: str, tool_names: set[str]) -> dict:
    parsed = load_decision_json(text)
    tool = parsed.get("tool")
    args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
    if tool != RUNNER_FINISH_TOOL and tool not in tool_names:
        return {"tool": tool, "args": args, "reason": parsed.get("reason") or "", "unknown": True}
    return {"tool": tool, "args": args, "reason": parsed.get("reason") or ""}


def summarize_tools_for_prompt(tools: list[dict]) -> list[dict]:
    output = []
    for tool in tools:
        output.append({
            "name": tool.get("name"),
            "description": tool.get("description"),
            "inputSchema": tool.get("inputSchema"),
        })
    return output


def agent_tool_subset(listed_tools: dict) -> list[dict]:
    tools = listed_tools.get("tools") if isinstance(listed_tools, dict) else []
    if not isinstance(tools, list):
        return []
    subset = []
    for tool in tools:
        name = tool.get("name") if isinstance(tool, dict) else None
        if isinstance(name, str) and name.startswith(AGENT_MCP_TOOL_PREFIXES):
            subset.append(tool)
    return subset


def run_command_verify(worktree_path: str) -> dict:
    result = run_command(
        "bash",
        ["./scripts/verify.sh"],
        cwd=worktree_path,
        env={"PYTHONPYCACHEPREFIX": "/tmp/map_platform_pycache"},
        timeout_ms=300000,
    )
    return {"ok": result.ok, "results": [command_summary(result)]}


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
            with McpStdioClient(
                config,
                map_platform_root=worktree.path,
                map_platform_write_enabled=True,
                timeout_s=30.0,
            ) as client:
                listed_tools = client.request("tools/list", {})
                tools = agent_tool_subset(listed_tools)
                tool_names = {tool["name"] for tool in tools if isinstance(tool.get("name"), str)}
                prompt = initial_tool_prompt(plan, tools)

                for _ in range(MAX_ACTION_ROUNDS):
                    completion = provider.complete(instructions=tool_loop_instructions(), prompt=prompt)
                    raw_text = completion["text"]
                    raw_responses.append(raw_text)
                    action = parse_tool_action(raw_text, tool_names)
                    action_log.append({"action": action})

                    if action["tool"] == RUNNER_FINISH_TOOL:
                        final_args = normalize_finish_args(action["args"])
                        break

                    if action.get("unknown"):
                        action_log.append({
                            "tool_result": {
                                "tool": action["tool"],
                                "ok": False,
                                "output": "Unknown tool requested; corrective prompt sent with MCP tools/list names.",
                            },
                        })
                        prompt = corrective_tool_prompt(action, tools, action_log)
                        continue

                    try:
                        tool_result = client.call_tool(action["tool"], action["args"])
                        output = tool_text(tool_result)
                        parsed = tool_json(tool_result)
                        ok = not (isinstance(parsed, dict) and parsed.get("ok") is False)
                    except Exception as error:
                        output = str(error)
                        parsed = {}
                        ok = False
                    action_log.append({"tool_result": {"tool": action["tool"], "ok": ok, "output": output, "data": parsed}})
                    if action["tool"] == "run_map_platform_verify":
                        verification = {"ok": ok, "results": [output]}
                    prompt = followup_tool_prompt(action_log, tools)

            if final_args is None:
                final_args = normalize_finish_args({
                    "summary": "Model did not return finish before the action budget; runner evaluated the generated diff deterministically.",
                    "deferred": ["Improve model finishing behavior if repeated runs continue to use the full action budget."],
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
                verification = run_command_verify(worktree.path)
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


def normalize_finish_args(args: dict) -> dict:
    blockers = args.get("blockers") if isinstance(args.get("blockers"), list) else []
    notes = args.get("notes")
    result = args.get("result")
    if result == "blocked" and isinstance(notes, str) and notes.strip() and not blockers:
        blockers = [notes.strip()]
    return {
        "summary": args.get("summary") or "Tool-loop run finished.",
        "changed_files": args.get("changed_files") if isinstance(args.get("changed_files"), list) else [],
        "verification": args.get("verification") if isinstance(args.get("verification"), list) else [],
        "commit_message": args.get("commit_message") or "agent-run: map-platform host iteration",
        "deferred": args.get("deferred") if isinstance(args.get("deferred"), list) else [],
        "blockers": blockers,
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
