from __future__ import annotations

import os
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE_ROOT = ROOT / "test" / "fixtures"
RUNTIME = tempfile.TemporaryDirectory(prefix="intact-runner-smoke-runtime-")
RUNTIME_ROOT = Path(RUNTIME.name)
RUNTIME_AGENT_ROOT = RUNTIME_ROOT / "agent-runner"
RUNTIME_MCP_ROOT = RUNTIME_ROOT / "mcp"
RUNTIME_HOST_STRATEGY_ROOT = RUNTIME_ROOT / "host_strategy"
shutil.copytree(FIXTURE_ROOT / "mcp", RUNTIME_MCP_ROOT)
shutil.copytree(FIXTURE_ROOT / "host_strategy", RUNTIME_HOST_STRATEGY_ROOT)
(RUNTIME_AGENT_ROOT / "config").mkdir(parents=True)
(RUNTIME_AGENT_ROOT / "data").mkdir(parents=True)
(RUNTIME_AGENT_ROOT / "config" / "runner.config.json").write_text(json.dumps({
    "mcpServerRoot": str(RUNTIME_MCP_ROOT),
    "mapPlatformRoot": str(ROOT),
    "hostStrategyRoot": str(RUNTIME_HOST_STRATEGY_ROOT),
    "activeProduct": "map-platform",
    "llmProvider": "none",
    "openaiModel": "gpt-5.2",
    "defaultAutomationId": "intact-agent-runner-smoke",
    "commitAndPush": False,
}), encoding="utf-8")
os.environ.update({
    "AGENT_RUNNER_ROOT": str(RUNTIME_AGENT_ROOT),
    "MCP_SERVER_ROOT": str(RUNTIME_MCP_ROOT),
    "MAP_PLATFORM_ROOT": str(ROOT),
    "HOST_STRATEGY_ROOT": str(RUNTIME_HOST_STRATEGY_ROOT),
    "LLM_PROVIDER": "none",
    "PYTHONDONTWRITEBYTECODE": "1",
})


def run(args, env=None):
    merged = os.environ.copy()
    merged.update({
        "AGENT_RUNNER_ROOT": str(RUNTIME_AGENT_ROOT),
        "MCP_SERVER_ROOT": str(RUNTIME_MCP_ROOT),
        "MAP_PLATFORM_ROOT": str(ROOT),
        "HOST_STRATEGY_ROOT": str(RUNTIME_HOST_STRATEGY_ROOT),
        "LLM_PROVIDER": "none",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    if env:
        merged.update(env)
    completed = subprocess.run(
        ["python3", "-m", "intact_agent_runner.cli", *args],
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or f"Command failed with {completed.returncode}")
    return completed


plan = run(["plan", "--product", "map-platform"])
if "selectedAgent" not in plan.stdout:
    raise RuntimeError("plan output missing selectedAgent")

result = run(["run", "--product", "map-platform"])
if "runPath" not in result.stdout:
    raise RuntimeError("run output missing runPath")

try:
    run(["run", "--product", "map-platform"], {
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "",
    })
    raise RuntimeError("openai mode without key unexpectedly passed")
except RuntimeError as error:
    if "OPENAI_API_KEY is required" not in str(error):
        raise

from intact_agent_runner.config import load_config
from intact_agent_runner.dashboard import collect_dashboard_state, render_dashboard_html
from intact_agent_runner.repo_intelligence import build_repo_intelligence
from intact_agent_runner.mcp_context import build_mcp_tool_context
from intact_agent_runner.development_agent import build_inspection_followup_prompt, build_patch_repair_prompt, check_agent_patch, finalize_repo_paths, parse_inspect_command, validate_patch_paths
from intact_agent_runner.run_log import sanitize_markdown
from intact_agent_runner.tool_loop import run_tool_loop_implementation

config = load_config()
dashboard_state = collect_dashboard_state(config)
if "scheduler" not in dashboard_state or "repos" not in dashboard_state:
    raise RuntimeError("dashboard state missing scheduler or repo telemetry")
if "Intact Agent Development" not in render_dashboard_html():
    raise RuntimeError("dashboard HTML missing expected title")
intelligence = build_repo_intelligence(config)
if "map_platform" not in intelligence:
    raise RuntimeError("repo intelligence missing map_platform packet")
if "pathPolicy" not in intelligence["map_platform"]:
    raise RuntimeError("repo intelligence missing path policy")
route_map = intelligence["map_platform"].get("routeEndpointMap", {})
if route_map.get("backendRouteEndpoint") not in {"GET /route?origin=lat,lon&destination=lat,lon", "unknown"}:
    raise RuntimeError("repo intelligence has unexpected route endpoint shape")
mcp_context = build_mcp_tool_context(config)
if mcp_context.get("status") not in {"ok", "unavailable"}:
    raise RuntimeError("MCP tool context returned unexpected status")

bad_decision = {
    "targetRepo": "map_platform",
    "unifiedDiff": f"diff --git a/{Path(config.map_platform_root).name}/bad.md b/{Path(config.map_platform_root).name}/bad.md\nnew file mode 100644\n--- /dev/null\n+++ b/{Path(config.map_platform_root).name}/bad.md\n@@ -0,0 +1 @@\n+bad\n",
}
errors = validate_patch_paths(config, bad_decision)
if not errors:
    raise RuntimeError("nested repo-name patch path was not rejected")

good_decision = {
    "targetRepo": "map_platform",
    "unifiedDiff": "diff --git a/docs/good.md b/docs/good.md\nnew file mode 100644\n--- /dev/null\n+++ b/docs/good.md\n@@ -0,0 +1 @@\n+good\n",
}
if validate_patch_paths(config, good_decision):
    raise RuntimeError("valid repo-relative patch path was rejected")

check = check_agent_patch(config, good_decision)
if not check["ok"]:
    raise RuntimeError("valid patch did not pass git apply --check")
repair_prompt = build_patch_repair_prompt({"selectedSpec": {}, "context": {"repoIntelligence": {}, "mcpToolContext": {}}}, {
    "agentRole": "qa-evaluation-agent",
    "selectedTask": "test",
    "targetRepo": "map_platform",
    "summary": "test",
    "unifiedDiff": "bad",
    "changedFiles": [],
    "verification": [],
    "commitMessage": "test",
    "deferred": [],
    "blockers": [],
}, {"summary": "Patch check failed"})
if "corrected JSON" not in repair_prompt or "Patch validation failure" not in repair_prompt:
    raise RuntimeError("patch repair prompt missing required guidance")


if not parse_inspect_command("rg route backend/routers/route.py")["ok"]:
    raise RuntimeError("safe rg inspect command was blocked")
if parse_inspect_command("git add README.md")["ok"]:
    raise RuntimeError("write git command was allowed")
if parse_inspect_command("rg route backend | cat")["ok"]:
    raise RuntimeError("shell pipeline was allowed")
followup_prompt = build_inspection_followup_prompt({"selectedSpec": {}, "context": {"repoIntelligence": {}, "mcpToolContext": {}}}, {
    "agentRole": "qa-evaluation-agent",
    "selectedTask": "inspect test",
    "targetRepo": "map_platform",
    "summary": "inspect test",
    "changedFiles": [],
    "verification": [],
    "commitMessage": "test",
    "deferred": [],
    "blockers": [],
}, ["$ rg route backend/main.py\nbackend/main.py:21 route"] )
if "Inspection command outputs" not in followup_prompt or "backend/main.py" not in followup_prompt:
    raise RuntimeError("inspection follow-up prompt missing command output")

if "trailing   \n" in sanitize_markdown("trailing   \nclean\n"):
    raise RuntimeError("run-log markdown sanitizer did not strip trailing whitespace")

class FakeToolProvider:
    name = "fake"

    def __init__(self, expected_sha):
        self.expected_sha = expected_sha
        self.index = 0

    def complete(self, *, instructions, prompt):
        change_request = re.search(r'map-platform-change-requests/[^"\s]+\.md', prompt)
        responses = [
            {"tool": "list_dir", "args": {"path": "."}, "reason": "deliberately request an unavailable alias to exercise correction"},
            {"tool": "list_map_platform_directory", "args": {"path": "."}, "reason": "inspect repository root through MCP"},
            {"tool": "get_map_platform_file_metadata", "args": {"path": "README.md"}, "reason": "capture hash before scoped write"},
            {"tool": "create_map_platform_change_request", "args": {"title": "Structured Tool Loop Smoke", "agent": "qa-evaluation-agent", "objective": "Verify MCP-backed runner writes.", "allowed_files": ["README.md"], "verification": ["run_map_platform_verify"], "approval_note": "Smoke test scoped write."}, "reason": "approve scoped write"},
            {"tool": "write_map_platform_file", "args": {"path": "README.md", "content": "# Test map platform\n\nUpdated through MCP-backed tool loop.\n", "expected_sha256": self.expected_sha, "change_request_path": change_request.group(0) if change_request else "map-platform-change-requests/missing.md", "approval_note": "Smoke test scoped write."}, "reason": "write through MCP"},
            {"tool": "run_map_platform_verify", "args": {"timeout_ms": 10000}, "reason": "verify through MCP"},
            {"tool": "finish", "args": {"summary": "Updated README through MCP-backed tool loop.", "changed_files": ["README.md"], "verification": ["run_map_platform_verify"], "commit_message": "agent-run: structured MCP tool loop smoke", "deferred": [], "blockers": []}, "reason": "done"},
        ]
        if self.index >= len(responses):
            raise RuntimeError("unexpected extra tool-loop call")
        value = responses[self.index]
        self.index += 1
        return {"text": __import__("json").dumps(value)}


class FakeNoFinishProvider:
    name = "fake"

    def __init__(self, expected_sha):
        self.expected_sha = expected_sha
        self.index = 0

    def complete(self, *, instructions, prompt):
        change_request = re.search(r'map-platform-change-requests/[^"\s]+\.md', prompt)
        responses = [
            {"tool": "get_map_platform_file_metadata", "args": {"path": "README.md"}, "reason": "capture hash before scoped write"},
            {"tool": "create_map_platform_change_request", "args": {"title": "No Finish Smoke", "agent": "qa-evaluation-agent", "objective": "Verify no-finish fallback.", "allowed_files": ["README.md"], "verification": ["run_map_platform_verify"], "approval_note": "Smoke test scoped write."}, "reason": "approve scoped write"},
            {"tool": "write_map_platform_file", "args": {"path": "README.md", "content": "# Test map platform\n\nUpdated without explicit finish.\n", "expected_sha256": self.expected_sha, "change_request_path": change_request.group(0) if change_request else "map-platform-change-requests/missing.md", "approval_note": "Smoke test scoped write."}, "reason": "write through MCP"},
            {"tool": "run_map_platform_verify", "args": {"timeout_ms": 10000}, "reason": "verify through MCP"},
        ]
        if self.index < len(responses):
            value = responses[self.index]
        else:
            value = {"tool": "map_platform_git_diff", "args": {}, "reason": "inspect current generated diff"}
        self.index += 1
        return {"text": __import__("json").dumps(value)}


with tempfile.TemporaryDirectory(prefix="intact-runner-tool-loop-") as temp_root:
    repo = Path(temp_root) / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, text=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "runner@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Runner Test"], cwd=repo, check=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "verify.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n", encoding="utf-8")
    original_readme = "# Test map platform\n"
    (repo / "README.md").write_text(original_readme, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, text=True, capture_output=True)
    temp_mcp = Path(temp_root) / "mcp"
    (temp_mcp / "src").mkdir(parents=True)
    shutil.copyfile("/Users/abhisheksrivastava/intact-mcp-server/src/server.js", temp_mcp / "src" / "server.js")
    fake_config = SimpleNamespace(
        allowed_repo_roots={"map_platform": str(repo)},
        mcp_server_root=str(temp_mcp),
        map_platform_root=str(repo),
        host_strategy_root=str(RUNTIME_HOST_STRATEGY_ROOT),
    )
    fake_plan = {
        "selectedAgent": "qa-evaluation-agent",
        "recommendedFocus": "structured tool-loop smoke",
        "selectedSpec": {"spec": "test spec"},
        "context": {
            "strategySnippets": [],
            "feedbackSnippets": [],
            "tasks": [],
            "implementationResults": [],
            "repoIntelligence": {},
            "mcpToolContext": {},
        },
    }
    expected_sha = hashlib.sha256(original_readme.encode("utf-8")).hexdigest()
    implementation = run_tool_loop_implementation(fake_config, FakeToolProvider(expected_sha), fake_plan)
    if not implementation["patch"]["applied"]:
        raise RuntimeError("tool loop did not apply verified generated diff")
    if "Updated through MCP-backed tool loop" not in (repo / "README.md").read_text(encoding="utf-8"):
        raise RuntimeError("tool loop did not apply MCP-generated file edit to canonical repo")
    status_check = subprocess.run(["git", "status", "--short", "--untracked-files=all"], cwd=repo, check=True, text=True, capture_output=True)
    if "README.md" not in status_check.stdout:
        raise RuntimeError("tool loop did not leave a reviewable canonical change")
    fake_config.commit_and_push = False
    finalized = finalize_repo_paths(fake_config, "map_platform", "agent-run: structured MCP tool loop smoke", ["README.md"])
    if not finalized["ok"]:
        raise RuntimeError("scoped finalization failed")
    clean_check = subprocess.run(["git", "status", "--short"], cwd=repo, check=True, text=True, capture_output=True)
    if clean_check.stdout.strip():
        raise RuntimeError(f"scoped finalization left temp repo dirty: {clean_check.stdout}")

with tempfile.TemporaryDirectory(prefix="intact-runner-tool-loop-no-finish-") as temp_root:
    repo = Path(temp_root) / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, text=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "runner@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Runner Test"], cwd=repo, check=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "verify.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n", encoding="utf-8")
    original_readme = "# Test map platform\n"
    (repo / "README.md").write_text(original_readme, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, text=True, capture_output=True)
    temp_mcp = Path(temp_root) / "mcp"
    (temp_mcp / "src").mkdir(parents=True)
    shutil.copyfile("/Users/abhisheksrivastava/intact-mcp-server/src/server.js", temp_mcp / "src" / "server.js")
    fake_config = SimpleNamespace(
        allowed_repo_roots={"map_platform": str(repo)},
        mcp_server_root=str(temp_mcp),
        map_platform_root=str(repo),
        host_strategy_root=str(RUNTIME_HOST_STRATEGY_ROOT),
    )
    fake_plan = {
        "selectedAgent": "qa-evaluation-agent",
        "recommendedFocus": "structured tool-loop no-finish smoke",
        "selectedSpec": {"spec": "test spec"},
        "context": {
            "strategySnippets": [],
            "feedbackSnippets": [],
            "tasks": [],
            "implementationResults": [],
            "repoIntelligence": {},
            "mcpToolContext": {},
        },
    }
    expected_sha = hashlib.sha256(original_readme.encode("utf-8")).hexdigest()
    implementation = run_tool_loop_implementation(fake_config, FakeNoFinishProvider(expected_sha), fake_plan)
    if not implementation["patch"]["applied"]:
        raise RuntimeError("no-finish fallback did not apply verified generated diff")
    if implementation["decision"]["blockers"]:
        raise RuntimeError(f"no-finish fallback incorrectly reported blockers: {implementation['decision']['blockers']}")

print("smoke test passed")
