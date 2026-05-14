from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE_ROOT = ROOT / "test" / "fixtures"


def run(args, env=None):
    merged = os.environ.copy()
    merged.update({
        "AGENT_RUNNER_ROOT": str(ROOT),
        "MCP_SERVER_ROOT": str(FIXTURE_ROOT / "mcp"),
        "MAP_PLATFORM_ROOT": str(ROOT),
        "HOST_STRATEGY_ROOT": str(FIXTURE_ROOT / "host_strategy"),
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
from intact_agent_runner.repo_intelligence import build_repo_intelligence
from intact_agent_runner.mcp_context import build_mcp_tool_context
from intact_agent_runner.development_agent import build_patch_repair_prompt, check_agent_patch, validate_patch_paths
from intact_agent_runner.host_loop import repair_until_patch_checks

config = load_config()
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
    "unifiedDiff": "diff --git a/map_platform/bad.md b/map_platform/bad.md\nnew file mode 100644\n--- /dev/null\n+++ b/map_platform/bad.md\n@@ -0,0 +1 @@\n+bad\n",
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


class FakeRepairProvider:
    name = "fake"

    def __init__(self, repaired_text):
        self.repaired_text = repaired_text
        self.calls = 0

    def complete(self, *, instructions, prompt):
        self.calls += 1
        if "Patch validation failure" not in prompt:
            raise RuntimeError("repair prompt did not include validation failure")
        return {"text": self.repaired_text}


initial_bad_decision = {
    "agentRole": "qa-evaluation-agent",
    "selectedTask": "repair test",
    "targetRepo": "map_platform",
    "summary": "repair test",
    "unifiedDiff": "diff --git a/docs/bad.md b/docs/bad.md\n@@ -1 +1 @@\n+bad\n",
    "changedFiles": ["docs/good.md"],
    "verification": [],
    "commitMessage": "test",
    "deferred": [],
    "blockers": [],
}
repaired_json = {
    "agent_role": "qa-evaluation-agent",
    "selected_task": "repair test",
    "target_repo": "map_platform",
    "summary": "repair test",
    "unified_diff": good_decision["unifiedDiff"],
    "changed_files": ["docs/good.md"],
    "verification": [],
    "commit_message": "test",
    "deferred": [],
    "blockers": [],
}
provider = FakeRepairProvider(__import__("json").dumps(repaired_json))
repaired, attempts = repair_until_patch_checks(
    config,
    provider,
    {"selectedSpec": {}, "context": {"repoIntelligence": {}, "mcpToolContext": {}}},
    initial_bad_decision,
    max_repairs=1,
)
if provider.calls != 1:
    raise RuntimeError("patch repair provider was not called exactly once")
if repaired["unifiedDiff"] != good_decision["unifiedDiff"]:
    raise RuntimeError("patch repair did not return corrected diff")
if not any("Patch validation attempt 2" in item for item in attempts):
    raise RuntimeError("patch repair attempts did not record second validation")

print("smoke test passed")
