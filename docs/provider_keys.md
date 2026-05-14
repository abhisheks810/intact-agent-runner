# Provider Keys

No API key is required for deterministic dry-run mode.

The host runner needs an OpenAI key when `LLM_PROVIDER=openai`.

## OpenAI

Environment:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.2
```

Recommended local-only env file:

```text
~/.config/intact-agent-runner/map-platform.env
```

Example:

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5.2
export COMMIT_AND_PUSH=1
```

`scripts/run-map-platform-loop.sh` loads that file automatically when it exists.

## Policy

- Store keys in environment variables or a secrets manager.
- Do not write keys into `.env` unless `.env` is ignored and local-only.
- Do not expose production credentials to agents until approval controls exist.
- Do not commit `~/.config/intact-agent-runner/map-platform.env` or any copied secret file.
