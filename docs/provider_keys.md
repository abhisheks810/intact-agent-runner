# Provider Keys

No API key is required for the current deterministic mode.

To enable LLM-backed agents later, the runner will need a provider key.

## OpenAI

Planned environment:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=...
```

Current status:

- provider boundary exists in `src/llm.js`;
- actual OpenAI API call is intentionally not implemented yet;
- no secrets should be committed to this repo.

## Policy

- Store keys in environment variables or a secrets manager.
- Do not write keys into `.env` unless `.env` is ignored and local-only.
- Do not expose production credentials to agents until approval controls exist.
