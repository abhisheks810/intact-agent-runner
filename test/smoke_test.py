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
from intact_agent_runner.development_agent import validate_patch_paths

config = load_config()
intelligence = build_repo_intelligence(config)
if "map_platform" not in intelligence:
    raise RuntimeError("repo intelligence missing map_platform packet")
if "pathPolicy" not in intelligence["map_platform"]:
    raise RuntimeError("repo intelligence missing path policy")
route_map = intelligence["map_platform"].get("routeEndpointMap", {})
if route_map.get("backendRouteEndpoint") not in {"GET /route?origin=lat,lon&destination=lat,lon", "unknown"}:
    raise RuntimeError("repo intelligence has unexpected route endpoint shape")

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

print("smoke test passed")
