from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
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

print("smoke test passed")
