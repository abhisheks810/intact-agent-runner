# Intact Agent Runner

`intact-agent-runner` is the self-hosted agent orchestration layer for the Intact product ecosystem.

It is designed to sit between:

- `intact-mcp-server`: strategy, tools, artifacts, agent specs, and audit memory;
- product repos such as `map_platform`;
- future LLM providers and model APIs;
- Codex automations or any other scheduler.

## Current Status

This first implementation is dependency-free and local-first.

It can:

- load map-platform deep-agent specs;
- inspect MCP artifact folders;
- choose a runnable agent role;
- create a structured agent run log (falls back to `AGENT_RUNNER_ROOT/data/agent-runs` when `MCP_SERVER_ROOT` is not writable);
- run in dry-run mode without API keys;
- provide a stable place to add LLM-backed execution later.

It does **not** yet autonomously edit code through an LLM. That requires an API key and a provider adapter.

## Architecture

```text
Codex automation / cron / manual command
  -> intact-agent-runner
      -> loads agent specs from intact-mcp-server/data/agent-specs
      -> reads tasks/proposals/feedback/artifacts
      -> optionally calls an LLM provider
      -> writes agent run logs
      -> later: calls MCP tools directly over stdio

intact-mcp-server
  -> MCP tools/resources
  -> artifact store

map_platform
  -> product repo
```

## Run

```bash
npm start
```

Run one map-platform iteration:

```bash
npm run run:map
```

Show the plan without writing:

```bash
npm run plan:map
```

## Environment

Defaults:

```bash
MCP_SERVER_ROOT=/Users/abhisheksrivastava/intact-mcp-server
MAP_PLATFORM_ROOT=/Users/abhisheksrivastava/map_platform
AGENT_RUNNER_ROOT=/Users/abhisheksrivastava/intact-agent-runner
LLM_PROVIDER=none
```

Future provider examples:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

No API key is required for the current dry-run/local orchestration mode.

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

## Next Integration Step

The next step is to make Codex automations call:

```bash
cd /Users/abhisheksrivastava/intact-agent-runner
npm run run:map
```

instead of directly acting as the whole orchestrator.
