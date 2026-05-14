from __future__ import annotations

import json
import sys

from .config import load_config
from .host_loop import run_host_map_platform_loop
from .runner import plan_map_platform, run_map_platform


def arg_value(name: str, fallback=None):
    try:
        index = sys.argv.index(name)
    except ValueError:
        return fallback
    return sys.argv[index + 1] if index + 1 < len(sys.argv) else fallback


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    product = arg_value("--product", "map-platform")
    if product != "map-platform":
        raise RuntimeError(f"Unsupported product: {product}")

    config = load_config()

    if command == "plan":
        plan = plan_map_platform(config)
        print(json.dumps({
            "product": plan["product"],
            "selectedAgent": plan["selectedAgent"],
            "recommendedFocus": plan["recommendedFocus"],
            "availableAgents": [agent["slug"] for agent in plan["agents"]],
            "recentTasks": [task["relative"] for task in plan["context"]["tasks"]],
        }, indent=2))
        return 0

    if command == "run":
        result = run_map_platform(config, dry_run=config.llm_provider == "none")
        print(json.dumps({
            "agent": result["agent"],
            "status": result["status"],
            "runPath": result["runPath"],
            "summary": result["summary"],
            "blockers": result["blockers"],
        }, indent=2))
        return 0

    if command == "host-run":
        result = run_host_map_platform_loop(config)
        print(json.dumps({
            "agent": result["agent"],
            "status": result["status"],
            "runPath": result["runPath"],
            "resultPath": result["resultPath"],
            "summary": result["summary"],
            "blockers": result["blockers"],
        }, indent=2))
        return 0

    raise RuntimeError(f"Unsupported command: {command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
