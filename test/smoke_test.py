from __future__ import annotations

import os
from pathlib import Path
import json
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
from intact_agent_runner.edit_session import EditSession
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

with tempfile.TemporaryDirectory(prefix="intact-runner-edit-session-") as temp_root:
    temp_path = Path(temp_root)
    (temp_path / "README.md").write_text("hello\n", encoding="utf-8")
    session = EditSession(repo_root=str(temp_path), repo_name="map_platform")
    read = session.read_file("README.md")
    if not read.ok or not read.data.get("sha256"):
        raise RuntimeError("edit session did not return file hash")
    stale = session.write_file_full("README.md", "updated\n", expected_sha256="bad")
    if stale.ok:
        raise RuntimeError("edit session allowed stale write")
    write = session.write_file_full("README.md", "updated\n", expected_sha256=read.data["sha256"])
    if not write.ok:
        raise RuntimeError(f"edit session rejected valid scoped write: {write.output}")
    if session.write_file_full("../escape.md", "bad\n").ok:
        raise RuntimeError("edit session allowed path escape")


class FakeToolProvider:
    name = "fake"

    def __init__(self):
        self.responses = [
            {"tool": "add_file", "args": {"path": "docs/agent-smoke.md", "content": "# Agent smoke\n\nGenerated through structured tools.\n"}, "reason": "add a small doc"},
            {"tool": "finish", "args": {"summary": "Added a structured tool-loop smoke doc.", "changed_files": ["docs/agent-smoke.md"], "verification": ["verify.sh"], "commit_message": "agent-run: structured tool loop smoke", "deferred": [], "blockers": []}, "reason": "done"},
        ]
        self.index = 0

    def complete(self, *, instructions, prompt):
        if self.index >= len(self.responses):
            raise RuntimeError("unexpected extra tool-loop call")
        value = self.responses[self.index]
        self.index += 1
        return {"text": __import__("json").dumps(value)}


with tempfile.TemporaryDirectory(prefix="intact-runner-tool-loop-") as temp_root:
    repo = Path(temp_root)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, text=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "runner@example.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Runner Test"], cwd=repo, check=True)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "verify.sh").write_text("#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n", encoding="utf-8")
    (repo / "README.md").write_text("# Test map platform\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, text=True, capture_output=True)
    fake_config = SimpleNamespace(allowed_repo_roots={"map_platform": str(repo)})
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
    implementation = run_tool_loop_implementation(fake_config, FakeToolProvider(), fake_plan)
    if not implementation["patch"]["applied"]:
        raise RuntimeError("tool loop did not apply verified generated diff")
    if not (repo / "docs" / "agent-smoke.md").exists():
        raise RuntimeError("tool loop did not apply generated file to canonical repo")
    status_check = subprocess.run(["git", "status", "--short", "--untracked-files=all"], cwd=repo, check=True, text=True, capture_output=True)
    if "docs/agent-smoke.md" not in status_check.stdout:
        raise RuntimeError("tool loop did not leave a reviewable canonical change")
    fake_config.commit_and_push = False
    finalized = finalize_repo_paths(fake_config, "map_platform", "agent-run: structured tool loop smoke", ["docs/agent-smoke.md"])
    if not finalized["ok"]:
        raise RuntimeError("scoped finalization failed")
    clean_check = subprocess.run(["git", "status", "--short"], cwd=repo, check=True, text=True, capture_output=True)
    if clean_check.stdout.strip():
        raise RuntimeError("scoped finalization left temp repo dirty")

print("smoke test passed")
