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
      async complete({ prompt, instructions } = {}) {
        const response = await fetch("https://api.openai.com/v1/responses", {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${process.env.OPENAI_API_KEY}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: config.openaiModel,
            instructions,
            input: prompt,
            text: {
              format: {
                type: "json_object",
              },
            },
          }),
        });
        const body = await response.text();
        if (!response.ok) {
          throw new Error(`OpenAI Responses API request failed (${response.status}): ${body.slice(0, 1200)}`);
        }
        const json = JSON.parse(body);
        return {
          mode: "openai",
          responseId: json.id,
          text: extractOutputText(json),
          raw: json,
        };
      },
    };
  }

  throw new Error(`Unsupported LLM_PROVIDER: ${config.llmProvider}`);
}

function extractOutputText(response) {
  if (typeof response.output_text === "string" && response.output_text.trim()) {
    return response.output_text;
  }
  const chunks = [];
  for (const item of response.output || []) {
    for (const content of item.content || []) {
      if (typeof content.text === "string") chunks.push(content.text);
    }
  }
  return chunks.join("\n").trim();
}
