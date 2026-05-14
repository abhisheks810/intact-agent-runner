# Architecture

## Purpose

`intact-agent-runner` is the future host for individual deep agents.

Current mode:

- deterministic local orchestration;
- agent role selection;
- run-log creation;
- mandatory host-context preflight;
- OpenAI-backed structured tool-loop development;
- scoped file writes in an isolated temporary Git worktree;
- deterministic generated-diff validation before canonical repo mutation;
- repo-local verification before apply/commit;
- scoped staging of agent-owned changed paths only;
- read-only `intact-mcp-server` stdio tool calls for map-platform context and doctors;
- repo-local verification;
- commit-and-push finalization.

Future mode:

- execute named deep agents as independent workers;
- expose an agent dashboard;
- optionally enable scoped MCP write tools only after explicit change-request approval.

## Components

| Component | Responsibility |
| --- | --- |
| `intact_agent_runner/cli.py` | Command-line entrypoint. |
| `intact_agent_runner/runner.py` | Product runner and role orchestration. |
| `intact_agent_runner/host_loop.py` | Host-loop replacement for scheduled map-platform development. |
| `intact_agent_runner/development_agent.py` | Bounded OpenAI decision parsing, patch application, verification, and Git finalization. |
| `intact_agent_runner/tool_loop.py` | Structured model action loop that discovers MCP tool schemas, calls MCP tools against a temporary worktree, captures generated diffs, and records diagnostics. |
| `intact_agent_runner/worktree.py` | Temporary Git worktree creation, generated diff validation, canonical diff apply, verification, and cleanup. |
| `intact_agent_runner/commands.py` | Child-process wrapper used for preflight, verification, and Git commands. |
| `intact_agent_runner/agents.py` | Loads and selects agent specs. |
| `intact_agent_runner/context.py` | Reads tasks, feedback, proposals, results, run logs, repo intelligence, and MCP tool context. |
| `intact_agent_runner/mcp_stdio.py` | Minimal MCP JSON-RPC stdio client with bounded response reads. |
| `intact_agent_runner/mcp_context.py` | Calls read-only intact MCP tools for map-platform files, searches, git status, and dry-run doctors. |
| `intact_agent_runner/dashboard.py` | Local web UI and JSON telemetry endpoint for agent runs, results, scheduler logs, repo state, and lock state. |
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
          -> intact-mcp-server stdio context tools
          -> OpenAI-backed structured tool-loop agent
          -> isolated temporary map_platform worktree
          -> generated Git diff validation
          -> product repo verification
          -> scoped-path commit/push
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

## Development Dashboard

The runner includes a local dashboard served with Python stdlib only:

```bash
cd /Users/abhisheksrivastava/intact-agent-runner
npm run dashboard
```

Default URL:

```text
http://127.0.0.1:8791
```

The dashboard exposes `/api/status` and `/api/artifact`. It reads the launchd job state, host-runner lock, local stdout/stderr logs, repo cleanliness, agent-run artifacts, and implementation-result artifacts. It is read-only and uses the same durable MCP artifact store as the scheduled loop.

## MCP Stdio Context

The host runner now starts `/Users/abhisheksrivastava/intact-mcp-server/src/server.js` over MCP stdio during context loading. It keeps `MAP_PLATFORM_WRITE_ENABLED=false` and calls only read-only/context tools by default: `tools/list`, `map_platform_git_status`, `list_map_platform_files`, `search_map_platform`, `read_map_platform_file`, and dry-run map-platform doctor tools. If MCP stdio is unavailable, the runner records the MCP context as unavailable and continues with direct filesystem context instead of crashing the scheduled loop.

## Structured Tool Loop

OpenAI-backed runs no longer ask the model to return a unified diff. The runner starts `intact-mcp-server` against the temporary worktree with `MAP_PLATFORM_WRITE_ENABLED=true`, reads the actual MCP `tools/list` response, and prompts the model with those tool names, descriptions, and schemas. The model returns one JSON action at a time using MCP tool names such as `list_map_platform_directory`, `get_map_platform_file_metadata`, `create_map_platform_change_request`, `write_map_platform_file`, and `run_map_platform_verify`, or the runner-private `finish` action.

All edits happen through MCP tools in a temporary Git worktree created from the canonical target repo. The runner generates the unified diff from Git, checks it with `git diff --check` and `git apply --check --whitespace=nowarn`, runs repo verification in the temporary worktree, then applies the generated diff to the canonical repo only after those gates pass. Git finalization stages only the changed paths returned by the generated diff.

Failed validation or verification leaves the canonical product repo unchanged. Run artifacts include the action log, generated diff, raw model responses, validation output, verification output, and cleanup/finalization status.
