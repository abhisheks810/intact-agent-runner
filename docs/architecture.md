# Architecture

## Purpose

`intact-agent-runner` is the future host for individual deep agents.

Current mode:

- deterministic local orchestration;
- agent role selection;
- run-log creation;
- mandatory host-context preflight;
- OpenAI-backed bounded patch generation;
- repo-local verification;
- commit-and-push finalization.

Future mode:

- connect to `intact-mcp-server` as an MCP client;
- call MCP tools directly instead of reading artifacts only;
- execute named deep agents as independent workers;
- expose an agent dashboard.

## Components

| Component | Responsibility |
| --- | --- |
| `src/cli.js` | Command-line entrypoint. |
| `src/runner.js` | Product runner and role orchestration. |
| `src/host-loop.js` | Host-loop replacement for scheduled map-platform development. |
| `src/development-agent.js` | Bounded OpenAI decision parsing, patch application, verification, and Git finalization. |
| `src/commands.js` | Child-process wrapper used for preflight, verification, and Git commands. |
| `src/agents.js` | Loads and selects agent specs. |
| `src/context.js` | Reads tasks, feedback, proposals, results, and run logs. |
| `src/llm.js` | Provider adapter boundary, including OpenAI Responses API. |
| `src/run-log.js` | Writes agent run audit logs and implementation results. |

## Why This Exists Beside Codex

Codex app automations could not reliably pass the GitHub DNS/push gate in this environment. This runner is designed to run from the host through `launchd`, so network and Git finalization happen in the same context a developer shell uses.

Target relationship:

```text
launchd at :00/:20/:40
  -> scripts/run-map-platform-loop.sh
      -> npm run host-run:map
          -> canonical preflight
          -> OpenAI-backed bounded agent
          -> product repo verification
          -> commit/push
          -> MCP artifact logs
```

## Scheduling

The LaunchAgent template lives at:

```text
launchd/com.intact.map-platform-loop.plist
```

Install or refresh it with:

```bash
cd /Users/abhisheksrivastava/intact-agent-runner
bash scripts/install-launchd-map-platform-loop.sh
```

The wrapper uses `/tmp/intact-map-platform-host-runner.lock` to prevent overlapping runs.
