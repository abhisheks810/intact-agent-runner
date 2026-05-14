export function getProvider(config) {
  if (config.llmProvider === "none") {
    return {
      name: "none",
      async complete() {
        return {
          mode: "dry-run",
          text: "LLM provider is disabled. Runner selected work and wrote an audit log only.",
        };
      },
    };
  }

  if (config.llmProvider === "openai") {
    if (!process.env.OPENAI_API_KEY) {
      throw new Error("OPENAI_API_KEY is required when LLM_PROVIDER=openai");
    }
    return {
      name: "openai",
      async complete() {
        throw new Error("OpenAI provider adapter is not implemented yet. Add SDK/API call here.");
      },
    };
  }

  throw new Error(`Unsupported LLM_PROVIDER: ${config.llmProvider}`);
}
