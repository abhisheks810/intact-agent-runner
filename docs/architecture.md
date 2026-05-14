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
| `intact_agent_runner/cli.py` | Command-line entrypoint. |
| `intact_agent_runner/runner.py` | Product runner and role orchestration. |
| `intact_agent_runner/host_loop.py` | Host-loop replacement for scheduled map-platform development. |
| `intact_agent_runner/development_agent.py` | Bounded OpenAI decision parsing, patch application, verification, and Git finalization. |
| `intact_agent_runner/commands.py` | Child-process wrapper used for preflight, verification, and Git commands. |
| `intact_agent_runner/agents.py` | Loads and selects agent specs. |
| `intact_agent_runner/context.py` | Reads tasks, feedback, proposals, results, and run logs. |
| `intact_agent_runner/llm.py` | Provider adapter boundary, including OpenAI Responses API. |
| `intact_agent_runner/run_log.py` | Writes agent run audit logs and implementation results. |

## Why This Exists Beside Codex

Codex app automations could not reliably pass the GitHub DNS/push gate in this environment. This runner is designed to run from the host through `launchd`, so network and Git finalization happen in the same context a developer shell uses.

Target relationship:

```text
launchd at :00/:20/:40
  -> scripts/run-map-platform-loop.sh
      -> python3 -m intact_agent_runner.cli host-run --product map-platform
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
