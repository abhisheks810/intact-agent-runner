# Intact Agent Runner

`intact-agent-runner` is the self-hosted agent orchestration layer for the Intact product ecosystem.

It is designed to sit between:

- `intact-mcp-server`: strategy, tools, artifacts, agent specs, and audit memory;
- product repos such as `map_platform`;
- future LLM providers and model APIs;
- Codex automations or any other scheduler.

## Current Status

This implementation is dependency-free and local-first by default.
The runtime is a Python package under `intact_agent_runner/`. The `npm` scripts remain as compatibility shims for existing operator commands.

It can:

- load map-platform deep-agent specs;
- inspect MCP artifact folders;
- invoke read-only `intact-mcp-server` tools over MCP stdio for map-platform context and doctors;
- choose a runnable agent role;
- create a structured agent run log (falls back to `AGENT_RUNNER_ROOT/data/agent-runs` when `MCP_SERVER_ROOT` is not writable);
- run in dry-run mode without API keys;
- run the mandatory map-platform preflight from host context;
- call the OpenAI Responses API when `LLM_PROVIDER=openai`;
- apply a bounded unified diff from the selected agent;
- run repo-local verification;
- commit and push verified changes when `COMMIT_AND_PUSH=1`;
- write both agent-run and implementation-result artifacts.

## Architecture

```text
launchd / manual command
  -> intact-agent-runner
      -> loads agent specs from intact-mcp-server/data/agent-specs
      -> reads tasks/proposals/feedback/artifacts
      -> invokes read-only intact-mcp-server stdio tools
      -> runs canonical map_platform preflight
      -> optionally calls OpenAI for a bounded patch
      -> verifies, commits, and pushes
      -> writes agent run logs and implementation results

intact-mcp-server
  -> MCP tools/resources
  -> artifact store

map_platform
  -> product repo
```

## Run

```bash
python3 -m intact_agent_runner.cli run --product map-platform
```

Run one map-platform iteration:

```bash
python3 -m intact_agent_runner.cli run --product map-platform
```

Run the host-loop replacement for the old automation:

```bash
python3 -m intact_agent_runner.cli host-run --product map-platform
```

Show the plan without writing:

```bash
python3 -m intact_agent_runner.cli plan --product map-platform
```

The existing compatibility commands still work:

```bash
npm run plan:map
npm run run:map
npm run host-run:map
```

## Environment

Defaults:

```bash
MCP_SERVER_ROOT=/Users/abhisheksrivastava/intact-mcp-server
MAP_PLATFORM_ROOT=/Users/abhisheksrivastava/map_platform
AGENT_RUNNER_ROOT=/Users/abhisheksrivastava/intact-agent-runner
LLM_PROVIDER=none
OPENAI_MODEL=gpt-5.2
COMMIT_AND_PUSH=1
MCP_STDIO_ENABLED=1
```

OpenAI-backed host-runner example:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

No API key is required for dry-run/local orchestration mode.

## Host Runner

The launchd wrapper is:

```bash
/Users/abhisheksrivastava/intact-agent-runner/scripts/run-map-platform-loop.sh
```

It loads optional local environment from the repo-local ignored file:

```bash
/Users/abhisheksrivastava/intact-agent-runner/.env
```

Example local env file:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5.2
export COMMIT_AND_PUSH=1
MCP_STDIO_ENABLED=1
```

Install the LaunchAgent:

```bash
cd /Users/abhisheksrivastava/intact-agent-runner
bash scripts/install-launchd-map-platform-loop.sh
```

The LaunchAgent runs at minutes `:00`, `:20`, and `:40`. Local stdout/stderr logs are written under `logs/`, which is ignored by Git.

## Agent Roles

Map-platform agent roles are loaded from:

```text
/Users/abhisheksrivastava/intact-mcp-server/data/agent-specs/map-platform/
```

Current roles:

- map-product-strategist
- geo-data-agent
- backend-api-agent
- frontend-ux-agent
- accessibility-layer-agent
- routing-tiles-agent
- qa-evaluation-agent
- platform-infra-agent

## Manual Smoke Commands

Dry-run orchestration:

```bash
cd /Users/abhisheksrivastava/intact-agent-runner
python3 -m intact_agent_runner.cli run --product map-platform
```

Host-loop replacement:

```bash
cd /Users/abhisheksrivastava/intact-agent-runner
python3 -m intact_agent_runner.cli host-run --product map-platform
```
