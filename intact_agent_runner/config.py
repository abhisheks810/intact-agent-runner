from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass
class Config:
    raw: dict
    agent_runner_root: str
    mcp_server_root: str
    map_platform_root: str
    host_strategy_root: str
    llm_provider: str
    openai_model: str
    automation_id: str
    commit_and_push: bool
    allowed_repo_roots: dict[str, str]


def load_config() -> Config:
    root = os.environ.get("AGENT_RUNNER_ROOT") or os.getcwd()
    config_path = Path(root) / "config" / "runner.config.json"
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    mcp_server_root = os.environ.get("MCP_SERVER_ROOT") or raw["mcpServerRoot"]
    map_platform_root = os.environ.get("MAP_PLATFORM_ROOT") or raw["mapPlatformRoot"]
    host_strategy_root = (
        os.environ.get("HOST_STRATEGY_ROOT")
        or raw.get("hostStrategyRoot")
        or "/Users/abhisheksrivastava/host_strategy"
    )
    commit_env = os.environ.get("COMMIT_AND_PUSH")
    commit_and_push = commit_env == "1" if commit_env is not None else raw.get("commitAndPush") is not False
    return Config(
        raw=raw,
        agent_runner_root=root,
        mcp_server_root=mcp_server_root,
        map_platform_root=map_platform_root,
        host_strategy_root=host_strategy_root,
        llm_provider=os.environ.get("LLM_PROVIDER") or raw.get("llmProvider") or "none",
        openai_model=os.environ.get("OPENAI_MODEL") or raw.get("openaiModel") or "gpt-5.2",
        automation_id=os.environ.get("AUTOMATION_ID") or raw["defaultAutomationId"],
        commit_and_push=commit_and_push,
        allowed_repo_roots={
            "map_platform": map_platform_root,
            "intact-mcp-server": mcp_server_root,
            "intact-agent-runner": root,
        },
    )
