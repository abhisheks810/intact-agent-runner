# Architecture

## Purpose

`intact-agent-runner` is the future host for individual deep agents.

Current mode:

- deterministic local orchestration;
- agent role selection;
- run-log creation;
- no LLM calls;
- no direct MCP stdio calls yet.

Future mode:

- connect to `intact-mcp-server` as an MCP client;
- call MCP tools directly;
- use LLM provider adapters for reasoning/code generation;
- execute named deep agents as independent workers;
- expose an agent dashboard.

## Components

| Component | Responsibility |
| --- | --- |
| `src/cli.js` | Command-line entrypoint. |
| `src/runner.js` | Product runner and role orchestration. |
| `src/agents.js` | Loads and selects agent specs. |
| `src/context.js` | Reads tasks, feedback, proposals, results, and run logs. |
| `src/llm.js` | Provider adapter boundary. |
| `src/run-log.js` | Writes agent run audit logs. |

## Why This Exists Beside Codex

Codex automations are currently the scheduler. This runner becomes the self-hosted execution layer that Codex can call.

Target relationship:

```text
Codex automation
  -> npm run run:map
      -> intact-agent-runner
          -> MCP server tools/artifacts
          -> product repo
          -> LLM provider
```

## Current Codex Integration

The three map-platform development automations now call this runner first:

- `map-platform-daily-agent-loop`
- `map-platform-daily-agent-loop-20`
- `map-platform-daily-agent-loop-40`

Current command:

```bash
cd /Users/abhisheksrivastava/intact-agent-runner
npm run run:map
```

Because `LLM_PROVIDER=none` by default, this currently performs deterministic orchestration and run-log creation. Codex may then continue with supervised low-risk implementation work in the same scheduled cycle.
